"""Factor return estimation, portfolio risk attribution and stress testing."""
from __future__ import annotations

import math

from .factors import forward_return
from .linalg import mean, ols, stdev
from .panel import Panel
from .preprocess import build_exposures


def cross_sectional_factor_returns(
    panel: Panel,
    prepared_by_t: dict[int, dict],
    keys: list[str],
    min_names: int = 20,
) -> dict:
    series: dict[str, list[dict]] = {key: [] for key in keys}
    series["market"] = []
    residuals: dict[str, dict[str, float]] = {}
    for t in sorted(prepared_by_t):
        scores = prepared_by_t[t].get("scores", {})
        available = [key for key in keys if key in scores]
        if len(available) < 3 or t + 1 >= len(panel.dates):
            continue
        symbols = []
        for symbol in set.intersection(*(set(scores[key]) for key in available)):
            if forward_return(panel, symbol, t) is not None:
                symbols.append(symbol)
        if len(symbols) < min_names:
            continue
        y = [forward_return(panel, symbol, t) or 0.0 for symbol in symbols]
        betas = prepared_by_t[t].get("diagnostics", {}).get("exposures", {}).get("betas", {})
        rows = [
            [1.0, betas.get(symbol, 1.0)] + [scores[key][symbol] for key in available]
            for symbol in symbols
        ]
        fit = ols(rows, y)
        series["market"].append({"date": panel.dates[t], "return": fit["beta"][1]})
        for index, key in enumerate(available):
            series[key].append({"date": panel.dates[t], "return": fit["beta"][index + 2]})
        residuals[panel.dates[t]] = dict(zip(symbols, fit["residuals"]))
    return {"series": series, "residuals": residuals}


def factor_stats(series: list[dict]) -> dict:
    values = [item["return"] for item in series]
    if len(values) < 20:
        return {"n": len(values), "annual_return": 0.0, "annual_vol": 0.0, "sharpe": 0.0, "tstat": 0.0}
    mu = mean(values)
    sd = stdev(values)
    return {
        "n": len(values),
        "annual_return": mu * 252.0,
        "annual_vol": sd * math.sqrt(252.0),
        "sharpe": mu / sd * math.sqrt(252.0) if sd > 1e-15 else 0.0,
        "tstat": mu / sd * math.sqrt(len(values)) if sd > 1e-15 else 0.0,
    }


def _aligned(series: dict[str, list[dict]], keys: list[str]) -> tuple[list[str], list[list[float]]]:
    maps = {key: {item["date"]: item["return"] for item in series[key]} for key in keys}
    common = set(maps[keys[0]])
    for key in keys[1:]:
        common &= set(maps[key])
    dates = sorted(common)
    rows = [[maps[key][day] for key in keys] for day in dates]
    return dates, rows


