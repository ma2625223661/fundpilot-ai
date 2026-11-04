"""Typed public money-market reference, independent of fund and equity data.

Shibor O/N is an annualized interbank offered rate. Its daily change is in
basis points, never an equity return or the yield of an investable product.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta
from urllib.parse import urlencode

from research_data import CHINA, fetch_text, now_iso

MONEY_HISTORY_ID = 'money_rate:shibor:CNY:ON'
MONEY_OFFICIAL_URL = 'https://www.shibor.org/'
MONEY_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get?' + urlencode({
    'reportName': 'RPT_IMP_INTRESTRATEN', 'columns': 'ALL',
    'pageSize': 121, 'pageNumber': 1, 'sortColumns': 'REPORT_DATE', 'sortTypes': -1,
    'filter': '(MARKET_CODE="001")(CURRENCY_CODE="CNY")(INDICATOR_ID="001")',
})
MONEY_METHOD = (
    '货币市场流动性观察模型v1，使用人民币隔夜Shibor年化利率及基点变化，'
    '不是股票回报、货币基金收益率或综合公司研究分，未经交易回测。'
    '至少61个近期有效发布日历史点，5/20/60日均指有效发布日；基准50分；5日利率下降每基点加1分（±8）；'
    '20日下降每基点加0.5分（±15）；60日下降每基点加0.2分（±10）；'
    '20日利率标准差每2基点扣1分（最多12）；当日上升超过5基点的部分每基点扣1分（最多15）。'
    '高分只表示当前利率相对平稳或资金趋宽，不代表存款安全或投资收益。')
MONEY_SCOPE = ('人民币隔夜Shibor资金价格观察；以年化利率%和基点变化展示，'
               '只研究货币市场流动性，不恢复基金或净值数据，不需要公司财务。')


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _stamp(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp.astimezone(CHINA)


def _cutoff(as_of):
    stamp = _stamp(as_of)
    # Keep the same completed-day policy as the daily reference collectors.
    return stamp.date() if stamp.hour >= 15 else stamp.date() - timedelta(days=1)


def _validated_history(history, as_of):
    cutoff, rows = _cutoff(as_of), {}
    for item in history if isinstance(history, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            day = datetime.strptime(str(item.get('date')), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        rate = _number(item.get('annual_rate_pct'))
        if day > cutoff or rate is None or rate < 0:
            continue
        rows[day.isoformat()] = {'date': day.isoformat(), 'annual_rate_pct': rate}
    return [rows[k] for k in sorted(rows)][-121:]


def parse_money_history(data, as_of):
    if (not isinstance(data, dict) or data.get('success') is not True or str(data.get('code')) != '0'
            or not isinstance(data.get('result'), dict)
            or not isinstance(data['result'].get('data'), list)):
        raise ValueError('Shibor公开数据源未返回有效利率列表')
    raw = []
    for item in data['result']['data']:
        if not isinstance(item, dict):
            continue
        if (str(item.get('MARKET_CODE')) != '001'
                or item.get('CURRENCY_CODE') != 'CNY'
                or str(item.get('INDICATOR_ID')) != '001'
                or item.get('REPORT_PERIOD') != '隔夜(O/N)'):
            raise ValueError('利率币种、市场或期限与人民币隔夜Shibor不一致')
        raw.append({'date': str(item.get('REPORT_DATE', ''))[:10],
                    'annual_rate_pct': item.get('IR_RATE')})
    history = _validated_history(raw, as_of)
    if not history:
        raise ValueError('Shibor公开数据源没有有效已完成日期利率')
    return history


def collect_money_reference(as_of):
    """Return (quotes, sources, histories); rate histories have no price field."""
    _stamp(as_of)
    source = {'id': 'sector_reference:money', 'board_id': 'money',
              'name': '东方财富公开利率 · 人民币隔夜Shibor', 'url': MONEY_URL,
              'official_url': MONEY_OFFICIAL_URL, 'fetched_at': now_iso(),
              'as_of': None, 'as_of_precision': 'date', 'status': 'error', 'count': 0,
              'asset_type': 'money_rate', 'return_type': 'annualized_interest_rate',
              'scope': MONEY_SCOPE}
    try:
        history = parse_money_history(json.loads(fetch_text(MONEY_URL)), as_of)
        last, previous = history[-1], history[-2] if len(history) > 1 else None
        change_bp = round((last['annual_rate_pct'] - previous['annual_rate_pct']) * 100, 6) if previous else None
        quote = {
            'board_id': 'money', 'sector_id': 'money', 'code': 'SHIBOR_CNY_ON',
            'name': '人民币隔夜Shibor', 'full_name': '上海银行间同业拆放利率（人民币隔夜）',
            'last': last['annual_rate_pct'], 'annual_rate_pct': last['annual_rate_pct'],
            'change_pct': None, 'change_bp': change_bp, 'change_unit': 'basis_points',
            'value_unit': 'annual_rate_pct', 'as_of': last['date'],
            'as_of_precision': 'date', 'data_frequency': 'daily',
            'source_id': source['id'], 'source_url': MONEY_URL,
            'history_secid': MONEY_HISTORY_ID, 'up_count': None, 'down_count': None,
            'asset_type': 'money_rate', 'return_type': 'annualized_interest_rate',
            'score_scope': 'money_liquidity', 'scope_note': MONEY_SCOPE,
            'official_url': MONEY_OFFICIAL_URL, 'methodology_url': None,
            'mapping_basis': '人民币隔夜Shibor明确利率序列。' + MONEY_SCOPE,
        }
        source.update(status='ok', count=len(history), as_of=last['date'])
        if len(history) < 61:
            source.update(status='partial', error='利率历史少于61个有效点，仅显示利率，不生成流动性分')
        return [quote], [source, dict(source, id='sector_history:' + MONEY_HISTORY_ID,
                                      name=source['name'] + ' · 利率历史')], {MONEY_HISTORY_ID: history}
    except Exception as exc:
        source['error'] = str(exc)[:180] if isinstance(exc, ValueError) else '公开利率源连接失败或响应格式变化'
        return [], [source], {}


def score_money_rate(history, as_of):
    """Score liquidity conditions, not investment quality or price momentum."""
    rows = _validated_history(history, as_of)
    if len(rows) < 61 or (_cutoff(as_of) - datetime.strptime(rows[-1]['date'], '%Y-%m-%d').date()).days > 14:
        return None
    if (datetime.strptime(rows[-1]['date'], '%Y-%m-%d') - datetime.strptime(rows[-61]['date'], '%Y-%m-%d')).days > 150:
        return None
    values = [r['annual_rate_pct'] for r in rows]
    delta = lambda days: (values[-1] - values[-1-days]) * 100
    std = statistics.pstdev(values[-20:]) * 100
    latest_change = delta(1)
    cap = lambda n, maximum: max(-maximum, min(maximum, n))
    components = {'base': 50, 'easing_5d': cap(-delta(5), 8),
                  'easing_20d': cap(-delta(20) * .5, 15),
                  'easing_60d': cap(-delta(60) * .2, 10),
                  'rate_volatility_penalty': -min(12, std / 2),
                  'daily_tightening_penalty': -min(15, max(0, latest_change - 5))}
    metrics = {'sample_count': len(rows), 'start_date': rows[0]['date'],
               'end_date': rows[-1]['date'], 'annual_rate_pct': values[-1],
               'rate_change_1d_bp': round(latest_change, 6),
               'rate_change_5d_bp': round(delta(5), 6),
               'rate_change_20d_bp': round(delta(20), 6),
               'rate_change_60d_bp': round(delta(60), 6),
               'rate_std_20d_bp': round(std, 6),
               'value_unit': 'annual_rate_pct', 'change_unit': 'basis_points'}
    score = round(max(0, min(100, sum(components.values()))))
    return {'score': score, 'components': {k: round(v, 3) for k,v in components.items()},
            'metrics': metrics, 'method': MONEY_METHOD, 'score_scope': 'money_liquidity',
            'trend': '资金趋宽' if delta(20) < -5 else '资金偏紧' if delta(20) > 5 else '利率平稳',
            'risk': '利率波动升高' if std >= 10 or latest_change >= 10 else '待结合信用与政策风险'}
