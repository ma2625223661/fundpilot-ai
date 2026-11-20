"""IC, decay, quantile spreads and performance statistics."""
from __future__ import annotations

import math

from .factors import forward_return
from .linalg import max_drawdown, mean, pearson, spearman, stdev
from .panel import Panel

TRADING_DAYS = 252.0


def ic_series(
    panel: Panel,
    prepared_by_t: dict[int, dict],
    key: str,
    horizon: int = 1,
    min_names: int = 15,
) -> list[dict]:
    out = []
    for t in sorted(prepared_by_t):
        scores = prepared_by_t[t].get("scores", {}).get(key, {})
        if len(scores) < min_names or t + horizon >= len(panel.dates):
            continue
        symbols = []
        factors = []
        forwards = []
        for symbol, value in scores.items():
            future = forward_return(panel, symbol, t, horizon)
            if future is None:
                continue
            symbols.append(symbol)
            factors.append(value)
            forwards.append(future)
        if len(symbols) < min_names:
            continue
        out.append(
            {
                "date": panel.dates[t],
                "ic": spearman(factors, forwards),
                "pearson": pearson(factors, forwards),
                "n": len(symbols),
            }
        )
    return out


def ic_stats(values: list[dict]) -> dict:
    series = [item["ic"] for item in values]
    if not series:
        return {
            "n": 0,
            "mean": 0.0,
            "std": 0.0,
            "icir": 0.0,
            "icir_annual": 0.0,
            "tstat": 0.0,
            "hit_rate": 0.0,
        }
    mu = mean(series)
    sd = stdev(series)
    icir = mu / sd if sd > 1e-15 else 0.0
    return {
        "n": len(series),
        "mean": mu,
        "std": sd,
        "icir": icir,
        "icir_annual": icir * math.sqrt(TRADING_DAYS),
        "tstat": icir * math.sqrt(len(series)) if sd > 1e-15 else 0.0,
        "hit_rate": sum(1 for value in series if value > 0) / len(series),
    }


def decay_curve(
    panel: Panel,
    prepared_by_t: dict[int, dict],
    key: str,
    horizons: tuple[int, ...] = (1, 2, 3, 5, 10, 20, 60),
    min_names: int = 15,
) -> list[dict]:
    out = []
    for horizon in horizons:
        stats = ic_stats(ic_series(panel, prepared_by_t, key, horizon=horizon, min_names=min_names))
        out.append({"horizon": horizon, "ic": stats["mean"], "tstat": stats["tstat"], "n": stats["n"]})
    return out


def half_life(decay: list[dict]) -> float | None:
    if not decay or not decay[0]["ic"] or decay[0]["ic"] <= 0:
        return None
    base = decay[0]["ic"]
    for point in decay[1:]:
        if point["ic"] <= 0.5 * base:
            return float(point["horizon"])
    return None


def average_correlation(prepared_by_t: dict[int, dict], keys: list[str]) -> dict:
    matrices = []
    for t in sorted(prepared_by_t):
        scores = prepared_by_t[t].get("scores", {})
        available = [key for key in keys if key in scores]
        if len(available) < 2:
            continue
        common = set(scores[available[0]])
        for key in available[1:]:
            common &= set(scores[key])
        symbols = sorted(common)
        if len(symbols) < 15:
            continue
        columns = [[scores[key][symbol] for symbol in symbols] for key in available]
        corr = [[pearson(columns[i], columns[j]) for j in range(len(available))] for i in range(len(available))]
        matrices.append((available, corr))
    if not matrices:
        return {"keys": keys, "matrix": [], "max_offdiag": 0.0}
    totals = [[0.0] * len(keys) for _ in keys]
    counts = [[0] * len(keys) for _ in keys]
    for available, corr in matrices:
        for i, key_i in enumerate(available):
            for j, key_j in enumerate(available):
                a, b = keys.index(key_i), keys.index(key_j)
                totals[a][b] += corr[i][j]
                counts[a][b] += 1
    matrix = [
        [totals[i][j] / counts[i][j] if counts[i][j] else (1.0 if i == j else 0.0) for j in range(len(keys))]
        for i in range(len(keys))
    ]
    offdiag = max((abs(matrix[i][j]) for i in range(len(keys)) for j in range(i + 1, len(keys))), default=0.0)
    return {"keys": keys, "matrix": matrix, "max_offdiag": offdiag, "days": len(matrices)}