def factor_covariance(series: dict[str, list[dict]], keys: list[str], shrink: float = 0.1) -> dict:
    dates, rows = _aligned(series, keys)
    k = len(keys)
    if len(rows) < 30:
        return {"keys": keys, "matrix": [[0.0] * k for _ in range(k)], "days": len(rows)}
    columns = [[row[j] for row in rows] for j in range(k)]
    cov = [[0.0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            value = sum(
                (columns[i][r] - mean(columns[i])) * (columns[j][r] - mean(columns[j]))
                for r in range(len(rows))
            ) / (len(rows) - 1) * 252.0
            cov[i][j] = cov[j][i] = value
    out = [
        [(1.0 - shrink) * cov[i][j] + (shrink * cov[i][i] if i == j else 0.0) for j in range(k)]
        for i in range(k)
    ]
    return {"keys": keys, "matrix": out, "days": len(rows), "start": dates[0], "end": dates[-1]}


def portfolio_exposures(weights: dict[str, float], cross: dict, keys: list[str]) -> dict:
    scores = cross.get("scores", {})
    out = {}
    for key in keys:
        values = scores.get(key, {})
        out[key] = sum(weight * values.get(symbol, 0.0) for symbol, weight in weights.items())
    return out


def specific_variance(
    panel: Panel,
    weights: dict[str, float],
    factor_result: dict,
    latest_date: str,
    window: int = 120,
) -> dict:
    residuals = factor_result.get("residuals", {})
    dates = [day for day in sorted(residuals) if day <= latest_date][-window:]
    out = {}
    for symbol, weight in weights.items():
        values = [residuals[day][symbol] for day in dates if symbol in residuals.get(day, {})]
        if len(values) >= 20:
            vol = stdev(values) * math.sqrt(252.0)
        else:
            sample = [value for value in panel.returns(symbol)[-window:] if value is not None]
            vol = stdev(sample) * math.sqrt(252.0) if len(sample) > 5 else 0.20
        out[symbol] = vol
    variance = sum((weight * out.get(symbol, 0.20)) ** 2 for symbol, weight in weights.items())
    return {"variance": variance, "vol": math.sqrt(variance), "by_symbol": out}


def risk_decomposition(
    weights: dict[str, float],
    exposures: dict[str, float],
    covariance: dict,
) -> dict:
    keys = covariance.get("keys", [])
    matrix = covariance.get("matrix", [])
    b = [exposures.get(key, 0.0) for key in keys]
    sigma_b = [sum(matrix[i][j] * b[j] for j in range(len(keys))) for i in range(len(keys))]
    contributions = {key: b[i] * sigma_b[i] for i, key in enumerate(keys)}
    factor_var = sum(contributions.values())
    return {
        "exposures": exposures,
        "factor_variance": factor_var,
        "factor_vol": math.sqrt(max(factor_var, 0.0)),
        "contributions": contributions,
    }


def _scenario(name: str, market: float, factors: dict[str, float], description: str) -> dict:
    return {"name": name, "market": market, "factors": factors, "description": description}


BASE_SCENARIOS = (
    _scenario(
        "动量崩塌",
        -0.06,
        {"momentum": -0.10, "low_vol": 0.03, "size": -0.04, "illiquidity": -0.03, "value": 0.01, "quality": 0.01},
        "高动量股票集中回撤，低波动与质量相对占优。",
    ),
    _scenario(
        "流动性冲击",
        -0.08,
        {"illiquidity": -0.08, "size": -0.06, "low_vol": 0.02, "quality": 0.01, "momentum": -0.02},
        "小市值与低流动性资产被强制卖出。",
    ),
    _scenario(
        "利率快速上行",
        -0.05,
        {"value": 0.04, "quality": -0.02, "low_vol": -0.03, "size": 0.01},
        "长久期成长股承压，价值风格相对受益。",
    ),
    _scenario(
        "风险偏好反转",
        0.04,
        {"momentum": 0.05, "size": 0.03, "low_vol": -0.02, "quality": -0.01},
        "高风险资产领涨，防御因子落后。",
    ),
)


def historical_stress(
    series: dict[str, list[dict]],
    keys: list[str],
    window: int = 20,
) -> dict:
    dates, rows = _aligned(series, ["market"] if "market" in series else keys)
    if not dates:
        aligned_dates, aligned = _aligned(series, keys)
        if not aligned_dates:
            return {"name": "样本内压力窗口", "market": 0.0, "factors": {}, "start": None, "end": None}
        dates = aligned_dates
        market_index = None
    else:
        aligned_dates, aligned = _aligned(series, keys)
    if not aligned:
        return {"name": "样本内压力窗口", "market": 0.0, "factors": {}, "start": None, "end": None}
    if "market" in series:
        market_map = {item["date"]: item["return"] for item in series["market"]}
        market_values = [market_map.get(day, 0.0) for day in aligned_dates]
    else:
        market_values = [sum(row) / len(row) for row in aligned]
    best = None
    for index in range(0, max(1, len(aligned_dates) - window + 1)):
        segment = market_values[index:index + window]
        if len(segment) < window:
            continue
        total = 1.0
        for value in segment:
            total *= 1.0 + value
        cumulative = total - 1.0
        if best is None or cumulative < best[0]:
            best = (cumulative, index)
    if best is None:
        return {"name": "样本内压力窗口", "market": 0.0, "factors": {}, "start": None, "end": None}
    index = best[1]
    factors = {}
    for j, key in enumerate(keys):
        total = 1.0
        for row in aligned[index:index + window]:
            total *= 1.0 + row[j]
        factors[key] = total - 1.0
    return {
        "name": "样本内最差 20 日",
        "market": best[0],
        "factors": factors,
        "start": aligned_dates[index],
        "end": aligned_dates[min(index + window - 1, len(aligned_dates) - 1)],
        "description": "按样本内最差 20 日市场窗口同步重放各因子实际收益。",
    }


def stress_test(
    weights: dict[str, float],
    exposures: dict[str, float],
    beta: float,
    scenarios: list[dict],
) -> list[dict]:
    out = []
    for scenario in scenarios:
        pnl = beta * scenario.get("market", 0.0)
        for key, value in scenario.get("factors", {}).items():
            pnl += exposures.get(key, 0.0) * value
        out.append(
            {
                "name": scenario["name"],
                "description": scenario.get("description", ""),
                "market": scenario.get("market", 0.0),
                "pnl": pnl,
                "start": scenario.get("start"),
                "end": scenario.get("end"),
            }
        )
    return out


def historical_tail(points: list[tuple[str, float]]) -> dict:
    values = sorted(value for _, value in points)
    if not values:
        return {"var95": 0.0, "var99": 0.0, "cvar95": 0.0, "cvar99": 0.0, "worst": 0.0}
    def quantile(q: float) -> float:
        index = max(0, min(len(values) - 1, int(q * (len(values) - 1))))
        return values[index]
    var95 = quantile(0.05)
    var99 = quantile(0.01)
    tail95 = [value for value in values if value <= var95]
    tail99 = [value for value in values if value <= var99]
    return {
        "var95": var95,
        "var99": var99,
        "cvar95": mean(tail95) if tail95 else var95,
        "cvar99": mean(tail99) if tail99 else var99,
        "worst": values[0],
    }


def portfolio_beta(panel: Panel, weights: dict[str, float], t: int) -> float:
    if not weights:
        return 0.0
    symbols = list(weights)
    exposures = build_exposures(panel, t, symbols)
    return sum(weights[symbol] * exposures["betas"].get(symbol, 1.0) for symbol in symbols)


def build_risk_model(
    panel: Panel,
    prepared_by_t: dict[int, dict],
    keys: list[str],
    weights: dict[str, float],
    factor_result: dict | None = None,
) -> dict:
    factor_result = factor_result or cross_sectional_factor_returns(panel, prepared_by_t, keys)
    series = dict(factor_result["series"])
    if not series.get("market"):
        market_series = []
        for t in sorted(prepared_by_t):
            value = panel.market_return(t)
            if value is not None:
                market_series.append({"date": panel.dates[t], "return": value})
        series["market"] = market_series
    available = [key for key in keys if len(series.get(key, [])) >= 30]
    if not available:
        return {"ok": False}
    covariance = factor_covariance(series, available)
    latest_t = max(prepared_by_t)
    cross = prepared_by_t[latest_t]
    exposures = portfolio_exposures(weights, cross, available)
    decomposition = risk_decomposition(weights, exposures, covariance)
    specific = specific_variance(panel, weights, factor_result, panel.dates[latest_t])
    total_variance = max(decomposition["factor_variance"], 0.0) + specific["variance"]
    total_vol = math.sqrt(total_variance)
    beta = portfolio_beta(panel, weights, latest_t)
    scenarios = list(BASE_SCENARIOS)
    replay = historical_stress(series, available)
    if replay.get("start"):
        scenarios.append(replay)
    stress = stress_test(weights, exposures, beta, scenarios)
    table = []
    for key in available:
        contribution = decomposition["contributions"].get(key, 0.0)
        table.append(
            {
                "factor": key,
                "exposure": exposures.get(key, 0.0),
                "annual_return": factor_stats(series[key])["annual_return"],
                "annual_vol": factor_stats(series[key])["annual_vol"],
                "sharpe": factor_stats(series[key])["sharpe"],
                "tstat": factor_stats(series[key])["tstat"],
                "risk_contribution": contribution,
                "risk_share": contribution / total_variance if total_variance > 1e-15 else 0.0,
            }
        )
    return {
        "ok": True,
        "beta": beta,
        "factors": table,
        "covariance": covariance,
        "specific_vol": specific["vol"],
        "total_vol": total_vol,
        "factor_vol": decomposition["factor_vol"],
        "stress": stress,
        "replay": replay,
        "factor_returns_available": {key: len(series[key]) for key in available},
    }

