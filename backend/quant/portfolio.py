"""Composite factor portfolio construction and walk-forward backtesting."""
from __future__ import annotations

import math

from .evaluate import ic_series, performance
from .linalg import mean, stdev
from .panel import Panel


def composite_scores(scores: dict[str, dict[str, float]], weights: dict[str, float]) -> dict[str, float]:
    out = {}
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return out
    symbols = set()
    for key, weight in weights.items():
        if weight > 0:
            symbols |= set(scores.get(key, {}))
    for symbol in symbols:
        numerator = 0.0
        denominator = 0.0
        for key, weight in weights.items():
            value = scores.get(key, {}).get(symbol)
            if value is not None and weight > 0:
                numerator += weight * value
                denominator += weight
        if denominator >= 0.55 * total_weight:
            out[symbol] = numerator / denominator
    return out


def _market_vol_percentile(panel: Panel, t: int, window: int = 60, history: int = 252) -> float:
    values = []
    for i in range(max(1, t - window + 1), t + 1):
        value = panel.market_return(i)
        if value is not None:
            values.append(value)
    current = stdev(values) * math.sqrt(252.0) if len(values) > 5 else 0.0
    history_values = []
    for end in range(max(window, t - history + 1), t + 1):
        sample = []
        for i in range(max(1, end - window + 1), end + 1):
            value = panel.market_return(i)
            if value is not None:
                sample.append(value)
        if len(sample) > 5:
            history_values.append(stdev(sample) * math.sqrt(252.0))
    if not history_values:
        return 0.5
    return sum(1 for value in history_values if value <= current) / len(history_values)


def regime_tilt(panel: Panel, t: int) -> dict:
    percentile = _market_vol_percentile(panel, t)
    stressed = percentile >= 0.75
    if stressed:
        tilt = {
            "low_vol": 1.6,
            "quality": 1.35,
            "momentum": 0.55,
            "illiquidity": 0.45,
            "size": 0.7,
            "reversal": 0.9,
            "value": 1.0,
        }
    else:
        tilt = {key: 1.0 for key in ("low_vol", "quality", "momentum", "illiquidity", "size", "reversal", "value")}
    return {"percentile": percentile, "stressed": stressed, "tilt": tilt}


def adaptive_weights(
    ic_by_key: dict[str, list[dict]],
    keys: list[str],
    cutoff_date: str,
    lookback: int = 252,
    min_observations: int = 60,
    shrink: float = 0.5,
    cap: float = 0.32,
    tilt: dict[str, float] | None = None,
) -> dict:
    equal = 1.0 / len(keys)
    raw = {}
    diagnostics = {}
    for key in keys:
        sample = [item["ic"] for item in ic_by_key.get(key, []) if item["date"] < cutoff_date][-lookback:]
        if len(sample) >= min_observations:
            mu = mean(sample)
            sd = stdev(sample)
            icir = mu / sd if sd > 1e-15 else 0.0
        else:
            icir = 0.0
        raw[key] = max(0.0, icir)
        diagnostics[key] = {"icir": icir, "n": len(sample)}
    total = sum(raw.values())
    if total <= 1e-12:
        weights = {key: equal for key in keys}
    else:
        weights = {key: (1.0 - shrink) * raw[key] / total + shrink * equal for key in keys}
    if tilt:
        weights = {key: weights[key] * tilt.get(key, 1.0) for key in keys}
        total = sum(weights.values())
        weights = {key: value / total for key, value in weights.items()}
    for _ in range(4):
        over = [key for key, value in weights.items() if value > cap]
        if not over:
            break
        excess = sum(weights[key] - cap for key in over)
        for key in over:
            weights[key] = cap
        rest = [key for key in keys if key not in over]
        rest_total = sum(weights[key] for key in rest)
        if rest_total <= 1e-12:
            break
        for key in rest:
            weights[key] += excess * weights[key] / rest_total
    total = sum(weights.values())
    weights = {key: value / total for key, value in weights.items()}
    return {"weights": weights, "diagnostics": diagnostics}


def top_weights(scores: dict[str, float], fraction: float = 0.2, minimum: int = 10) -> dict[str, float]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    count = max(minimum, int(math.ceil(len(ranked) * fraction)))
    count = min(count, len(ranked))
    selected = ranked[:count]
    if not selected:
        return {}
    weight = 1.0 / len(selected)
    return {symbol: weight for symbol, _ in selected}


