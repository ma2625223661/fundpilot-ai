"""Pure, dated A-share sample sentiment proxy; no HTTP or model calls.

This is a descriptive price-participation indicator, not an investor survey,
market-wide breadth count, valuation score or return probability.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from research_data import CHINA
from research_trading_calendar import a_share_quote_fresh, is_trading_day, last_closed_trading_day
from research_numbers import finite_number as _finite

VERSION = 'a_share_sample_sentiment_v1'
MIN_SAMPLES = 20
INDEX_CODES = frozenset(('sh000001', 'sz399001', 'sh000300', 'sz399006'))
WEIGHTS = {'breadth': .4, 'index_strength': .3, 'ma20_participation': .3}
STOCK_CODE = re.compile(r'^(?:(?:60[0135]|68[89])\d{3}\.SH|(?:00[0-3]|30[0-2])\d{3}\.SZ|[489]\d{5}\.BJ)$')
SCOPE = ('A股指数与本站已采集、去重公司样本的价格参与度代理；公司样本经过研究池筛选，'
         '不代表全市场涨跌家数、全部投资者情绪或收益概率。海外股票、指数、债券与资金利率不进入公司样本。')
METHOD = ('上涨广度40%＋四大A股指数强弱30%＋20日均线参与度30%。'
          '广度=100×(上涨家数＋0.5×平盘家数)/有效去重股票数；'
          '指数强弱=clip(50＋有效指数平均涨跌幅×10,0,100)；'
          'MA20参与度=100×(历史收盘高于MA20家数＋0.5×相等家数)/有效历史股票数。'
          '广度与MA分项各至少20只，指数至少2/4；至少两项且可计算分项权重覆盖≥70%才发布，'
          '缺项不填50分，仅按已具备计算条件的权重归一并标明部分数据。'
          'MA20只使用最近完整交易日及其连续20个交易日的前复权历史，不与盘中现价比较。'
          '低于20低迷、20～<40偏冷、40～<60平稳、60～<80活跃、80及以上过热；固定观察规则，未经收益回测。')


def _round(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)
    except (TypeError, ValueError):
        return None


def _ids(value):
    return sorted({v.strip() for v in value if isinstance(v, str) and v.strip()}) if isinstance(value, list) else []


def _sources(row, history=False):
    ids = _ids(row.get('source_ids'))
    if history:
        selected = [v for v in ids if 'history' in v]
    else:
        selected = [v for v in ids if 'quote' in v and not any(part in v for part in ('financial', 'history', 'members', 'business'))]
    return selected


def _same(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _recent_days(as_of):
    cutoff = last_closed_trading_day(as_of)
    if not cutoff:
        return [], None
    day = datetime.fromisoformat(cutoff).date()
    days = []
    for _ in range(100):
        opened = is_trading_day(day)
        if opened is None:
            return [], cutoff
        if opened:
            days.append(day.isoformat())
        if len(days) == 20:
            return list(reversed(days)), cutoff
        day -= timedelta(days=1)
    return [], cutoff


def _quote(row, as_of):
    q = row.get('quote')
    q = q if isinstance(q, dict) else {}
    when = row.get('as_of') or q.get('as_of') or q.get('trade_date')
    stamp = _stamp(when)
    change, close = q.get('pct_chg'), q.get('close')
    live = q.get('is_intraday') is True
    if (not stamp or not _sources(row) or not _finite(change) or not _finite(close) or close <= 0
            or not a_share_quote_fresh(when, as_of, daily=not live)):
        return None
    day = stamp.date().isoformat()
    if q.get('trade_date') and q['trade_date'] != day:
        return None
    return {'stamp': stamp, 'day': day, 'change': change, 'close': close,
            'live': live, 'source_ids': _sources(row)}


def _stock_quotes(pools, as_of):
    accepted, conflicts = {}, 0
    for code, rows in pools.items():
        valid = [q for row in rows if (q := _quote(row, as_of))]
        if not valid:
            continue
        latest = max(q['stamp'] for q in valid)
        chosen = [q for q in valid if q['stamp'] == latest]
        first = chosen[0]
        if any(not _same(q['change'], first['change']) or not _same(q['close'], first['close'])
               or q['live'] != first['live'] for q in chosen[1:]):
            conflicts += 1
            continue
        first['source_ids'] = sorted({v for q in chosen for v in q['source_ids']})
        accepted[code] = first
    # An older daily fallback must not become a member of today's live breadth.
    day = max((q['day'] for q in accepted.values()), default=None)
    return {code: q for code, q in accepted.items() if q['day'] == day}, day, conflicts


def _histories(pools, days):
    accepted, conflicts = {}, 0
    wanted = set(days)
    if len(wanted) != 20:
        return accepted, conflicts
    for code, rows in pools.items():
        samples, observed = [], {}
        bad = False
        for row in rows:
            if row.get('price_adjustment') != 'forward_adjusted' or not _sources(row, history=True):
                continue
            values = {}
            for point in row.get('history') or []:
                if not isinstance(point, dict) or point.get('date') not in wanted:
                    continue
                day, close = point['date'], point.get('close')
                if not _finite(close) or close <= 0:
                    continue
                if day in observed and not _same(observed[day], close):
                    bad = True
                observed[day] = close
                if day in values and not _same(values[day], close):
                    bad = True
                values[day] = close
            if set(values) == wanted:
                samples.append((values, _sources(row, history=True)))
        if bad or samples and any(any(not _same(v[day], samples[0][0][day]) for day in days) for v, _ in samples[1:]):
            conflicts += 1
            continue
        if not samples:
            continue
        values = samples[0][0]
        latest = values[days[-1]]
        mean = sum(values[day] / 20 for day in days)
        participation = .5 if _same(latest, mean) else 1 if latest > mean else 0
        accepted[code] = {'participation': participation,
                          'source_ids': sorted({v for _, ids in samples for v in ids})}
    return accepted, conflicts


def _indices(report, as_of):
    pools = defaultdict(list)
    snapshot = report.get('snapshot')
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    for row in snapshot.get('market') or []:
        if isinstance(row, dict) and row.get('code') in INDEX_CODES:
            pools[row['code']].append(row)
    accepted, conflicts = {}, 0
    for code, rows in pools.items():
        valid = []
        for row in rows:
            when = row.get('as_of')
            stamp = _stamp(when)
            change = row.get('change_pct')
            source = row.get('source_id')
            source = source.strip() if isinstance(source, str) else ''
            if (stamp and _finite(change) and source
                    and a_share_quote_fresh(when, as_of, daily=row.get('data_frequency') == 'daily')):
                valid.append({'stamp': stamp, 'day': stamp.date().isoformat(), 'change': change, 'source_id': source})
        if not valid:
            continue
        latest = max(q['stamp'] for q in valid)
        chosen = [q for q in valid if q['stamp'] == latest]
        if any(not _same(q['change'], chosen[0]['change']) for q in chosen[1:]):
            conflicts += 1
            continue
        accepted[code] = chosen[0]
    day = max((q['day'] for q in accepted.values()), default=None)
    return {code: q for code, q in accepted.items() if q['day'] == day}, conflicts


def build_market_sentiment(report):
    """Build dated observed components, never changing any research score."""
    report = report if isinstance(report, dict) else {}
    snapshot = report.get('snapshot')
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    as_of = report.get('as_of') or snapshot.get('as_of')
    as_of = as_of if isinstance(as_of, str) else ''
    evidence = report.get('company_evidence')
    evidence = evidence if isinstance(evidence, dict) else {}
    leaders = evidence.get('sector_leaders') or {}
    pools = defaultdict(list)
    if isinstance(leaders, dict):
        for rows in leaders.values():
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict) and isinstance(row.get('ts_code'), str) and STOCK_CODE.fullmatch(row['ts_code']):
                    pools[row['ts_code']].append(row)
    quotes, sample_date, quote_conflicts = _stock_quotes(pools, as_of)
    days, history_date = _recent_days(as_of)
    histories, history_conflicts = _histories(pools, days)
    indices, index_conflicts = _indices(report, as_of)
    candidate_count, sample_count, index_count = len(pools), len(quotes), len(indices)
    history_count = len(histories)
    breadth_ready, index_ready, ma_ready = sample_count >= MIN_SAMPLES, index_count >= 2, history_count >= MIN_SAMPLES
    index_mean = sum(q['change'] / index_count for q in indices.values()) if index_ready else None
    breadth = 100 * sum(1 if q['change'] > 0 else .5 if q['change'] == 0 else 0 for q in quotes.values()) / sample_count if breadth_ready else None
    ma = 100 * sum(q['participation'] for q in histories.values()) / history_count if ma_ready else None
    index_score = max(0, min(100, 50 + index_mean * 10)) if index_mean is not None else None
    quote_ids = sorted({v for q in quotes.values() for v in q['source_ids']})
    history_ids = sorted({v for q in histories.values() for v in q['source_ids']})
    index_ids = sorted({q['source_id'] for q in indices.values()})
    index_time = max((q['stamp'] for q in indices.values()), default=None)
    quote_time = max((q['stamp'] for q in quotes.values()), default=None)
    components = [
        {'id': 'breadth', 'label': '样本上涨广度', 'weight': .4, 'score': _round(breadth) if breadth is not None else None,
         'count': sample_count, 'status': 'unavailable' if not breadth_ready else 'ok' if sample_count == candidate_count else 'partial',
         'note': f'同一报价日去重A股{sample_count}/{candidate_count}只；上涨计1、平盘计0.5、下跌计0。至少{MIN_SAMPLES}只才计算。',
         'as_of': quote_time.isoformat() if quote_time else None, 'source_ids': quote_ids},
        {'id': 'index_strength', 'label': '四大指数强弱', 'weight': .3, 'score': _round(index_score) if index_score is not None else None,
         'count': index_count, 'status': 'unavailable' if not index_ready else 'ok' if index_count == 4 else 'partial',
         'coverage_pct': index_count * 25,
         'note': f'上证、深成指、沪深300、创业板白名单有效{index_count}/4；至少2个才计算；指数成分存在重叠。',
         'as_of': index_time.isoformat() if index_time else None, 'source_ids': index_ids},
        {'id': 'ma20_participation', 'label': '样本MA20参与度', 'weight': .3, 'score': _round(ma) if ma is not None else None,
         'count': history_count, 'status': 'unavailable' if not ma_ready else 'ok' if history_count == candidate_count else 'partial',
         'note': f'{history_count}/{candidate_count}只具备截至{history_date or "未知"}连续20个交易日前复权历史；历史收盘高于MA20计1、相等计0.5、低于计0；不混用现价。',
         'as_of': history_date, 'source_ids': history_ids},
    ]
    available = [c for c in components if c['score'] is not None]
    covered = sum(c['weight'] for c in available)
    score = _round(sum(c['score'] * c['weight'] for c in available) / covered) if len(available) >= 2 and covered >= .7 - 1e-9 else None
    status = 'unavailable' if score is None else 'ok' if all(c['status'] == 'ok' for c in components) else 'partial'
    label = ('数据不足' if score is None else '低迷' if score < 20 else '偏冷' if score < 40 else
             '平稳' if score < 60 else '活跃' if score < 80 else '过热')
    missing = []
    if sample_count < candidate_count:
        missing.append(f'{candidate_count - sample_count}只候选未通过同日有效报价核验（含{quote_conflicts}只同一时点报价冲突）；未计入广度。')
    if not breadth_ready:
        missing.append(f'广度仅{sample_count}只有效去重样本，未达到{MIN_SAMPLES}只。')
    if index_count < 4:
        missing.append(f'四大指数仅取得{index_count}/4个有效同日样本（冲突剔除{index_conflicts}个）。')
    if history_count < candidate_count:
        missing.append(f'{candidate_count - history_count}只候选的连续20日同口径历史不足或未核验（含{history_conflicts}只历史冲突）；未计入MA分项。')
    if not ma_ready:
        missing.append(f'MA20仅{history_count}只有效历史样本，未达到{MIN_SAMPLES}只。')
    if score is None:
        missing.append('至少两项且可计算分项权重覆盖≥70%才发布情绪分，缺项不填中性值。')
    source_ids = sorted({v for c in available for v in c['source_ids']})
    summary = ((f'情绪代理{score:.2f}/100，{label}。' if score is not None else '情绪代理数据不足，暂不发布分数。')
               + f'报价样本{sample_count}只去重A股，指数{index_count}/4，MA20历史样本{history_count}只；'
               + f'可计算分项权重覆盖{covered * 100:.0f}%（不是全市场证券覆盖率）。'
               + ('部分数据，已按可用分项权重归一。' if status == 'partial' else '')
               + '分数越高表示当前样本参与度越活跃，过热不等于更值得买入。')
    return {'version': VERSION, 'score': score, 'label': label, 'status': status,
            'coverage_pct': _round(covered * 100), 'as_of': as_of, 'sample_date': sample_date,
            'history_date': history_date, 'sample_count': sample_count, 'candidate_count': candidate_count,
            'index_count': index_count, 'components': components, 'source_ids': source_ids,
            'missing': missing, 'method': METHOD, 'scope': SCOPE, 'summary': summary}
