"""Public quote refresh and dated interpretation reuse. Never invokes a model."""
import copy
import hashlib
import json
import re

from research_data import now_iso


def retain_verified_closes(company, previous, as_of):
    """A failed live request cannot erase an exact, still-current daily close.

    Never retain an intraday tick or resurrect a removed constituent. Retained
    sources keep their original dates; this is not a fresh realtime quotation.
    """
    from research_trading_calendar import a_share_quote_fresh
    old = {row.get('ts_code'):row for rows in previous.get('sector_leaders',{}).values() for row in rows}
    for rows in company.get('sector_leaders',{}).values():
        for row in rows:
            code = row.get('ts_code','')
            prior = old.get(code) or {}
            quote = prior.get('quote') or {}
            if (row.get('quote') or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',code)
                    or quote.get('is_intraday') or not quote.get('close')
                    or not a_share_quote_fresh(prior.get('as_of'),as_of,daily=True)):
                continue
            identity = 'public:retained_close:'+code
            row.update(quote=copy.deepcopy(quote),as_of=prior.get('as_of'))
            row['quote']['retained_close']=True
            row['quote']['retained_reason']='本轮报价未取得，沿用仍覆盖最新已收盘交易日的原始收盘数据。'
            row['market_metrics']=copy.deepcopy(prior.get('market_metrics') or {})
            row['source_ids']=list(dict.fromkeys(row.get('source_ids',[])+[identity]))
            company.setdefault('sources',[]).append({'id':identity,'name':'腾讯财经 · 已核验收盘缓存 '+code,
                'url':'https://qt.gtimg.cn/q='+code[-2:].lower()+code[:6], 'status':'ok',
                'as_of':prior.get('as_of'),'cache_used':True,'checked_at':as_of,
                'note':row['quote']['retained_reason']})
    return company


def retain_reference_closes(matches, histories, sources, previous, as_of):
    """Reuse whole exact reference pairs, only while their native dates validate."""
    from research_sectors import _quote_fresh, _history_fresh, MIN_HISTORY
    from research_review_evidence import local_history
    retained=[]
    old_sources={s.get('id'):s for s in previous.get('snapshot',{}).get('sources',[])}
    for sector in previous.get('sector_analysis',[]):
        identity=sector.get('id');quote=sector.get('quote') or {}
        if not quote or quote.get('is_custom') or not _quote_fresh(quote,as_of):
            continue
        current=matches.get(identity) or {}
        if current and len(histories.get(current.get('history_secid'),[]))>=MIN_HISTORY and _history_fresh(histories[current['history_secid']],current,as_of):
            continue
        rows=local_history(sector,previous)
        if len(rows)<MIN_HISTORY or not _history_fresh(rows,quote,as_of):
            continue
        cached=copy.deepcopy(quote)
        cached['cache_used']=True
        cached['scope_note']=(cached.get('scope_note') or '')+' 本轮来源未取得完整更新，沿用仍有效的已核验收盘缓存；保留原始日期。'
        matches[identity]=cached
        histories[cached['history_secid']]=rows
        retained.append(identity)
        for key in (quote.get('source_id'),'sector_history:'+quote['history_secid']):
            if key in old_sources:
                source=copy.deepcopy(old_sources[key]);source.update(cache_used=True,checked_at=as_of,
                    note='本轮更新未齐，使用仍符合本地收盘日期要求的已核验缓存。')
                sources.append(source)
    return retained


