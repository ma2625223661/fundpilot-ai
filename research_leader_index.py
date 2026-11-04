"""Independent, transparent indicators built from dated leading-company samples.

These are research baskets, not official sector indices. Current membership is
held fixed over the displayed retrospective window; no historical leadership or
investable/backtested return is claimed. No external model creates prices.
"""
from __future__ import annotations

import copy
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from research_data import CHINA, fetch_text, now_iso
from research_trading_calendar import is_trading_day, last_closed_trading_day, a_share_quote_fresh
from research_sample_policy import MAX_SAMPLES, fair_codes
from research_numbers import finite_number as finite

VERSION = 'leader_equal_weight_v1'
MIN_HISTORY = 61
METHOD = ('自建龙头样本指标 v1：在已核验归属候选池内筛选至多8家数据完整的公司，等权；'
          '优先保留4家市值/固定池代表，其余按披露盈利和增长条件补充；'
          '共同历史首日设100，每日以各样本前复权收盘收益率的算术平均连乘。'
          '样本固定于本轮选择，历史为当前样本回溯，不是历史龙头组合、官方指数或策略回测；'
          '不计交易成本，换样后起点和历史可重算，不跨轮拼接。'
          '至少2只有效样本、全部样本具备共同近期61个交易日才生成综合分。'
          '综合分还须满足有效数据、明确映射、专用模型三项条件，包括已核验披露日的公司财务证据。'
          '指标编制与研究评分分别版本化；板块研究分采用基本面0–40、走势0–30、事件催化±30。'
          '缺失证据保留待评估状态；大盘风险独立展示。未经收益回测，不是上涨概率。')


def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=CHINA) if parsed.tzinfo is None else parsed.astimezone(CHINA)
    except (TypeError, ValueError):
        return None


def last_close_day(as_of):
    return last_closed_trading_day(as_of)


def history_url(code):
    symbol = code[-2:].lower() + code[:6]
    return 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=' + symbol + ',day,,,121,qfq'


def parse_history(payload, code, as_of):
    symbol = code[-2:].lower() + code[:6]
    series = payload.get('data', {}).get(symbol, {}) if isinstance(payload, dict) else {}
    raw = series.get('qfqday') or series.get('day')
    if not isinstance(raw, list):
        raise ValueError('公司日线未返回对应证券的有效序列')
    cutoff = last_close_day(as_of)
    if cutoff is None:
        raise ValueError('交易日历无法核验')
    rows = {}
    for row in raw:
        if not isinstance(row, list) or len(row) < 3:
            continue
        day = str(row[0])
        try:
            datetime.strptime(day, '%Y-%m-%d')
            close = float(row[2])
        except (ValueError, TypeError):
            continue
        if day > cutoff or not math.isfinite(close) or close <= 0 or not is_trading_day(datetime.fromisoformat(day).date()):
            continue
        rows[day] = {'date': day, 'close': close}
    return [rows[day] for day in sorted(rows)][-121:]


