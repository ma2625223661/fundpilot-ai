"""Bounded, evidence-only AI interpretation for server-owned automatic scans.

The model adds narratives to measured decisions. It cannot change scores,
transaction eligibility, product terms or the deterministic risk limits.
"""
import copy
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock

from research_categories import BOARDS
from research_service import API_URL, MODELS, SCORE_DEFINITIONS, SYSTEM, provider_json

BATCH_SIZE = 8
MAX_WORKERS = 2
REQUEST_TIMEOUT = 75
MAX_FUNDS = 96


class _SupersededRequest(Exception):
    pass


class _WindowClosedRequest(Exception):
    pass


WINDOW_STOP_REASON = '本次时段已结束，未发出的批次保持量化研究；下个时段重新采集证据。'

AUTO_SYSTEM = SYSTEM + '''
当前为全自动研究，不要求用户手动收集新闻、录入基金或补充分析。所有最新事实必须来自输入证据，缺口明确写成未取得。
requested_fund_codes 仅表示本次请求的一批基金，不是全轮研究范围。summary 如提及输入基金数量，必须写“本批”，不得称为“本轮”总数；baseline 的全轮汇总不得用本批数量覆盖。
每只输入基金必须返回一个独立的 reason、invalidation、evidence_ids 和 operation_plan；不得遗漏或用一段话代替逐只研究。
reason 中分别解释支持证据、反对证据/缺口，invalidation 说明何种变化推翻当前结论。
operation_plan 至少给出 entry_conditions 和 exit_conditions，每项为非空字符串数组。
action 只能保留输入状态或降级为继续观察、暂缓新增；研究候选不等于可执行交易。
基金名称仅为显示标识，不得据此判断行业或板块；使用持仓与各板块的独立核验结果。只研究输入的基金和证据，不改变净值、数学指标、历史研究分、推荐指数、恐慌分、7 天研究下限或交易限制。使用 fund_decision_context 的实际推荐指数、板块与持仓核验解释结论；引用持仓事实时使用该基金提供的持仓 source_id。'''


def _fund_source_ids(fund):
    sources = {str(fund['source_id'])} if fund.get('source_id') else set()
    holdings = fund.get('holdings')
    if (isinstance(holdings, dict) and holdings.get('status') == 'ok'
            and holdings.get('rows') and holdings.get('source_id')):
        sources.add(str(holdings['source_id']))
    return sources


def _metadata(config):
    return {'status': 'not_configured', 'model': config.get('model') or MODELS[0],
            'revision': config.get('revision', config.get('generation')),
            'configuration_enabled': bool(config.get('enabled', True)),
            'request_count': 0, 'requests_attempted': 0, 'requests_succeeded': 0,
            'analyzed_count': 0, 'target_count': 0, 'requested_count': 0,
            'requested_codes': [], 'analyzed_codes': [],
            'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
            'usage_complete': True, 'errors': [], 'error': '', 'terminal_error': False,
            'stopped_for_schedule': False, 'stopped_reason': ''}


def _safe_error(error):
    """Never copy provider bodies, URLs or arbitrary exception text into reports."""
    code = getattr(error, 'status_code', getattr(error, 'code', None))
    message = str(error)
    if code == 401 or 'API Key 无效' in message or '身份验证' in message:
        return 'API Key 无效，请重新配置', True
    if code == 402 or '余额不足' in message:
        return 'DeepSeek 余额不足', True
    if code == 429 or '频率过高' in message:
        return 'DeepSeek 请求频率过高，本轮不自动重试', False
    if '超时' in message or isinstance(error, TimeoutError):
        return 'DeepSeek 连接失败或超时，本次请求可能已被服务端接收', False
    if isinstance(error, (ValueError, TypeError, KeyError, IndexError)):
        return 'AI 未返回有效的逐基金证据解读，保留量化研究', False
    return 'DeepSeek 研究请求未完成，保留量化研究', False


def _allowed_sources(snapshot):
    sources = {str(row['id']) for row in snapshot.get('sources', [])
               if isinstance(row, dict) and row.get('id') and row.get('status') != 'error'}
    sources.update('nav:' + row['code'] for row in snapshot.get('funds', [])
                   if isinstance(row, dict) and row.get('code') and row.get('history'))
    failed = {str(row['id']) for row in snapshot.get('sources', [])
              if isinstance(row, dict) and row.get('id') and row.get('status') == 'error'}
    for row in snapshot.get('funds', []):
        if isinstance(row, dict):
            sources.update(_fund_source_ids(row) - failed)
    sources.update(str(row['source_id']) for row in snapshot.get('news', [])
                   if isinstance(row, dict) and row.get('source_id'))
    return sources