def refresh_company_quotes(previous, as_of):
    from research_public_data import fetch_quotes, _parallel
    company = copy.deepcopy(previous)
    codes = sorted({r['ts_code'] for rows in company.get('sector_leaders', {}).values() for r in rows
                    if re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', str(r.get('ts_code', '')))})
    batches = [tuple(codes[i:i+100]) for i in range(0, len(codes), 100)]
    prices, sources = {}, []
    for batch, (rows, error) in _parallel(batches, lambda b: fetch_quotes(b, as_of), 45, workers=8).items():
        prices.update(rows or {})
        sources.append({'id': 'public:live_quotes:' + str(batches.index(batch)),
            'name': '腾讯财经 · 固定研究样本最新行情',
            'url': 'https://qt.gtimg.cn/q=' + ','.join(c[-2:].lower()+c[:6] for c in batch),
            'status': 'ok' if len(rows or {}) == len(batch) else 'partial' if rows else 'error',
            'count': len(rows or {}), 'as_of': max((r['as_of'] for r in (rows or {}).values()), default=None),
            'fetched_at': now_iso(), 'error': error or ('' if len(rows or {}) == len(batch) else '部分样本报价未取得，不以旧报价补造盘中数值')})
    for rows in company.get('sector_leaders', {}).values():
        for row in rows:
            code = row.get('ts_code', '')
            if code not in codes:  # Other markets retain their own disclosed session dates.
                continue
            row['source_ids'] = [s for s in row.get('source_ids', [])
                                 if not s.startswith(('public:quotes:', 'public:live_quotes:'))]
            row['source_ids'] += [s['id'] for s in sources if code[-2:].lower()+code[:6] in s['url']]
            price = prices.get(code)
            if not price:
                row.update(quote={}, as_of=None)
                continue
            row.update(as_of=price['as_of'], quote={k: price[k] for k in
                ('trade_date', 'close', 'pct_chg', 'amount', 'is_intraday')})
            row['quote']['data_kind'] = 'realtime' if price['is_intraday'] else 'daily_close'
            row['quote']['units'] = {'amount': '元'}
            row['market_metrics'] = {k: price.get(k) for k in ('total_mv','turnover_rate','pe_ttm','pb')}
    company['sources'] = [s for s in company.get('sources', [])
                          if not s.get('id', '').startswith(('public:quotes:', 'public:live_quotes:'))] + sources
    company['live_sample_policy'] = '盘中固定本日已核验样本，仅更新报价；财务与样本池在完整采集时复核。'
    return retain_verified_closes(company,previous,as_of)


def event_signatures(report):
    from research_event_ai import _eligible_event_candidates
    return {r['id']: hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest() for r in _eligible_event_candidates(report)}


def retain_interpretations(report, previous, config):
    """Reuse only dated results, without changing their unlock identity/price."""
    from research_schedule import parse_schedule_time
    from research_event_ai import refresh_event_indicators
    from research_sector_ai import _research_action
    from research_subscriptions import NARRATIVE_FIELDS, content_identity
    now = parse_schedule_time(report.get('as_of'))
    old_ai = previous.get('ai_research') or {}
    revision = config.get('revision', config.get('generation'))
    if old_ai.get('revision') != revision or not config.get('enabled'):
        return report
    old = previous.get('event_analysis') or {}
    assessed_at = parse_schedule_time(old.get('generated_at') or old.get('as_of'))
    current_signatures = event_signatures(report)
    previous_signatures = old.get('candidate_signatures') or event_signatures(previous)
    if (old.get('revision') == revision and old.get('status') in ('completed','partial','no_evidence')
            and now and assessed_at and 0 <= (now-assessed_at).total_seconds() <= 7*86400):
        retained = copy.deepcopy(old)
        retained.update(retained=True, request_count=0, usage={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},
                        eligible_count=len(current_signatures), candidate_count=len(report.get('event_candidates', [])))
        matching = {k for k in current_signatures if current_signatures[k] == previous_signatures.get(k)}
        retained['events'] = [e for e in retained.get('events', []) if e.get('event_id') in matching]
        scarcity = retained.get('scarcity_analysis')
        if isinstance(scarcity,dict):
            scarcity['assessments'] = [r for r in scarcity.get('assessments',[]) if r.get('event_id') in matching]
            scarcity['assessed_event_ids'] = [i for i in scarcity.get('assessed_event_ids',[]) if i in matching]
        if isinstance(retained.get('source_verifications'),dict):
            retained['source_verifications'] = {k:v for k,v in retained['source_verifications'].items() if k in matching}
        if current_signatures != previous_signatures:
            retained.update(status='partial', assessed_count=len({e.get('event_id') for e in retained['events']}), selected_count=len(current_signatures),
                            error='事件证据已有变化，新增或变更内容等待下一研究时段评估。')
        report['event_analysis'] = retained
        refresh_event_indicators(report)
    old_rows = {r['id']:r for r in previous.get('sector_analysis', [])}
    old_sources = {s.get('id'):s for s in previous.get('snapshot', {}).get('sources', []) if isinstance(s,dict)}
    current_sources = {s.get('id') for s in report.get('snapshot', {}).get('sources', []) if isinstance(s,dict)}
    reused = []
    for row in report.get('sector_analysis', []):
        old_row = old_rows.get(row.get('id'))
        if not old_row or row.get('status') not in ('ok','partial') or not row.get('quote'):
            continue
        stable = lambda r: [(v.get('ts_code'),v.get('financials')) for v in r.get('leaders', [])]
        if (stable(row) != stable(old_row) or _research_action(row) != _research_action(old_row)
                or row.get('risk') != old_row.get('risk') or current_signatures != previous_signatures):
            continue
        def valid(value):
            when = parse_schedule_time(value.get('ai_generated_at'))
            return content_identity({**value,'id':row['id']}) and now and when and 0 <= (now-when).total_seconds() <= 86400
        if valid(old_row):
            row.update({k:copy.deepcopy(old_row[k]) for k in NARRATIVE_FIELDS if k in old_row})
            row.update(ai_live_retained=True, ai_reused=True)
            reused.append(row['id'])
        for effort, value in old_row.get('ai_variants', {}).items():
            if valid(value):
                row.setdefault('ai_variants', {})[effort] = {**copy.deepcopy(value), 'ai_live_retained':True, 'ai_reused':True}
        # A retained interpretation still links to its ORIGINAL dated evidence.
        # Do not relabel an old quote source with this refresh's timestamp.
        cited = set(row.get('evidence_ids', []))
        for value in row.get('ai_variants', {}).values():
            cited.update(value.get('evidence_ids', []))
        for identity in cited:
            if identity not in current_sources and identity in old_sources:
                report.setdefault('snapshot', {}).setdefault('sources', []).append(
                    {**copy.deepcopy(old_sources[identity]), 'retained_ai_evidence':True})
                current_sources.add(identity)
    report.setdefault('ai_research', {}).update(reused_count=len(reused), reused_sector_ids=reused,
        analyzed_count=len(reused), analyzed_sector_ids=reused, live_retained=True)
    return report
