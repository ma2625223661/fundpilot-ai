"""Convertible-bond index trend heuristic; no issuer/valuation data invented."""
import math
from research_numbers import finite_number as _finite

VERSION = 'convertible_trend_v1'
METHOD = ('可转债趋势模型 v1：以中证可转换债券指数的公开历史日线为依据，'
          '不是普通国债模型、股票龙头组合或基金净值。固定启发式，未经回测，非收益概率。'
          '基准50；日变动×2（±8）；5日收益×2（±10）；20日收益×1.2（±15）；'
          '60日收益×0.5（±10）；20日均线方向±5；年化波动超过15%每个百分点扣0.4（最多10）；'
          '窗口回撤绝对值×0.8（最多20）。至少61个近期历史点及三项数据条件均满足才评分。'
          '可转债含股性与信用风险，A股压力防御/谨慎/资料不足时上限分别49/64/49。'
          '未取得转股溢价、到期收益率、发行人评级、强赎及回售条款，不计入模型；'
          '该分数仅反映指数走势，不能判断转债便宜、信用安全或可买入。')


def score_convertible(metrics, daily_change, regime=None):
    required = ('return_5d', 'return_20d', 'return_60d', 'ma20_gap',
                'annual_volatility', 'max_drawdown')
    if metrics.get('sample_count', 0) < 61 or not _finite(daily_change) or any(
            not _finite(metrics.get(key)) for key in required):
        return None
    cap = lambda value, limit: max(-limit, min(limit, value))
    components = {'base': 50, 'daily_change': cap(daily_change * 2, 8),
                  'momentum_5d': cap(metrics['return_5d'] * 2, 10),
                  'momentum_20d': cap(metrics['return_20d'] * 1.2, 15),
                  'momentum_60d': cap(metrics['return_60d'] * .5, 10),
                  'trend_20d': 5 if metrics['ma20_gap'] > 0 else -5 if metrics['ma20_gap'] < 0 else 0,
                  'volatility_penalty': -min(10, max(0, metrics['annual_volatility'] - 15) * .4),
                  'drawdown_penalty': -min(20, abs(metrics['max_drawdown']) * .8)}
    components = {key: round(value, 3) for key, value in components.items()}
    raw = round(max(0, min(100, sum(components.values()))))
    ceiling = {'defensive': 49, 'cautious': 64, 'unknown': 49}.get((regime or {}).get('mode', 'unknown'), 100)
    return {'score': min(raw, ceiling), 'raw_score': raw, 'score_cap': ceiling,
            'components': components, 'method': METHOD}