def _texts(value, limit=8):
    return [item.strip()[:1500] for item in value if isinstance(item, str) and item.strip()][:limit] if isinstance(value, list) else []


def _batch_evidence(report, codes):
    """Keep context finite and include each fund's notices before general news."""
    snapshot = report.get('snapshot', {})
    wanted = set(codes)
    funds = [{key: value for key, value in fund.items() if key != 'history'}
             for fund in snapshot.get('funds', []) if fund.get('code') in wanted]
    for fund in funds:
        fund.setdefault('source_id', f'nav:{fund["code"]}')
    decisions = [row for row in report.get('analysis', {}).get('funds', []) if row.get('code') in wanted]
    decision_context = []
    for row in decisions:
        match = row.get('board_match') if isinstance(row.get('board_match'), dict) else {}
        board = BOARDS.get(match.get('board_id'), {})
        decision_context.append({
            'code': row.get('code'), 'score': row.get('score'),
            'recommendation_index': row.get('recommendation_index'),
            'action': row.get('action'), 'execution_eligible': row.get('execution_eligible'),
            'board': {key: board.get(key) for key in ('id', 'label', 'requires_holdings_match')},
            'board_match': match, 'board_matches': row.get('board_matches', [match]),
            'classification_method': row.get('board_classification_method'),
        })
    notices, other = {code: [] for code in codes}, []
    for item in snapshot.get('news', []):
        row = {key: value for key, value in item.items() if key != 'content'}
        if isinstance(row.get('summary'), str):
            row['summary'] = row['summary'][:1600]
        raw = json.dumps(row, ensure_ascii=False)
        if item.get('category') == '基金公告':
            if isinstance(item.get('content'), str) and item['content'].strip():
                row['content'] = item['content'][:2400]
            # Explicit association takes precedence over incidental fund codes
            # mentioned inside another fund's notice text.
            fund_code = item.get('fund_code')
            belongs = [fund_code] if fund_code in wanted else ([code for code in codes if code in raw] if not fund_code else [])
            for code in belongs:
                notices[code].append(row)
        else:
            other.append(row)
    for rows in notices.values():
        rows.sort(key=lambda row: str(row.get('published_at') or ''), reverse=True)
    selected_notices, seen_notices = [], set()
    # Latest notice for every fund first; then fill evenly so an early fund's
    # notice history cannot crowd the final batch funds out of the prompt.
    for offset in range(max((len(rows) for rows in notices.values()), default=0)):
        for code in codes:
            rows = notices[code]
            if offset < len(rows) and id(rows[offset]) not in seen_notices:
                seen_notices.add(id(rows[offset]))
                selected_notices.append(rows[offset])
                if len(selected_notices) >= 24:
                    break
        if len(selected_notices) >= 24:
            break
    notice_coverage = []
    notice_warnings = []
    for code in codes:
        latest = notices[code][0] if notices[code] else {}
        supplied = [row for row in notices[code] if id(row) in seen_notices]
        scope = str(latest.get('content_scope', ''))
        has_excerpt = bool(latest.get('content')) or ('正文节选' in scope and bool(latest.get('summary')))
        notice_coverage.append({'code': code, 'available_notice_count': len(notices[code]),
                                'supplied_notice_count': len(supplied),
                                'latest_published_at': latest.get('published_at'),
                                'latest_has_excerpt': bool(has_excerpt),
                                'content_scope': latest.get('content_scope') or '公告正文覆盖未核验'})
        if not latest:
            notice_warnings.append(f'{code}：本批未取得基金公告，不代表没有公告或事件风险。')
        elif not has_excerpt:
            notice_warnings.append(f'{code}：最新公告仅提供标题/分类，未取得正文节选。')
    news = selected_notices + other[:18]
    referenced = {f'nav:{code}' for code in codes}
    for fund in funds:
        referenced.update(_fund_source_ids(fund))
        holdings = fund.get('holdings')
        if isinstance(holdings, dict) and holdings.get('source_id'):
            referenced.add(str(holdings['source_id']))
    referenced.update(str(row.get('source_id')) for row in news if row.get('source_id'))
    # Market source entries are useful to audit market/panic explanations.
    referenced.update(str(row.get('source_id')) for row in snapshot.get('market', []) if row.get('source_id'))
    sources = [row for row in snapshot.get('sources', []) if str(row.get('id')) in referenced]
    return {'score_definitions': SCORE_DEFINITIONS,
            'preferences': report.get('prefs', {}),
            'fund_decision_context': decision_context,
            'automatic_evidence': {'as_of': snapshot.get('as_of'), 'funds': funds,
                                   'market': snapshot.get('market', [])[:24],
                                   'sentiment': snapshot.get('sentiment', {}),
                                   'news': news, 'sources': sources,
                                   'notice_coverage': notice_coverage,
                                   'warnings': list(dict.fromkeys(snapshot.get('warnings', [])[:20] + notice_warnings))},
            'quantitative_results': [row for row in report.get('quant', []) if row.get('code') in wanted],
            'baseline_decisions_and_operations': {
                **{key: report.get('analysis', {}).get(key) for key in ('summary', 'market_view', 'risks', 'next_steps')},
                'funds': decisions},
            'market_risk_boundaries': report.get('strategy', {}).get('regime', {}),
            'panic': report.get('strategy', {}).get('panic', {}),
            'requested_fund_codes': codes}


