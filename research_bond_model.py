"""Transparent bond trend heuristic, independent of equity panic caps.

Percentage inputs use percentage points. This is neither a forecast of yield
nor a probability of profit. No duration, rating or credit spreads are guessed.
"""
import math

METHOD = ('债券趋势模型 v1，固定启发式规则，未经交易回测，非收益概率或到期收益率。'
          '基准50分；5日收益×8（±10）；20日收益×6（±15）；60日收益×3（±10）；'
          '20日均线方向±5；60日年化波动超过2%每个百分点扣2分（最多10）；'
          '窗口最大回撤绝对值×4（最多20）。至少61个近期历史点才评分；不套用A股恐慌分数上限。')


def score_bond(metrics):
    required = ('return_5d', 'return_20d', 'return_60d', 'ma20_gap',
                'annual_volatility', 'max_drawdown')
    if metrics.get('sample_count', 0) < 61 or any(
        isinstance(metrics.get(k), bool) or not isinstance(metrics.get(k), (float, int))
        or not math.isfinite(metrics[k]) for k in required):
        return None
    cap = lambda value, limit: max(-limit, min(limit, value))
    components = {'base': 50, 'momentum_5d': cap(metrics['return_5d'] * 8, 10),
                  'momentum_20d': cap(metrics['return_20d'] * 6, 15),
                  'momentum_60d': cap(metrics['return_60d'] * 3, 10),
                  'trend_20d': 5 if metrics['ma20_gap'] > 0 else -5 if metrics['ma20_gap'] < 0 else 0,
                  'volatility_penalty': -min(10, max(0, metrics['annual_volatility'] - 2) * 2),
                  'drawdown_penalty': -min(20, abs(metrics['max_drawdown']) * 4)}
    components = {k: round(v, 3) for k, v in components.items()}
    return {'score': round(max(0, min(100, sum(components.values())))),
            'components': components, 'method': METHOD}