def collect_leader_histories(company, as_of):
    """Bound requests to the already selected companies; persist reusable data."""
    from research_public_data import _get, _remember, _fetched_at, _save
    import re
    selected = {r['ts_code'] for rows in company.get('sector_leaders', {}).values() for r in rows
                if isinstance(r, dict) and re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(r.get('ts_code', '')))}
    codes = [code for code in fair_codes(company.get('sector_leaders', {})) if code in selected]
    sources = []
    cutoff = last_close_day(as_of)
    prior = {r['ts_code']: r for rows in company.get('sector_leaders', {}).values() for r in rows if r.get('ts_code') in selected}

    def fetch(code):
        key = 'leader_history:' + code + ':' + str(cutoff)
        cached = _get(key)
        existing = prior.get(code, {})
        if cached is None and not code.endswith('.BJ') and existing.get('history') and existing.get('price_adjustment') == 'forward_adjusted':
            from research_evidence_resilience import complete_history
            if complete_history(existing['history'], as_of):
                source = next((s for s in company.get('sources', []) if s.get('id') == 'leader_history:' + code), {})
                if source.get('url'):
                    cached = {'rows': existing['history'], 'provider': 'baostock' if 'baostock' in source['url'] else 'tencent',
                              'url': source['url'], 'original_fetched_at': source.get('fetched_at')}
                    _remember(key, cached, 8 * 86400)
        provider, url, metadata = 'tencent', history_url(code), {}
        if isinstance(cached, dict):
            rows = cached.get('rows', [])
            provider, url = cached.get('provider', 'tencent'), cached.get('url', url)
            metadata = cached.get('metadata') or {}
        else:
            rows = cached
        if cached is None:
            rows = parse_history(json.loads(fetch_text(history_url(code))), code, as_of)
            if rows:
                _remember(key, rows, 8 * 86400)
        fetched_at = cached.get('original_fetched_at') if isinstance(cached, dict) else None
        return rows or [], fetched_at or _fetched_at(key), '', provider, url, metadata

    pool = ThreadPoolExecutor(max_workers=12)
    futures = {pool.submit(fetch, code): code for code in codes}
    result = {}
    try:
        for future in as_completed(futures, timeout=60):
            code = futures[future]
            try:
                result[code] = future.result()
            except Exception as error:
                from research_transport import source_error
                result[code] = ([], now_iso(), source_error(error, '公司历史数据未取得'), 'tencent', history_url(code), {})
    except TimeoutError:
        pass
    finally:
        for future, code in futures.items():
            if code not in result:
                future.cancel()
                result[code] = ([], now_iso(), '本轮公司日线采集超时', 'tencent', history_url(code), {})
        pool.shutdown(wait=False, cancel_futures=True)
    required = set()
    if cutoff:
        day = datetime.fromisoformat(cutoff).date()
        for _ in range(240):
            if is_trading_day(day):
                required.add(day.isoformat())
            if len(required) >= MIN_HISTORY:
                break
            day -= timedelta(days=1)
    missing = [code for code, item in result.items() if code.endswith(('.SH', '.SZ'))
               and not (len(required) == MIN_HISTORY and required.issubset(r['date'] for r in item[0]))]
    if missing:
        from research_leader_history_fallback import fetch_a_share_histories
        # Replace a whole adjusted series, never splice two providers' prices.
        for start in range(0, len(missing), 60):
            try:
                fallbacks = fetch_a_share_histories(missing[start:start+60], as_of)
            except Exception:
                fallbacks = {}
            for code, fallback in fallbacks.items():
                rows = fallback.get('rows', [])
                original = result[code]
                if rows and (required.issubset(r['date'] for r in rows) or len(rows) > len(original[0])):
                    prior_name = 'BaoStock' if original[3] == 'baostock' else '腾讯财经'
                    sources.append({'id': 'leader_history_primary:' + code,
                        'name': prior_name + ' · 公司日线前次来源 ' + code, 'url': original[4],
                        'status': 'partial' if original[0] else 'error', 'count': len(original[0]),
                        'as_of': original[0][-1]['date'] if original[0] else None,
                        'fetched_at': original[1], 'error': original[2] or '近期日线不足，已使用BaoStock备用来源'})
                    url = fallback['url']
                    result[code] = (rows, fallback['fetched_at'], '', 'baostock', url, {})
                    _remember('leader_history:' + code + ':' + str(cutoff),
                              {'rows': rows, 'provider': 'baostock', 'url': url}, 8 * 86400)
    missing_bj = [code for code, item in result.items() if code.endswith('.BJ')
                  and not (len(required) == MIN_HISTORY and required.issubset(r['date'] for r in item[0]))]
    if missing_bj:
        from research_beijing_history import fetch_histories
        members = {r['ts_code']: r for rows in company.get('sector_leaders', {}).values() for r in rows}
        fallbacks = fetch_histories([members[code] for code in missing_bj], as_of)
        for code, fallback in fallbacks.items():
            rows, original = fallback.get('rows', []), result[code]
            if rows and required.issubset(r['date'] for r in rows):
                sources.append({'id': 'leader_history_primary:' + code, 'name': '腾讯财经 · 公司日线前次来源 ' + code,
                    'url': original[4], 'status': 'partial' if original[0] else 'error', 'count': len(original[0]),
                    'as_of': original[0][-1]['date'] if original[0] else None,
                    'fetched_at': original[1], 'error': original[2] or '日线不足，已核验新浪备用来源'})
                metadata = {k: fallback[k] for k in ('factor_url', 'identity_url', 'method')}
                result[code] = (rows, fallback['fetched_at'], '', 'sina_bj', fallback['url'], metadata)
                _remember('leader_history:' + code + ':' + str(cutoff),
                    {'rows': rows, 'provider': 'sina_bj', 'url': fallback['url'], 'metadata': metadata}, 8*86400)
            elif fallback.get('error'):
                result[code] = (*original[:2], original[2] + '；' + fallback['error'], *original[3:])
    for code, (rows, fetched_at, error, provider, url, metadata) in result.items():
        fresh = bool(rows and rows[-1]['date'] == cutoff)
        name = '新浪财经' if provider == 'sina_bj' else 'BaoStock' if provider == 'baostock' else '腾讯财经'
        sources.append({'id': 'leader_history:' + code, 'name': name + ' · 公司前复权日线 ' + code,
            'url': url, 'status': 'ok' if fresh and required.issubset(r['date'] for r in rows) else 'partial' if rows else 'error',
            'count': len(rows), 'as_of': rows[-1]['date'] if rows else None, 'fetched_at': fetched_at,
            'error': error or ('' if fresh else '日线未覆盖最近已收盘交易日')})
        if provider == 'sina_bj':
            for kind, title in (('factor', '前复权因子'), ('identity', '证券身份及收盘交叉核对')):
                sources.append({'id': 'leader_history_' + kind + ':' + code, 'name': '新浪财经 · ' + title + ' ' + code,
                    'url': metadata[kind + '_url'], 'status': 'ok', 'count': 1,
                    'as_of': rows[-1]['date'], 'fetched_at': fetched_at, 'error': '', 'method': metadata['method']})
    for rows in company.get('sector_leaders', {}).values():
        for row in rows:
            code = row.get('ts_code')
            if code not in selected:
                continue
            row['history'] = copy.deepcopy(result.get(code, ([], '', ''))[0])
            row['history_count'] = len(row['history'])
            if code in result:
                row['source_ids'] = list(dict.fromkeys(row.get('source_ids', []) + ['leader_history:' + code]))
                row['price_adjustment'] = 'forward_adjusted'
                if result[code][3] == 'sina_bj':
                    row['source_ids'] += ['leader_history_factor:' + code, 'leader_history_identity:' + code]
    company.setdefault('sources', []).extend(sources)
    _save()
    return company