def _request_batch(report, codes, config, before_request=None):
    evidence = _batch_evidence(report, codes)
    payload = {'model': config.get('model') or MODELS[0], 'stream': False,
               'max_tokens': 7500, 'thinking': {'type': 'disabled'},
               'response_format': {'type': 'json_object'},
               'messages': [{'role': 'system', 'content': AUTO_SYSTEM},
                            {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)}]}
    # Payload construction can cross the stop time. The final admission check
    # belongs immediately before I/O, not merely before queuing a future.
    if before_request is not None:
        before_request()
    return provider_json(API_URL, config['key'], payload, REQUEST_TIMEOUT)


def _decode_response(response, codes, allowed_sources, fund_sources):
    choice = response['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise ValueError('incomplete response')
    proposed = json.loads(choice['message']['content'])
    if not isinstance(proposed, dict) or any(not isinstance(proposed.get(k), str) or not proposed[k].strip()
                                             for k in ('summary', 'market_view')):
        raise ValueError('missing market interpretation')
    if not isinstance(proposed.get('funds'), list):
        raise ValueError('missing fund interpretations')
    valid, seen = {}, set()
    for row in proposed['funds']:
        if not isinstance(row, dict) or row.get('code') not in codes:
            continue
        code = row['code']
        if code in seen:
            valid.pop(code, None)
            continue
        seen.add(code)
        plan = row.get('operation_plan')
        refs = [ref for ref in row.get('evidence_ids', []) if isinstance(ref, str) and ref in allowed_sources] if isinstance(row.get('evidence_ids'), list) else []
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ('reason', 'invalidation')):
            continue
        if (not set(refs).intersection(fund_sources.get(code, set())) or not isinstance(plan, dict)
                or not _texts(plan.get('entry_conditions')) or not _texts(plan.get('exit_conditions'))):
            continue
        valid[code] = {**row, 'evidence_ids': list(dict.fromkeys(refs))}
    return proposed, valid


def _merge_fund(fund, suggestion):
    """Only the narrative and a conservative action may change."""
    fund['ai_reason'] = suggestion['reason'].strip()[:6000]
    fund['ai_invalidation'] = suggestion['invalidation'].strip()[:6000]
    fund['reason'] = str(fund.get('reason', '')) + '\nAI 证据解读：' + fund['ai_reason']
    fund['invalidation'] = str(fund.get('invalidation', '')) + '\nAI 复查条件：' + fund['ai_invalidation']
    fund['evidence_ids'] = list(dict.fromkeys(fund.get('evidence_ids', []) + suggestion['evidence_ids']))
    plan = fund.setdefault('operation_plan', {})
    proposed_plan = suggestion['operation_plan']
    plan['ai_observations'] = _texts(proposed_plan.get('entry_conditions')) + _texts(proposed_plan.get('exit_conditions'))
    fund['ai_research_status'] = 'completed'
    if fund.get('action') in ('分批配置候选', '7 天以上研究候选') and suggestion.get('action') in ('继续观察', '暂缓新增'):
        fund['action'] = suggestion['action']
        plan['new_position'] = 'AI 证据解读发现尚未澄清的风险，当前暂缓新增并自动复查。'
        plan['existing_position'] = '如已持有，按实际仓位与风险预算复核；当前不安排补仓或新增批次。'
        plan['entry_conditions'] = ['事件风险澄清，且量化、市场及产品交易条件重新通过后再评估研究资格。']
        plan['steps'] = ['当前不安排新增批次。', '系统持续跟踪事件原文、公告日期及量化条件。', '证据更新后自动重新计算研究资格。']