def quantile_series(
    panel: Panel,
    prepared_by_t: dict[int, dict],
    key: str,
    groups: int = 5,
    rebalance: int = 21,
    min_names: int = 25,
) -> dict:
    scores_by_t = {
        t: prepared_by_t[t].get("scores", {}).get(key, {})
        for t in prepared_by_t
    }
    return quantile_from_scores(panel, scores_by_t, groups=groups, rebalance=rebalance, min_names=min_names)


def quantile_from_scores(
    panel: Panel,
    scores_by_t: dict[int, dict[str, float]],
    groups: int = 5,
    rebalance: int = 21,
    min_names: int = 25,
) -> dict:
    dates = panel.dates
    indices = sorted(t for t in scores_by_t if t + 1 < len(dates))
    if not indices:
        return {"groups": groups, "series": {}, "summary": {}}
    rebalance_points = indices[::rebalance]
    series: dict[str, list[tuple[str, float]]] = {f"Q{index + 1}": [] for index in range(groups)}
    spread_key = f"Q{groups}-Q1"
    series[spread_key] = []
    for position, t in enumerate(rebalance_points):
        scores = scores_by_t[t]
        ranked = sorted(scores.items(), key=lambda item: item[1])
        if len(ranked) < min_names:
            continue
        end_t = rebalance_points[position + 1] if position + 1 < len(rebalance_points) else len(dates) - 1
        buckets: list[list[str]] = [[] for _ in range(groups)]
        for index, (symbol, _) in enumerate(ranked):
            bucket = min(groups - 1, int(index * groups / len(ranked)))
            buckets[bucket].append(symbol)
        for day in range(t + 1, min(end_t + 1, len(dates))):
            group_returns = []
            for bucket in buckets:
                values = [
                    value
                    for value in (panel.return_at(symbol, day) for symbol in bucket)
                    if value is not None
                ]
                group_returns.append(sum(values) / len(values) if values else 0.0)
            for index, value in enumerate(group_returns):
                series[f"Q{index + 1}"].append((dates[day], value))
            series[spread_key].append((dates[day], group_returns[-1] - group_returns[0]))
    summary = {name: performance(points) for name, points in series.items()}
    return {"groups": groups, "series": series, "summary": summary}


def performance(points: list[tuple[str, float]]) -> dict:
    values = [value for _, value in points]
    if not values:
        return {
            "n": 0,
            "cagr": 0.0,
            "annual_vol": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "hit_rate": 0.0,
            "cumulative": 0.0,
        }
    wealth = []
    level = 1.0
    for value in values:
        level *= 1.0 + value
        wealth.append(level)
    years = len(values) / TRADING_DAYS
    cagr = level ** (1.0 / years) - 1.0 if years > 0 and level > 0 else 0.0
    vol = stdev(values) * math.sqrt(TRADING_DAYS)
    sharpe = mean(values) / stdev(values) * math.sqrt(TRADING_DAYS) if stdev(values) > 1e-15 else 0.0
    drawdown = max_drawdown(wealth)
    return {
        "n": len(values),
        "cagr": cagr,
        "annual_vol": vol,
        "sharpe": sharpe,
        "max_drawdown": drawdown,
        "calmar": cagr / abs(drawdown) if drawdown < -1e-9 else 0.0,
        "hit_rate": sum(1 for value in values if value > 0) / len(values),
        "cumulative": level - 1.0,
    }


def drawdown_series(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    out = []
    level = 1.0
    peak = 1.0
    for day, value in points:
        level *= 1.0 + value
        peak = max(peak, level)
        out.append((day, level / peak - 1.0))
    return out


def rolling_vol(points: list[tuple[str, float]], window: int = 60) -> list[tuple[str, float]]:
    values = [value for _, value in points]
    out = []
    for index, (day, _) in enumerate(points):
        start = max(0, index - window + 1)
        sample = values[start:index + 1]
        out.append((day, stdev(sample) * math.sqrt(TRADING_DAYS) if len(sample) > 2 else 0.0))
    return out

