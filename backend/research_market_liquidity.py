"""Expose the dated money-market liquidity score as a separate market indicator.

The underlying score is the existing dedicated overnight-Shibor model. This
module only builds a public, clearly labelled view; it does not alter sector
research scores or infer equity liquidity from price changes.
"""
from __future__ import annotations

import math
from research_numbers import finite_number as _finite


VERSION = 'market_liquidity_v1'


def _score_label(score):
    if not _finite(score):
        return '数据待补充'
    if score < 30:
        return '偏紧'
    if score < 45:
        return '略紧'
    if score < 60:
        return '中性'
    if score < 75:
        return '偏宽'
    return '宽松'


def build_market_liquidity(report):
    """Return a dated liquidity index without mutating *report*.

    The money sector's recommendation index is the health-oriented score:
    higher means the observed overnight funding conditions are relatively
    easier or steadier. The separate risk score is retained for comparison
    with the environment-risk model, where higher means riskier.
    """
    source = report if isinstance(report, dict) else {}
    sectors = source.get('sector_analysis') or []
    money = next((row for row in sectors if isinstance(row, dict) and row.get('id') == 'money'), {})
    quote = money.get('quote') or {}
    metrics = money.get('metrics') or {}
    score = money.get('recommendation_index')
    if not (_finite(score) and 0 <= score <= 100 and money.get('score_scope') == 'money_liquidity'
            and money.get('status') == 'ok'):
        score = None
    risk_score = 100 - score if _finite(score) else None
    status = 'ok' if score is not None else 'unavailable'
    as_of = quote.get('as_of') or money.get('as_of') or metrics.get('end_date')
    source_ids = []
    for row in money.get('sources') or []:
        if isinstance(row, dict) and isinstance(row.get('id'), str) and row['id'].strip():
            source_ids.append(row['id'].strip())
    risk = (source.get('strategy') or {}).get('risk_overview') or {}
    for value in risk.get('source_ids') or []:
        if isinstance(value, str) and value.strip() in {'sector_reference:money', 'sector_history:money_rate:shibor:CNY:ON'}:
            source_ids.append(value.strip())
    source_ids = sorted(set(source_ids))
    missing = []
    if score is None:
        missing.append('人民币隔夜Shibor专用历史或当前时点未满足流动性模型条件。')
    if not source_ids:
        missing.append('尚无可核验的资金利率来源记录。')
    label = _score_label(score)
    summary = (f'市场流动性指数{score:.0f}/100，{label}；分数越高表示人民币隔夜资金利率相对平稳或趋宽。'
               if score is not None else '市场流动性指数暂不可用，等待有效的人民币隔夜Shibor及专用历史。')
    return {
        'version': VERSION,
        'score': round(float(score), 2) if score is not None else None,
        'risk_score': round(float(risk_score), 2) if risk_score is not None else None,
        'label': label,
        'status': status,
        'as_of': as_of,
        'sample_count': int(metrics.get('sample_count', 0)) if isinstance(metrics.get('sample_count'), int) else 0,
        'annual_rate_pct': metrics.get('annual_rate_pct') if _finite(metrics.get('annual_rate_pct')) else None,
        'rate_change_1d_bp': metrics.get('rate_change_1d_bp') if _finite(metrics.get('rate_change_1d_bp')) else None,
        'rate_change_5d_bp': metrics.get('rate_change_5d_bp') if _finite(metrics.get('rate_change_5d_bp')) else None,
        'rate_change_20d_bp': metrics.get('rate_change_20d_bp') if _finite(metrics.get('rate_change_20d_bp')) else None,
        'rate_change_60d_bp': metrics.get('rate_change_60d_bp') if _finite(metrics.get('rate_change_60d_bp')) else None,
        'rate_std_20d_bp': metrics.get('rate_std_20d_bp') if _finite(metrics.get('rate_std_20d_bp')) else None,
        'trend': str(money.get('trend') or ''),
        'source_ids': source_ids,
        'missing': missing,
        'scope': '人民币隔夜Shibor资金价格与变化代理；只观察货币市场流动性，不代表股票收益、存款安全或完整资金供给。',
        'method': str(money.get('score_method') or '沿用货币市场流动性观察模型v1；基于利率水平、5/20/60日变化及20日波动。'),
        'summary': summary,
    }
