"""Cross-sectional factor library.

Every score is oriented so that a higher value is expected to earn a higher
forward return. Scores use closes up to and including day t, and fundamental
reports published strictly before day t.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .linalg import stdev, zscore
from .panel import Panel


@dataclass(frozen=True)
class FactorSpec:
    key: str
    label: str
    category: str
    description: str
    min_history: int


FACTOR_SPECS = (
    FactorSpec(
        "momentum",
        "动量",
        "trend",
        "过去 12 个月剔除最近 1 个月的累计收益；高动量预期延续。",
        252,
    ),
    FactorSpec(
        "reversal",
        "短期反转",
        "trend",
        "过去 5 日收益取负；短期超跌后修复。",
        6,
    ),
    FactorSpec(
        "low_vol",
        "低波动",
        "risk",
        "过去 60 日年化波动率取负；低波动股票在风险厌恶阶段通常更抗跌。",
        60,
    ),
    FactorSpec(
        "illiquidity",
        "非流动性",
        "liquidity",
        "过去 60 日 Amihud 非流动性取对数；流动性溢价假设。",
        60,
    ),
    FactorSpec(
        "size",
        "小市值",
        "size",
        "对数总市值取负；市值越小得分越高。",
        1,
    ),
    FactorSpec(
        "value",
        "价值",
        "fundamental",
        "盈利收益率与账面市值比的截面标准化均值；只用已披露财报。",
        1,
    ),
    FactorSpec(
        "quality",
        "质量",
        "fundamental",
        "ROE 减去应计项目的一半；盈利质量越高得分越高。",
        1,
    ),
)

BY_KEY = {spec.key: spec for spec in FACTOR_SPECS}
ALL_KEYS = tuple(spec.key for spec in FACTOR_SPECS)


def _valid(values: list[float | None]) -> list[float]:
    return [value for value in values if value is not None]


def momentum_score(panel: Panel, t: int) -> dict[str, float]:
    out = {}
    if t < 252:
        return out
    for symbol in panel.symbols:
        closes = panel.close[symbol]
        start = closes[t - 252]
        end = closes[t - 21]
        if start and end and start > 0:
            out[symbol] = end / start - 1.0
    return out


def reversal_score(panel: Panel, t: int) -> dict[str, float]:
    out = {}
    if t < 5:
        return out
    for symbol in panel.symbols:
        closes = panel.close[symbol]
        start = closes[t - 5]
        end = closes[t]
        if start and end and start > 0:
            out[symbol] = -(end / start - 1.0)
    return out


def low_vol_score(panel: Panel, t: int) -> dict[str, float]:
    out = {}
    if t < 60:
        return out
    for symbol in panel.symbols:
        values = _valid(panel.returns(symbol)[t - 59:t + 1])
        if len(values) >= 45:
            out[symbol] = -stdev(values) * math.sqrt(252.0)
    return out


def illiquidity_score(panel: Panel, t: int) -> dict[str, float]:
    out = {}
    if t < 60:
        return out
    for symbol in panel.symbols:
        values = []
        for i in range(t - 59, t + 1):
            ret = panel.return_at(symbol, i)
            dollar = panel.dollar_volume(symbol, i)
            if ret is not None and dollar and dollar > 0:
                values.append(abs(ret) / dollar)
        if len(values) >= 40:
            amihud = sum(values) / len(values)
            out[symbol] = math.log1p(amihud * 1e9)
    return out


def size_score(panel: Panel, t: int) -> dict[str, float]:
    out = {}
    for symbol in panel.symbols:
        cap = panel.market_cap[symbol][t]
        if cap and cap > 0:
            out[symbol] = -math.log(cap)
    return out


def value_score(panel: Panel, t: int) -> dict[str, float]:
    earnings_yield = {}
    book_to_price = {}
    for symbol in panel.symbols:
        record = panel.fundamental_asof(symbol, t)
        if record is None:
            continue
        if record.earnings_yield is not None:
            earnings_yield[symbol] = record.earnings_yield
        if record.book_to_price is not None:
            book_to_price[symbol] = record.book_to_price
    ep_z = dict(zip(earnings_yield, zscore(list(earnings_yield.values())))) if len(earnings_yield) >= 5 else {}
    bp_z = dict(zip(book_to_price, zscore(list(book_to_price.values())))) if len(book_to_price) >= 5 else {}
    out = {}
    for symbol in set(ep_z) | set(bp_z):
        parts = [value for value in (ep_z.get(symbol), bp_z.get(symbol)) if value is not None]
        if parts:
            out[symbol] = sum(parts) / len(parts)
    return out


def quality_score(panel: Panel, t: int) -> dict[str, float]:
    out = {}
    for symbol in panel.symbols:
        record = panel.fundamental_asof(symbol, t)
        if record is None or record.roe is None:
            continue
        value = record.roe
        if record.accruals is not None:
            value -= 0.5 * record.accruals
        out[symbol] = value
    return out


COMPUTERS = {
    "momentum": momentum_score,
    "reversal": reversal_score,
    "low_vol": low_vol_score,
    "illiquidity": illiquidity_score,
    "size": size_score,
    "value": value_score,
    "quality": quality_score,
}


def factor_scores(panel: Panel, t: int, key: str) -> dict[str, float]:
    if key not in COMPUTERS:
        raise KeyError(f"unknown factor {key}")
    return COMPUTERS[key](panel, t)


def all_factor_scores(panel: Panel, t: int) -> dict[str, dict[str, float]]:
    return {key: COMPUTERS[key](panel, t) for key in ALL_KEYS}


def forward_return(panel: Panel, symbol: str, t: int, horizon: int = 1) -> float | None:
    if t < 0 or t + horizon >= len(panel.dates):
        return None
    start = panel.close[symbol][t]
    end = panel.close[symbol][t + horizon]
    if start and end and start > 0:
        return end / start - 1.0
    return None


def spec_table() -> list[dict]:
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "category": spec.category,
            "description": spec.description,
            "min_history": spec.min_history,
        }
        for spec in FACTOR_SPECS
    ]