def enrich_auto_report(report, config=None, progress=None, is_current=None, requester=None,
                       can_start_request=None):
    """Return an isolated report; no paid request occurs without eligible evidence.

    ``is_current`` guards credential revisions before every wave and at commit.
    ``requester`` is injectable for deterministic tests and receives one batch.
    ``can_start_request`` gates each new provider call and wave. Once it closes,
    this run stops queuing batches; already sent requests retain their results
    and usage. A later window always starts a new evidence collection run.
    """
    output = copy.deepcopy(report)
    config = dict(config or {})
    meta = _metadata(config)
    output['ai_research'] = meta
    automatic = output.setdefault('automatic', {})
    automatic['paid_api_calls'] = False
    automatic['paid_api_call_count'] = 0
    if not config.get('enabled', True):
        meta['status'] = 'disabled'
        return output
    if not config.get('key'):
        return output
    current = is_current or (lambda: True)
    can_start = can_start_request or (lambda: True)
    notify = progress or (lambda stage, details=None: None)
    snapshot = output.get('snapshot', {})
    evidence_funds = {row.get('code') for row in snapshot.get('funds', []) if row.get('history')}
    analyzed_funds = {row.get('code') for row in output.get('analysis', {}).get('funds', [])}
    targets = list(dict.fromkeys(row['code'] for row in output.get('quant', [])
                                if row.get('quality') == 'ok' and row.get('code') in evidence_funds
                                and row.get('code') in analyzed_funds))[:MAX_FUNDS]
    selected = output.get('universe', {}).get('selected_codes')
    if isinstance(selected, list):
        targets = [code for code in targets if code in set(selected)]
    meta['target_count'] = len(targets)
    if not targets:
        meta['status'] = 'no_evidence'
        return output
    if not current():
        meta['status'] = 'superseded'
        meta['error'] = 'AI 配置已更改，本轮解读未采用，系统将按新配置重新研究。'
        return output
    batches = [targets[start:start + BATCH_SIZE] for start in range(0, len(targets), BATCH_SIZE)]
    window_closed, sent_lock, sent_batches = Event(), Lock(), []

    def request_allowed():
        if window_closed.is_set():
            return False
        try:
            permitted = bool(can_start())
        except Exception:
            # Failure to confirm the window must never authorize a paid call.
            permitted = False
        if not permitted:
            window_closed.set()
        return permitted

    def admit_request(batch):
        if not current():
            raise _SupersededRequest()
        if not request_allowed():
            raise _WindowClosedRequest()
        if not current():
            raise _SupersededRequest()
        with sent_lock:
            sent_batches.append(tuple(batch))

    def sync_request_counts():
        with sent_lock:
            started = list(sent_batches)
        sent_codes = {code for batch in started for code in batch}
        meta['request_count'] = meta['requests_attempted'] = len(started)
        meta['requested_codes'] = [code for code in targets if code in sent_codes]
        meta['requested_count'] = len(meta['requested_codes'])
        automatic['paid_api_call_count'] = len(started)
        automatic['paid_api_calls'] = bool(started)

    def guarded_request(batch):
        if not current():
            raise _SupersededRequest()
        if requester is None:
            return _request_batch(output, batch, config, before_request=lambda: admit_request(batch))
        admit_request(batch)
        return requester(output, batch, config)
    narratives, market_results, fatal = {}, [], False
    meta['status'] = 'running'
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='fundpilot-ai') as pool:
        for start in range(0, len(batches), MAX_WORKERS):
            if not current():
                meta['status'] = 'superseded'
                break
            if not request_allowed():
                break
            tasks = {}
            for batch in batches[start:start + MAX_WORKERS]:
                if not current():
                    break
                if not request_allowed():
                    break
                tasks[pool.submit(guarded_request, batch)] = batch
            sync_request_counts()
            notify(f'AI 正在研究 {len(narratives)} / {len(targets)} 只基金',
                   {'ai_done': len(narratives), 'ai_total': len(targets), 'ai_requests': meta['request_count']})
            for task in as_completed(tasks):
                batch = tasks[task]
                try:
                    response = task.result()
                    usage = response.get('usage') or {}
                    if not isinstance(usage, dict) or not all(isinstance(usage.get(k), int) and not isinstance(usage[k], bool)
                                                            and usage[k] >= 0 for k in meta['usage']):
                        meta['usage_complete'] = False
                    else:
                        for key in meta['usage']:
                            meta['usage'][key] += usage[key]
                    provided = _batch_evidence(output, batch)['automatic_evidence']
                    allowed = _allowed_sources(provided)
                    fund_sources = {row['code']: _fund_source_ids(row) & allowed for row in provided['funds']}
                    for item in provided['news']:
                        code = item.get('fund_code')
                        if code in fund_sources and item.get('source_id'):
                            fund_sources[code].add(str(item['source_id']))
                    proposed, valid = _decode_response(response, batch, allowed, fund_sources)
                    if valid:
                        meta['requests_succeeded'] += 1
                        narratives.update(valid)
                        market_results.append((batch[0], proposed))
                    missing = [code for code in batch if code not in valid]
                    if missing:
                        meta['errors'].append({'codes': missing, 'message': 'AI 未返回有效的逐基金证据解读，保留量化研究'})
                except (_SupersededRequest, _WindowClosedRequest):
                    # These futures never reached the provider. They carry no
                    # usage and must not inflate request/fund counters.
                    pass
                except Exception as error:
                    meta['usage_complete'] = False
                    message, terminal = _safe_error(error)
                    fatal = fatal or terminal
                    meta['terminal_error'] = meta['terminal_error'] or terminal
                    meta['errors'].append({'codes': batch, 'message': message})
            sync_request_counts()
            if fatal or window_closed.is_set():
                break
    sync_request_counts()
    if not current():
        # A replaced key/model must never attach its old narratives to a fresh report.
        meta['status'] = 'superseded'
        meta['error'] = 'AI 配置已更改，本轮解读未采用，系统将按新配置重新研究。'
        return output
    downgraded = []
    for fund in output.get('analysis', {}).get('funds', []):
        if fund.get('code') in narratives:
            old_action = fund.get('action')
            _merge_fund(fund, narratives[fund['code']])
            if fund.get('action') != old_action:
                downgraded.append(fund['code'])
    if downgraded:
        strategy = output.setdefault('strategy', {})
        removed = set(downgraded)
        strategy['candidates'] = [row for row in strategy.get('candidates', []) if row.get('code') not in removed]
        strategy['ai_downgraded_codes'] = downgraded
        exclusions = strategy.setdefault('excluded_candidates', [])
        for code in downgraded:
            exclusions.append({'code': code, 'reason': 'AI 证据复核提示未澄清风险，本轮暂缓新增并自动跟踪。'})
        analysis = output['analysis']
        analysis['quantitative_summary'] = analysis.get('summary', '')
        label = strategy.get('regime', {}).get('label', '等待数据')
        count = len(strategy['candidates'])
        analysis['summary'] = label + ' · ' + (f'{count} 只保留至少 7 天的中高风险研究候选。' if count else
                                               'AI 证据复核后，本轮没有保留的中高风险研究候选。')
    if market_results:
        _, market = sorted(market_results, key=lambda item: targets.index(item[0]))[0]
        analysis = output['analysis']
        analysis['ai_summary'] = market['summary'].strip()[:6000]
        analysis['ai_market_view'] = market['market_view'].strip()[:10000]
        analysis['summary'] = str(analysis.get('summary', '')) + '\nAI 市场概括：' + analysis['ai_summary']
        analysis['market_view'] = str(analysis.get('market_view', '')) + '\nAI 证据解读：' + analysis['ai_market_view']
        analysis['risks'] = list(dict.fromkeys(analysis.get('risks', []) + _texts(market.get('risks'))))
    meta['analyzed_codes'] = [code for code in targets if code in narratives]
    meta['analyzed_count'] = len(meta['analyzed_codes'])
    meta['status'] = 'completed' if len(narratives) == len(targets) else ('partial' if narratives else 'error')
    if window_closed.is_set() and len(narratives) < len(targets):
        meta.update(stopped_for_schedule=True, stopped_reason=WINDOW_STOP_REASON)
        if not fatal:
            meta['status'] = 'window_closed'
    if meta['errors']:
        meta['error'] = meta['errors'][0]['message']
    output['model'] = meta['model'] + ' + 自动量化研究' if narratives else output.get('model', '自动量化研究')
    # The automatic engine identity is stable even when AI is enabled.
    output['engine'] = 'automatic'
    return output