def long_short_weights(scores: dict[str, float], fraction: float = 0.2, minimum: int = 8) -> dict[str, float]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    count = max(minimum, int(math.ceil(len(ranked) * fraction)))
    count = min(count, len(ranked) // 2)
    if count <= 0:
        return {}
    long_leg = ranked[:count]
    short_leg = ranked[-count:]
    weight = 0.5 / count
    out = {symbol: weight for symbol, _ in long_leg}
    for symbol, _ in short_leg:
        out[symbol] = out.get(symbol, 0.0) - weight
    return {symbol: value for symbol, value in out.items() if abs(value) > 1e-12}


def vol_target_scale(
    panel: Panel,
    weights: dict[str, float],
    t: int,
    target_vol: float = 0.10,
    window: int = 60,
    floor: float = 0.2,
    max_scale: float = 1.0,
) -> tuple[float, float]:
    returns = []
    for day in range(max(1, t - window + 1), t + 1):
        value = 0.0
        for symbol, weight in weights.items():
            ret = panel.return_at(symbol, day)
            if ret is not None:
                value += weight * ret
        returns.append(value)
    if len(returns) < 10:
        return 1.0, 0.0
    vol = stdev(returns) * math.sqrt(252.0)
    if vol <= 1e-9:
        return 1.0, 0.0
    scale = min(max_scale, target_vol / vol)
    return max(floor, scale), vol


def _turnover(old: dict[str, float], new: dict[str, float]) -> float:
    symbols = set(old) | set(new)
    old_cash = max(0.0, 1.0 - sum(old.values()))
    new_cash = max(0.0, 1.0 - sum(new.values()))
    total = abs(new_cash - old_cash)
    for symbol in symbols:
        total += abs(new.get(symbol, 0.0) - old.get(symbol, 0.0))
    return 0.5 * total


def _drift(weights: dict[str, float], returns: dict[str, float | None]) -> dict[str, float]:
    gross = 0.0
    for symbol, weight in weights.items():
        ret = returns.get(symbol)
        gross += weight * (ret if ret is not None else 0.0)
    if gross <= -0.999:
        return dict(weights)
    out = {}
    for symbol, weight in weights.items():
        ret = returns.get(symbol)
        out[symbol] = weight * (1.0 + (ret if ret is not None else 0.0)) / (1.0 + gross)
    return out


def run_backtest(
    panel: Panel,
    prepared_by_t: dict[int, dict],
    keys: list[str],
    mode: str = "adaptive",
    rebalance: int = 21,
    top_fraction: float = 0.2,
    target_vol: float = 0.10,
    cost_bps: float = 5.0,
    benchmark: bool = False,
    ic_by_key: dict[str, list[dict]] | None = None,
) -> dict:
    indices = sorted(prepared_by_t)
    if not indices:
        return {"points": [], "metrics": performance([]), "turnover": [], "weights": {}}
    start = indices[0]
    ic_by_key = ic_by_key or {
        key: ic_series(panel, prepared_by_t, key, horizon=1)
        for key in keys
    }
    weights: dict[str, float] = {}
    points: list[tuple[str, float]] = []
    turnovers: list[dict] = []
    weight_history: list[dict] = []
    cost_for_next = 0.0
    regime_log = []
    for t in range(start, len(panel.dates) - 1):
        if (t - start) % rebalance == 0:
            if benchmark:
                eligible = panel.eligible(t)
                target = {symbol: 1.0 / len(eligible) for symbol in eligible} if eligible else {}
                scale, estimate = 1.0, 0.0
                detail = {}
            else:
                cross = prepared_by_t.get(t, {})
                if not cross:
                    continue
                current_keys = [key for key in keys if key in cross.get("scores", {})]
                if len(current_keys) < 3:
                    continue
                if mode == "adaptive":
                    regime = regime_tilt(panel, t)
                    result = adaptive_weights(
                        ic_by_key,
                        current_keys,
                        panel.dates[t - 1] if t > 0 else panel.dates[t],
                        tilt=regime["tilt"] if regime["stressed"] else None,
                    )
                    used_weights = result["weights"]
                    detail = {"ic": result["diagnostics"], "regime": regime}
                    regime_log.append({"date": panel.dates[t], **regime})
                else:
                    used_weights = {key: 1.0 / len(current_keys) for key in current_keys}
                    detail = {}
                scores = composite_scores(cross["scores"], used_weights)
                if mode == "long_short":
                    target = long_short_weights(scores, fraction=top_fraction)
                else:
                    target = top_weights(scores, fraction=top_fraction)
                scale, estimate = vol_target_scale(
                    panel,
                    target,
                    t,
                    target_vol=target_vol,
                    max_scale=1.2 if mode == "long_short" else 1.0,
                )
                target = {symbol: weight * scale for symbol, weight in target.items()}
                detail.update({"vol_estimate": estimate, "scale": scale, "factor_weights": used_weights})
            turnover = _turnover(weights, target)
            cost_for_next = turnover * cost_bps / 10000.0
            weights = target
            turnovers.append({"date": panel.dates[t], "turnover": turnover, "cost": cost_for_next})
            weight_history.append({"date": panel.dates[t], "weights": dict(weights), "detail": detail})
        next_returns = {}
        gross = 0.0
        for symbol, weight in weights.items():
            ret = panel.return_at(symbol, t + 1)
            next_returns[symbol] = ret
            if ret is not None:
                gross += weight * ret
        net = gross - cost_for_next
        points.append((panel.dates[t + 1], net))
        weights = _drift(weights, next_returns)
        cost_for_next = 0.0
    total_turnover = sum(item["turnover"] for item in turnovers)
    years = max(len(points) / 252.0, 1e-9)
    metrics = performance(points)
    metrics["annual_turnover"] = total_turnover / years
    metrics["average_invested"] = mean([sum(item["weights"].values()) for item in weight_history]) if weight_history else 0.0
    metrics["average_gross"] = mean([sum(abs(value) for value in item["weights"].values()) for item in weight_history]) if weight_history else 0.0
    metrics["average_net"] = metrics["average_invested"]
    metrics["rebalances"] = len(turnovers)
    return {
        "mode": mode,
        "points": points,
        "metrics": metrics,
        "turnover": turnovers,
        "weights": weight_history[-1]["weights"] if weight_history else {},
        "weight_history": weight_history,
        "regime_log": regime_log,
    }


def latest_holdings(
    panel: Panel,
    result: dict,
    composite: dict[str, float] | None = None,
) -> list[dict]:
    weights = result.get("weights", {})
    t = len(panel.dates) - 1
    rows = []
    for symbol, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True):
        rows.append(
            {
                "symbol": symbol,
                "weight": weight,
                "industry": panel.industry.get(symbol, "Unknown"),
                "market_cap": panel.market_cap[symbol][t],
                "score": (composite or {}).get(symbol),
            }
        )
    return rows