def build_indicator(board, leaders, as_of):
    if board.get('group') == 'overseas' and leaders:
        from research_overseas import build_overseas_indicator
        return build_overseas_indicator(board, leaders, as_of)
    if board.get('group') not in {'industry', 'style', 'broad'} or not leaders:
        return None
    # Samples need dated membership evidence, dated prices, and source ids. An
    # arbitrary named company alone can never become an index constituent.
    valid, excluded, seen = [], [], set()
    now = stamp(as_of)
    for row in leaders[:MAX_SAMPLES]:
        code, quote = row.get('ts_code'), row.get('quote') or {}
        when = stamp(row.get('as_of'))
        member = row.get('membership_evidence') or {}
        member_day = stamp(member.get('snapshot_date'))
        evidence_ok = bool(member.get('l1_name') and row.get('source_ids') and member_day and now
                           and 0 <= (now.date() - member_day.date()).days <= 45)
        price_ok = (when and now and a_share_quote_fresh(row.get('as_of'), as_of, daily=not quote.get('is_intraday'))
                    and finite(quote.get('pct_chg')) and finite(quote.get('close')) and quote['close'] > 0)
        if code in seen or not evidence_ok or not price_ok:
            excluded.append({'code': code or '', 'reason': '归属证据缺失/过期，或报价缺失/过期/重复'})
            continue
        seen.add(code)
        valid.append(row)
    if not valid:
        return None
    # Do not merge quotations from different sessions into a single snapshot.
    if len({stamp(r['as_of']).date() for r in valid}) != 1 or len({bool(r['quote'].get('is_intraday')) for r in valid}) != 1:
        return None
    histories = []
    cutoff = last_close_day(as_of)
    if cutoff is None:
        return None
    for row in valid:
        points = {r.get('date'): r.get('close') for r in row.get('history', [])
                  if isinstance(r, dict) and isinstance(r.get('date'), str) and finite(r.get('close'))
                  and r['close'] > 0 and r['date'] <= cutoff}
        histories.append(points)
    days = sorted(set.intersection(*(set(h) for h in histories))) if histories else []
    series = []
    value = 100.0
    for index, day in enumerate(days):
        ret = sum(h[day] / h[days[index-1]] - 1 for h in histories) / len(histories) if index else 0
        value *= 1 + ret
        series.append({'date': day, 'close': value, 'return_pct': ret * 100 if index else None})
    live = bool(valid[0]['quote'].get('is_intraday'))
    daily = sum(r['quote']['pct_chg'] for r in valid) / len(valid)
    if not live and series and days[-1] == cutoff and len(series) >= 2:
        daily = series[-1]['return_pct']
    last = (series[-1]['close'] * (1 + daily / 100) if live else series[-1]['close']) if series and days[-1] == cutoff else None
    recent, day = set(), datetime.fromisoformat(cutoff).date()
    for _ in range(240):
        opened = is_trading_day(day)
        if opened is None:
            break
        if opened:
            recent.add(day.isoformat())
        if len(recent) >= MIN_HISTORY:
            break
        day -= timedelta(days=1)
    ready = (len(valid) >= 2 and len(valid) == min(len(leaders), MAX_SAMPLES)
             and len(recent) == MIN_HISTORY and recent.issubset(days))
    business_samples = any(r.get('membership_evidence', {}).get('evidence_type') in {'official_business', 'public_business', 'official_index_business'} for r in valid)
    fixed_samples = any(r.get('membership_evidence', {}).get('evidence_type') == 'official_fixed_sample' for r in valid)
    if fixed_samples:
        scope = ('先前已核验官方指数归属的固定公司样本；本轮完整成分名单未取得，沿用原日期的有限样本，'
                 '未重新核对完整名单或进行全成分市值排名，不代表全板块或主营市占率龙头认证。')
        method = METHOD.replace('在已核验归属候选池内筛选至多8家数据完整的公司', '使用先前已核验官方归属的固定有限样本，至多8家公司')
        mapping_basis = '本网站独立编制：先前已核验官方归属的固定样本等权（本轮完整成分未取得）'
    elif business_samples:
        scope = '已核对公开业务证据的指定代表公司样本；仅在核验样本池内按市值选取，不代表全部主题成分或主营市占率排名。'
        method = METHOD.replace('在已核验归属候选池内筛选至多8家数据完整的公司', '在已核验公开业务证据池内筛选至多8家数据完整的公司')
        mapping_basis = '本网站独立编制：已核对公开业务证据样本等权'
    else:
        scope = '当前官方成分池内市值代表及财务条件补充样本；不代表全板块。主营业务市占率龙头身份未作认证。'
        method = METHOD
        mapping_basis = '本网站独立编制：已披露成分内市值领先样本等权，不依赖官方板块报价'
    index_label = '龙头样本指标'
    if board['id'] == 'sector_brain_computer':
        index_label = '研究关联样本指标'
        scope = ('已核对官方脑机接口设备或临床研究合作事实的有限样本池，不代表脑机接口主营收入龙头。'
                 '财务数据为上市公司整体财务，不是脑机接口业务分部财务；研究合作、试验或拟建项目不等同现有规模产品收入。')
        method = method.replace('自建龙头样本指标 v1', '脑机接口研究关联样本指标 v1')
        mapping_basis = '本网站独立编制：脑机接口设备及临床研究关联样本等权，非主题收入排名'
    elif board['id'] == 'commodities':
        index_label = '资源企业股票样本指标'
        scope = ('已核对公开业务证据的金属采矿与油气资源企业股票有限样本；仅在核验池内按市值选取，'
                 '不是全资源行业排名。财务为上市公司整体财务；不代表煤炭、农产品等全部商品，'
                 '不是商品现货或期货价格。可能与黄金矿业、油气及其他资源股票方向重叠，不能视为独立资产。')
        method = method.replace('自建龙头样本指标 v1', '资源企业股票样本指标 v1')
        mapping_basis = '本网站独立编制：已核验金属采矿及油气业务的资源企业股票等权，非商品价格指数'
    elif board['id'] == 'style_microcap':
        index_label = '小市值样本指标'
        scope = ('在国证A股指数完整成分快照内，对本轮已取得有效市值报价且非ST/退市标记的股票，'
                 '按市值从小到大取12家候选，核验财务和近期走势后等权取至多8家。'
                 '此处为有限小市值股票样本，不是官方微盘指数，不保证包含全市场最小股票；'
                 '缺报价、停牌及新股历史不足可能影响覆盖，未采用母指数涨跌冒充微盘走势。')
        method = method.replace('自建龙头样本指标 v1', '自建小市值样本指标 v1')
        method = method.replace('优先保留4家市值/固定池代表', '优先保留4家小市值代表')
        method = method.replace('不是历史龙头组合', '不是历史小市值组合')
        mapping_basis = '本站独立编制：国证A股成分核验池内按当前市值从小到大筛选的有限股票样本'
    meta = {'id': 'leader:' + board['id'], 'version': VERSION, 'name': board['title'] + ' · ' + index_label,
        'scope': scope,
        'method': method, 'weighting': '等权 · 每日收益率平均', 'base_value': 100,
        'base_date': days[0] if days else None, 'history_end': days[-1] if days else None,
        'history_count': len(series), 'sample_count': len(valid), 'minimum_samples': 2,
        'ready': ready, 'is_intraday': live, 'value': round(last, 4) if last else None,
        'as_of': min(r['as_of'] for r in valid), 'excluded': excluded,
        'constituents': [{'code': r['ts_code'], 'name': r.get('name', r['ts_code']),
            'weight_pct': 100 / len(valid), 'as_of': r['as_of'],
            'membership_date': r['membership_evidence']['snapshot_date'],
            'selection_basis': r.get('selection_basis', ''), 'source_ids': r.get('source_ids', [])} for r in valid],
        'history': [{'date': r['date'], 'value': round(r['close'], 4)} for r in series]}
    if any(r['quote'].get('retained_close') for r in valid):
        meta['data_recovery'] = 'verified_close'
        meta['data_note'] = '盘中报价未齐，使用最近已收盘交易日的完整样本日线；日期及数据来源保留，不代表当前盘中涨跌。'
        meta['scope'] += ' ' + meta['data_note']
    if live and last and now:
        meta['live_point'] = {'date': now.date().isoformat(), 'value': round(last, 4), 'as_of':meta['as_of']}
    quote = {'code': meta['id'], 'name': meta['name'], 'last': last, 'change_pct': daily,
        'as_of': meta['as_of'], 'source_id': meta['id'], 'history_secid': meta['id'],
        'mapping_basis': mapping_basis,
        'scope_note': meta['scope'], 'data_frequency': 'intraday' if live else 'daily',
        'as_of_precision': 'datetime', 'asset_type': 'equity', 'is_custom': True}
    source = {'id': meta['id'], 'name': meta['name'] + ' · 本站计算', 'url': None,
        'status': 'ok' if ready else 'partial', 'as_of': meta['as_of'], 'fetched_at': now_iso(),
        'count': len(series), 'scope': meta['scope'], 'error': '' if ready else '至少2只且全部选定样本需共同近期61个日线点；当前只展示已取得的样本数据'}
    return {'meta': meta, 'quote': quote, 'history': series, 'source': source}


