"""Cross-sectional cleaning, neutralisation and orthogonalisation.

Neutralisation follows the usual Barra workflow: winsorise, standardise,
regress each raw score on industry dummies, log market cap and market beta
with cap-based weights, then standardise the residual. The resulting style
scores are orthogonalised with a symmetric (Löwdin) transform so the order of
factors does not matter.
"""
from __future__ import annotations

import math

from .factors import ALL_KEYS, factor_scores
from .linalg import (
    condition_number,
    correlation,
    invert_matrix,
    max_offdiag_corr,
    mean,
    ols,
    stdev,
    zscore,
)
from .panel import Panel


def winsorize_mad(values: list[float], k: float = 3.0) -> list[float]:
    if not values:
        return []
    ordered = sorted(values)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (
        ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]
    ) / 2.0
    deviations = sorted(abs(value - median) for value in values)
    mad = deviations[len(deviations) // 2] if len(deviations) % 2 else (
        deviations[len(deviations) // 2 - 1] + deviations[len(deviations) // 2]
    ) / 2.0
    scale = 1.4826 * mad
    if scale <= 1e-15:
        q1 = ordered[max(0, int(0.25 * (len(ordered) - 1)))]
        q3 = ordered[min(len(ordered) - 1, int(0.75 * (len(ordered) - 1)))]
        scale = (q3 - q1) / 1.349
    if scale <= 1e-15:
        scale = stdev(values)
    if scale <= 1e-15:
        return list(values)
    low, high = median - k * scale, median + k * scale
    return [max(low, min(high, value)) for value in values]


def robust_z(values: list[float], k: float = 3.0) -> list[float]:
    return zscore(winsorize_mad(values, k=k))


def _market_series(panel: Panel, t: int, window: int) -> list[float | None]:
    start = max(1, t - window + 1)
    out: list[float | None] = []
    for i in range(start, t + 1):
        values = [
            value
            for value in (panel.return_at(symbol, i) for symbol in panel.symbols)
            if value is not None
        ]
        out.append(sum(values) / len(values) if values else None)
    return out


def rolling_beta(panel: Panel, symbol: str, t: int, market: list[float | None], window: int) -> float:
    start = max(1, t - window + 1)
    pairs = []
    for offset, i in enumerate(range(start, t + 1)):
        stock = panel.return_at(symbol, i)
        benchmark = market[offset] if offset < len(market) else None
        if stock is not None and benchmark is not None:
            pairs.append((benchmark, stock))
    if len(pairs) < 60:
        return 1.0
    mx = mean([pair[0] for pair in pairs])
    my = mean([pair[1] for pair in pairs])
    var = sum((pair[0] - mx) ** 2 for pair in pairs)
    if var <= 1e-15:
        return 1.0
    cov = sum((pair[0] - mx) * (pair[1] - my) for pair in pairs)
    return max(-0.5, min(2.5, cov / var))


def build_exposures(panel: Panel, t: int, symbols: list[str], beta_window: int = 252) -> dict:
    industries = sorted({panel.industry.get(symbol, "Unknown") for symbol in symbols})
    baseline = industries[0] if industries else "Unknown"
    market = _market_series(panel, t, beta_window)
    log_caps = []
    betas = []
    for symbol in symbols:
        cap = panel.market_cap[symbol][t] or 1.0
        log_caps.append(math.log(max(cap, 1.0)))
        betas.append(rolling_beta(panel, symbol, t, market, beta_window))
    cap_z = robust_z(log_caps)
    beta_z = robust_z(betas)
    rows = []
    weights = []
    for index, symbol in enumerate(symbols):
        row = [1.0]
        for industry in industries[1:]:
            row.append(1.0 if panel.industry.get(symbol, "Unknown") == industry else 0.0)
        row.extend((cap_z[index], beta_z[index]))
        rows.append(row)
        cap = panel.market_cap[symbol][t] or 1.0
        weights.append(math.sqrt(max(cap, 1.0)))
    average = mean(weights)
    weights = [value / average for value in weights]
    return {
        "rows": rows,
        "weights": weights,
        "names": ["intercept"] + [f"industry:{item}" for item in industries[1:]] + ["log_size", "beta"],
        "industries": industries,
        "baseline": baseline,
        "betas": dict(zip(symbols, betas)),
        "log_caps": dict(zip(symbols, log_caps)),
    }


def neutralize_scores(
    scores: dict[str, float],
    exposures: dict,
    symbols: list[str],
    ridge: float = 1e-6,
    exclude: set[str] | None = None,
) -> dict:
    names = [symbol for symbol in symbols if symbol in scores]
    if len(names) < 12:
        values = [scores[name] for name in names]
        z = robust_z(values) if values else []
        return {"scores": dict(zip(names, z)), "r2": 0.0, "n": len(names), "ok": False}
    index_of = {symbol: index for index, symbol in enumerate(symbols)}
    exclude = exclude or set()
    keep = [i for i, name in enumerate(exposures["names"]) if name not in exclude]
    rows = [[exposures["rows"][index_of[symbol]][i] for i in keep] for symbol in names]
    weights = [exposures["weights"][index_of[symbol]] for symbol in names]
    y = robust_z([scores[symbol] for symbol in names])
    fit = ols(rows, y, weights=weights, ridge=ridge)
    residual = robust_z(fit["residuals"])
    return {
        "scores": dict(zip(names, residual)),
        "r2": fit["r2"],
        "n": len(names),
        "ok": True,
    }


def _score_matrix(score_map: dict[str, dict[str, float]], keys: list[str]) -> tuple[list[str], list[list[float]]]:
    common = set(score_map[keys[0]])
    for key in keys[1:]:
        common &= set(score_map[key])
    symbols = sorted(common)
    if len(symbols) < 5:
        return [], []
    rows = []
    for symbol in symbols:
        rows.append([score_map[key][symbol] for key in keys])
    return symbols, rows


def correlation_report(score_map: dict[str, dict[str, float]], keys: list[str]) -> dict:
    _, rows = _score_matrix(score_map, keys)
    if not rows:
        return {"keys": keys, "matrix": [], "max_offdiag": 0.0, "condition": 1.0, "vif": [1.0] * len(keys)}
    corr = correlation(rows)
    try:
        inv = invert_matrix(corr)
        vif = [max(inv[i][i], 1.0) for i in range(len(keys))]
    except ValueError:
        vif = [float("inf")] * len(keys)
    return {
        "keys": keys,
        "matrix": corr,
        "max_offdiag": max_offdiag_corr(corr),
        "condition": condition_number(corr),
        "vif": vif,
    }


def orthogonalize_symmetric(
    score_map: dict[str, dict[str, float]],
    keys: list[str] | None = None,
    shrink: float = 0.05,
) -> dict:
    keys = list(keys or score_map.keys())
    keys = [key for key in keys if score_map.get(key)]
    if len(keys) < 2:
        return {"scores": {key: score_map.get(key, {}) for key in keys}, "keys": keys, "skipped": True}
    symbols, rows = _score_matrix(score_map, keys)
    if len(symbols) < max(15, 2 * len(keys)):
        return {
            "scores": {key: dict(score_map[key]) for key in keys},
            "keys": keys,
            "skipped": True,
            "reason": "common sample too small",
        }
    columns = [[rows[i][j] for i in range(len(rows))] for j in range(len(keys))]
    columns = [zscore(column) for column in columns]
    matrix = [[rows[i][j] for j in range(len(keys))] for i in range(len(rows))]
    for i in range(len(rows)):
        for j in range(len(keys)):
            matrix[i][j] = columns[j][i]
    corr = correlation(matrix)
    corr_shrunk = [
        [(1.0 - shrink) * corr[i][j] + (shrink if i == j else 0.0) for j in range(len(keys))]
        for i in range(len(keys))
    ]
    from .linalg import matmul, inv_sqrt_spd

    root = inv_sqrt_spd(corr_shrunk)
    transformed = matmul(matrix, root)
    out = {}
    for j, key in enumerate(keys):
        column = [transformed[i][j] for i in range(len(rows))]
        column = zscore(column)
        original = columns[j]
        if sum(a * b for a, b in zip(column, original)) < 0:
            column = [-value for value in column]
        out[key] = dict(zip(symbols, column))
    after = correlation([[out[key][symbol] for key in keys] for symbol in symbols])
    return {
        "scores": out,
        "keys": keys,
        "skipped": False,
        "max_offdiag_before": max_offdiag_corr(corr),
        "max_offdiag_after": max_offdiag_corr(after),
        "condition_before": condition_number(corr),
        "condition_after": condition_number(after),
        "n": len(symbols),
    }


def orthogonalize_sequential(
    score_map: dict[str, dict[str, float]],
    keys: list[str] | None = None,
) -> dict:
    """Gram-Schmidt residualisation, kept as a diagnostic alternative."""
    keys = list(keys or score_map.keys())
    keys = [key for key in keys if score_map.get(key)]
    if len(keys) < 2:
        return {"scores": {key: score_map.get(key, {}) for key in keys}, "keys": keys}
    symbols, rows = _score_matrix(score_map, keys)
    if len(symbols) < max(15, 2 * len(keys)):
        return {"scores": {key: dict(score_map[key]) for key in keys}, "keys": keys, "skipped": True}
    out: dict[str, dict[str, float]] = {}
    used: list[list[float]] = []
    for j, key in enumerate(keys):
        y = zscore([rows[i][j] for i in range(len(rows))])
        if used:
            fit = ols(used, y)
            residual = fit["residuals"]
        else:
            residual = y
        residual = zscore(residual)
        out[key] = dict(zip(symbols, residual))
        used.append(residual)
    return {"scores": out, "keys": keys, "skipped": False}


def prepare_cross_section(
    panel: Panel,
    t: int,
    keys: tuple[str, ...] = ALL_KEYS,
    min_names: int = 15,
    neutralize: bool = True,
    orthogonalize: bool = True,
) -> dict:
    eligible = panel.eligible(t)
    if len(eligible) < min_names:
        return {"date": panel.dates[t], "eligible": eligible, "scores": {}, "diagnostics": {}}
    raw = {key: factor_scores(panel, t, key) for key in keys}
    raw = {key: {symbol: value for symbol, value in values.items() if symbol in set(eligible)} for key, values in raw.items()}
    usable = [
        key
        for key in keys
        if len(raw[key]) >= max(min_names, int(0.45 * len(eligible)))
    ]
    if not usable:
        return {"date": panel.dates[t], "eligible": eligible, "scores": {}, "diagnostics": {}}
    if neutralize:
        exposures = build_exposures(panel, t, eligible)
        cleaned = {}
        r2 = {}
        for key in usable:
            exclude = {"log_size"} if key == "size" else {"beta"} if key == "low_vol" else set()
            result = neutralize_scores(raw[key], exposures, eligible, exclude=exclude)
            if result["scores"]:
                cleaned[key] = result["scores"]
                r2[key] = result["r2"]
    else:
        cleaned = {key: dict(zip(raw[key], robust_z(list(raw[key].values())))) for key in usable}
        r2 = {key: 0.0 for key in usable}
        exposures = {}
    if len(cleaned) < 2:
        return {
            "date": panel.dates[t],
            "eligible": eligible,
            "scores": cleaned,
            "diagnostics": {"neutralization_r2": r2, "usable": list(cleaned)},
        }
    before = correlation_report(cleaned, list(cleaned))
    if orthogonalize:
        orth = orthogonalize_symmetric(cleaned, list(cleaned))
        final = orth.pop("scores")
    else:
        orth = {"skipped": True}
        final = cleaned
    after = correlation_report(final, list(final))
    return {
        "date": panel.dates[t],
        "eligible": eligible,
        "scores": final,
        "diagnostics": {
            "usable": list(final),
            "neutralization_r2": r2,
            "correlation_before": before,
            "correlation_after": after,
            "orthogonalization": orth,
            "exposures": {
                "industries": exposures.get("industries", []),
                "baseline": exposures.get("baseline"),
                "betas": exposures.get("betas", {}),
            },
        },
    }

