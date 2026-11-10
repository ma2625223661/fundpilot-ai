"""Per-sector changes since the previous trading day, for watchlist alerts.

Each published report is compared with the last report of the most recent
earlier trading day (its "baseline"). Only values the backend already produced
are compared: research score, research tier, the critical-risk and strong-trend
markers and the market risk level. The page reads the result and never derives
it. Baselines are small per-sector records kept in ``sector-baselines.json``
next to the report file, one per China date, for the last few dates.

A change is a change in research evidence, not a return direction or advice.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

from research_data import CHINA

VERSION = 1
# Dates kept in the baseline file; also the reach of the score history.
KEEP_DAYS = 30
# A score move at least this large is worth an alert on its own.
NOTABLE_SCORE_DELTA = 3.0
MAX_FILE_BYTES = 2_000_000
FILE_NAME = 'sector-baselines.json'
NOTE = '变动对比的是上一交易日最后一份报告，只描述研究证据的变化，不代表收益方向，不构成投资建议。'


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _china_date(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CHINA)
    return moment.astimezone(CHINA).date().isoformat()


def snapshot(report):
    """The comparable fields of every sector in a report, or None without a usable time."""
    if not isinstance(report, dict):
        return None
    day = _china_date(report.get('as_of'))
    if not day:
        return None
    sectors = {}
    for sector in report.get('sector_analysis') or []:
        if not isinstance(sector, dict) or not isinstance(sector.get('id'), str):
            continue
        tier = sector.get('research_tier') if isinstance(sector.get('research_tier'), dict) else {}
        sectors[sector['id']] = {
            'title': str(sector.get('title') or sector['id'])[:60],
            'score': _number(sector.get('score')),
            'tier_id': tier.get('id') if isinstance(tier.get('id'), str) else None,
            'tier_label': tier.get('label') if isinstance(tier.get('label'), str) else None,
            'critical': sector.get('severity') == 'critical',
            'strong': sector.get('signal') == 'trend_excellent',
            'risk': sector.get('risk') if isinstance(sector.get('risk'), str) else None,
        }
    return {'version': VERSION, 'as_of': report.get('as_of'), 'date': day, 'sectors': sectors}


def remember(baselines, current):
    """Keep only the last snapshot of each date, for the newest KEEP_DAYS dates."""
    rows = [row for row in baselines if isinstance(row, dict) and isinstance(row.get('date'), str)
            and row['date'] != current['date']]
    rows.append(current)
    rows.sort(key=lambda row: row['date'])
    return rows[-KEEP_DAYS:]


def _trading_day(day):
    try:
        from research_trading_calendar import is_trading_day
        return bool(is_trading_day(date.fromisoformat(day)))
    except Exception:
        return True


def baseline_for(baselines, day):
    """The latest snapshot from an earlier trading day (any earlier day if none qualifies)."""
    earlier = [row for row in baselines if isinstance(row, dict) and isinstance(row.get('date'), str)
               and row['date'] < day and isinstance(row.get('sectors'), dict)]
    trading = [row for row in earlier if _trading_day(row['date'])]
    pool = trading or earlier
    return max(pool, key=lambda row: row['date']) if pool else None


def score_history(baselines, current):
    """Research score per sector on each earlier trading day plus the current report.

    One value per date (the last report of that day); a sector missing or without
    a score that day gets None, never a filled-in number.
    """
    if not current:
        return {'dates': [], 'scores': {}}
    rows = sorted((row for row in baselines if isinstance(row, dict) and isinstance(row.get('date'), str)
                   and row['date'] < current['date'] and isinstance(row.get('sectors'), dict)
                   and _trading_day(row['date'])), key=lambda row: row['date'])
    rows = rows[-(KEEP_DAYS - 1):] + [current]

    def score(row, sector_id):
        value = row['sectors'].get(sector_id)
        return _number(value.get('score')) if isinstance(value, dict) else None

    return {'dates': [row['date'] for row in rows],
            'scores': {sector_id: [score(row, sector_id) for row in rows] for sector_id in current['sectors']}}


def changes(report, baselines):
    """Per-sector differences against the baseline; values are copied, deltas computed here."""
    current = snapshot(report)
    empty = {'version': VERSION, 'baseline_as_of': None, 'baseline_date': None, 'items': {}, 'note': NOTE,
             'history': score_history(baselines, current)}
    if not current:
        return {**empty, 'status': 'unavailable', 'reason': '报告时间缺失，无法对比。'}
    base = baseline_for(baselines, current['date'])
    if not base:
        return {**empty, 'status': 'no_baseline', 'reason': '尚无上一交易日的报告，下一个交易日起显示变动。'}
    items = {}
    for sector_id, now in current['sectors'].items():
        before = base['sectors'].get(sector_id)
        if not isinstance(before, dict):
            continue
        item = {}
        old_score = _number(before.get('score'))
        if now['score'] is not None and old_score is not None:
            item.update(score_before=old_score, score_now=now['score'], score_delta=round(now['score'] - old_score, 2))
        if before.get('tier_id') and now['tier_id'] and before['tier_id'] != now['tier_id']:
            item['tier'] = {'before': before.get('tier_label') or before['tier_id'], 'now': now['tier_label'] or now['tier_id']}
        flags = []
        if now['critical'] and not before.get('critical'):
            flags.append('新增特大风险')
        if before.get('critical') and not now['critical']:
            flags.append('特大风险解除')
        if now['strong'] and not before.get('strong'):
            flags.append('新增趋势优')
        if before.get('strong') and not now['strong']:
            flags.append('趋势优消失')
        if flags:
            item['flags'] = flags
        if now['risk'] and before.get('risk') and now['risk'] != before['risk']:
            item['risk'] = {'before': before['risk'], 'now': now['risk']}
        if not item:
            continue
        delta = item.get('score_delta')
        item['notable'] = bool(flags or 'tier' in item or 'risk' in item
                               or (delta is not None and abs(delta) >= NOTABLE_SCORE_DELTA))
        items[sector_id] = item
    return {**empty, 'status': 'ok', 'baseline_as_of': base.get('as_of'), 'baseline_date': base['date'],
            'notable_score_delta': NOTABLE_SCORE_DELTA, 'items': items, 'reason': ''}


def baseline_path(state_path):
    return Path(state_path).with_name(FILE_NAME)


def load(path):
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return []
        rows = json.loads(path.read_text(encoding='utf-8'))
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def save(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(rows, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    temp.replace(path)


def apply_changes(report, state_path):
    """Attach report['sector_changes'] and record today's baseline. Never raises."""
    try:
        path = baseline_path(state_path) if state_path else None
        baselines = load(path) if path else []
        report['sector_changes'] = changes(report, baselines)
        current = snapshot(report)
        if path and current:
            save(path, remember(baselines, current))
    except Exception:
        report['sector_changes'] = {'version': VERSION, 'status': 'unavailable', 'baseline_as_of': None,
                                    'baseline_date': None, 'items': {}, 'note': NOTE,
                                    'reason': '变动记录暂时无法读取，下一轮自动重试。'}
    return report