def refresh_custom_scores(report):
    """Recompute idempotently after official event assessment or retention."""
    from research_balanced_score import VERSION as SCORE_VERSION, score_company, research_tier, apply_market_risks
    apply_market_risks(report)
    for sector in report.get('sector_analysis', []):
        if sector.get('score_model') != SCORE_VERSION:
            continue
        if 'requirements' in sector:
            from research_sectors import enforce_score_requirements
            if not enforce_score_requirements(sector):
                continue
        if not sector.get('custom_index', {}).get('ready'):
            continue
        result=score_company(sector, report.get('event_analysis') or {}, report.get('as_of'))
        if result is None:
            sector.update(score=None, recommendation_index=None, research_score=None, score_status='unavailable',
                          research_tier=research_tier(None,None,None,None,False), signal='neutral')
            continue
        breakdown=result['breakdown'];finance=breakdown['fundamentals']['points'];trend=breakdown['trend']['points']
        event=breakdown['catalysts']
        sector.update(score=result['score'], recommendation_index=result['score'], research_score=result['complete_score'],
            confirmed_score=result['base_score'], score_status=result['score_status'], score_maximum=result['score_maximum'],
            score_coverage_pct=result['coverage_pct'], score_possible_range=result['possible_range'],
            score_breakdown=breakdown, score_components={'fundamental_points':finance,'trend_points':trend,
                'catalyst_points':event['observed_adjustment']}, event_score_status=event['status'],
            research_tier=research_tier(result['score'],finance,trend,event['points'],result['score_status']=='complete'))
        for key in ('score_cap','financial_adjustment','technical_score'):
            sector.pop(key,None)
        sample_label = ('研究关联样本分析' if sector['id'] == 'sector_brain_computer' else
                        '资源企业股票样本分析' if sector['id'] == 'commodities' else
                        '小市值样本分析' if sector['id'] == 'style_microcap' else '龙头样本分析')
        stage='板块研究分' if result['score_status']=='complete' else '阶段分（事件或财务待完整评估）'
        sector['summary'] = (f'{sample_label}：{sector["trend"]}，{stage} {result["score"]:.2f}/{result["score_maximum"]}；'
                             f'{sector["research_tier"]["label"]}；{sector["risk"]}。')
        metrics = sector.get('metrics') or {}
        mode=report.get('strategy',{}).get('regime',{}).get('mode','unknown')
        strong = (sector.get('status') == 'ok' and sector['research_tier']['id']=='optimistic'
                  and mode not in {'cautious','defensive','unknown'}
                  and sector.get('market_risk',{}).get('status')=='complete' and sector['market_risk']['score']<65
                  and sector.get('severity') != 'critical' and sector.get('risk') != '高风险'
                  and all(finite(metrics.get(key)) and metrics[key] > 0
                          for key in ('return_5d', 'return_20d', 'ma20_gap')))
        previous_star = sector.get('signal') == 'trend_excellent'
        sector['signal'] = 'trend_excellent' if strong else 'neutral'
        if strong:
            sector['indicator_reason'] = '趋势优：完整研究分达到乐观档，5日及20日上涨且高于20日均线，大盘风险证据完整且未触发高风险。'
        elif previous_star and sector.get('severity') != 'critical':
            sector['indicator_reason'] = ''
    coverage=report.setdefault('coverage',{})
    companies=[s for s in report.get('sector_analysis',[]) if s.get('score_model')==SCORE_VERSION]
    coverage.update(company_complete_score_count=sum(s.get('score_status')=='complete' for s in companies),
        company_provisional_score_count=sum(s.get('score_status')=='provisional' for s in companies),
        optimistic_company_count=sum(s.get('research_tier',{}).get('id')=='optimistic' for s in companies))
    return report


def apply_indicator(sector, bundle, leaders, as_of=None):
    from research_balanced_score import VERSION as SCORE_VERSION, METHOD as SCORE_METHOD, score_company
    sector.update(research_basis='leader_sample', custom_index=bundle['meta'],
                  score_scope='company_composite', score_label='板块研究分', leaders=copy.deepcopy(leaders),
                  analysis_scope=bundle['meta']['scope'], score_model=SCORE_VERSION, score_method=SCORE_METHOD)
    sample_label = ('研究关联样本指标' if sector['id'] == 'sector_brain_computer' else
                    '资源企业股票样本指标' if sector['id'] == 'commodities' else
                    '小市值样本指标' if sector['id'] == 'style_microcap' else '龙头样本指标')
    sector['reasons'].insert(0, '本网站独立编制' + sample_label + '；样本名单、等权权重、时点和共同历史均可查。')
    sector['risks'].insert(0, '采用本轮选定样本回溯历史，存在选样及幸存者偏差；不是整个板块的历史收益。')
    for key in ('technical_score','financial_adjustment','score_cap'):
        sector.pop(key,None)
    result=score_company(sector,{},as_of or sector.get('as_of')) if bundle['meta']['ready'] else None
    sector.update(score=result['score'] if result else None, recommendation_index=result['score'] if result else None,
                  score_components={}, research_score=None, score_status='provisional' if result else 'unavailable')
    if not bundle['meta']['ready']:
        sector.update(score=None, recommendation_index=None, status='partial', trend='样本数据待补齐',
            risk='样本覆盖不足', severity='normal', signal='neutral', indicator_reason='',
            summary='已建立独立' + sample_label + '；共同近期历史或样本数量不足，暂不生成综合分。', history_complete=False)
        sector['data_gaps'].append({'code': 'leader_history_incomplete',
            'message': bundle['source']['error'], 'source_ids': [bundle['source']['id']]})
    sector['data_status_summary'] = ('自建' + sample_label + ' · ' + str(bundle['meta']['sample_count']) + '只等权样本 · '
        + str(bundle['meta']['history_count']) + '个共同历史点')
    return sector
