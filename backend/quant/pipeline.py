"""End-to-end FactorLab research run and artifact writer."""
from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .evaluate import (
    average_correlation,
    decay_curve,
    drawdown_series,
    half_life,
    ic_series,
    ic_stats,
    performance,
    quantile_from_scores,
)
from .factors import ALL_KEYS, BY_KEY, spec_table
from .linalg import cumulative, pearson
from .options import protective_put_overlay
from .panel import Panel
from .portfolio import adaptive_weights, composite_scores, latest_holdings, run_backtest
from .preprocess import prepare_cross_section
from .risk import build_risk_model, cross_sectional_factor_returns, factor_stats
from .synthetic import SyntheticConfig, generate_dataset

HONG_KONG = timezone(timedelta(hours=8))


@dataclass
class RunConfig:
    seed: int = 42
    years: int = 6
    n_symbols: int = 80
    start: str = "2020-01-02"
    target_vol: float = 0.10
    cost_bps: float = 5.0
    rebalance: int = 21
    top_fraction: float = 0.20
    portfolio_value: float = 1_000_000.0
    out_dir: str = "reports/factorlab-demo"
    label: str = "FactorLab demo"
    verbose: bool = True


def _json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _average_diagnostic_matrix(prepared_by_t: dict[int, dict], field_name: str, keys: list[str]) -> dict:
    matrices = []
    for t in sorted(prepared_by_t):
        payload = prepared_by_t[t].get("diagnostics", {}).get(field_name, {})
        if payload.get("matrix"):
            matrices.append((payload.get("keys", []), payload["matrix"]))
    if not matrices:
        return {"keys": keys, "matrix": [[1.0 if i == j else 0.0 for j in range(len(keys))] for i in range(len(keys))]}
    totals = [[0.0] * len(keys) for _ in keys]
    counts = [[0] * len(keys) for _ in keys]
    for available, matrix in matrices:
        for i, key_i in enumerate(available):
            if key_i not in keys:
                continue
            for j, key_j in enumerate(available):
                if key_j not in keys:
                    continue
                a, b = keys.index(key_i), keys.index(key_j)
                totals[a][b] += matrix[i][j]
                counts[a][b] += 1
    return {
        "keys": keys,
        "matrix": [
            [totals[i][j] / counts[i][j] if counts[i][j] else (1.0 if i == j else 0.0) for j in range(len(keys))]
            for i in range(len(keys))
        ],
    }


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _truth_check(panel: Panel, truth: dict, factor_result: dict, keys: list[str]) -> list[dict]:
    out = []
    true_series = truth.get("factor_series", {})
    estimated = factor_result.get("series", {})
    date_index = {day: index for index, day in enumerate(panel.dates)}
    for key in keys:
        truth_values = true_series.get(key)
        estimate = estimated.get(key, [])
        if not truth_values or len(estimate) < 30:
            continue
        paired = [
            (truth_values[date_index[item["date"]] + 1], item["return"])
            for item in estimate
            if item["date"] in date_index and date_index[item["date"]] + 1 < len(truth_values)
        ]
        if len(paired) < 30:
            continue
        corr = pearson([item[0] for item in paired], [item[1] for item in paired])
        out.append({"factor": key, "label": BY_KEY[key].label, "correlation": corr, "n": len(paired)})
    return out


def _factor_table(
    keys: list[str],
    ic_by_key: dict[str, list[dict]],
    prepared_by_t: dict[int, dict],
    panel: Panel,
) -> tuple[list[dict], dict]:
    rows = []
    decays = {}
    latest = prepared_by_t[max(prepared_by_t)]
    after = latest.get("diagnostics", {}).get("correlation_after", {})
    before = latest.get("diagnostics", {}).get("correlation_before", {})
    after_keys = after.get("keys", [])
    before_keys = before.get("keys", [])
    after_vif = dict(zip(after_keys, after.get("vif", []))) if after_keys else {}
    before_vif = dict(zip(before_keys, before.get("vif", []))) if before_keys else {}
    for key in keys:
        values = ic_by_key.get(key, [])
        stats = ic_stats(values)
        decay = decay_curve(panel, prepared_by_t, key)
        decays[key] = decay
        rows.append(
            {
                "key": key,
                "label": BY_KEY[key].label,
                "category": BY_KEY[key].category,
                "description": BY_KEY[key].description,
                "ic_mean": stats["mean"],
                "ic_std": stats["std"],
                "icir": stats["icir"],
                "icir_annual": stats["icir_annual"],
                "tstat": stats["tstat"],
                "hit_rate": stats["hit_rate"],
                "n": stats["n"],
                "half_life": half_life(decay),
                "vif_before": before_vif.get(key),
                "vif_after": after_vif.get(key),
            }
        )
    return rows, decays


def _merge_points(named: dict[str, list[tuple[str, float]]]) -> tuple[list[str], dict[str, dict[str, float]]]:
    dates = sorted({day for points in named.values() for day, _ in points})
    maps = {name: dict(points) for name, points in named.items()}
    return dates, maps


def run(config: RunConfig | None = None, panel: Panel | None = None, truth: dict | None = None) -> dict:
    config = config or RunConfig()
    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if panel is None:
        panel, truth = generate_dataset(
            SyntheticConfig(seed=config.seed, years=config.years, n_symbols=config.n_symbols, start=config.start)
        )
    truth = truth or {}
    if len(panel.dates) < 420:
        raise ValueError("synthetic panel is too short for a factor run")
    eval_start = 273
    prepared_by_t: dict[int, dict] = {}
    for position, t in enumerate(range(eval_start, len(panel.dates) - 1)):
        cross = prepare_cross_section(panel, t)
        if cross.get("scores"):
            prepared_by_t[t] = cross
        if config.verbose and position % 200 == 0:
            print(f"prepare {position + 1}/{len(panel.dates) - 1 - eval_start} {panel.dates[t]}")
    if len(prepared_by_t) < 150:
        raise ValueError("not enough prepared cross-sections; increase years")
    keys = [
        key
        for key in ALL_KEYS
        if sum(1 for t in prepared_by_t if key in prepared_by_t[t].get("scores", {})) >= 120
    ]
    if len(keys) < 3:
        raise ValueError("not enough usable factors")
    ic_by_key = {key: ic_series(panel, prepared_by_t, key) for key in keys}
    factor_rows, decay_map = _factor_table(keys, ic_by_key, prepared_by_t, panel)
    average_before = _average_diagnostic_matrix(prepared_by_t, "correlation_before", keys)
    average_after = _average_diagnostic_matrix(prepared_by_t, "correlation_after", keys)
    correlation_summary = average_correlation(prepared_by_t, keys)

    adaptive = run_backtest(
        panel,
        prepared_by_t,
        keys,
        mode="adaptive",
        rebalance=config.rebalance,
        top_fraction=config.top_fraction,
        target_vol=config.target_vol,
        cost_bps=config.cost_bps,
        ic_by_key=ic_by_key,
    )
    equal = run_backtest(
        panel,
        prepared_by_t,
        keys,
        mode="equal",
        rebalance=config.rebalance,
        top_fraction=config.top_fraction,
        target_vol=config.target_vol,
        cost_bps=config.cost_bps,
        ic_by_key=ic_by_key,
    )
    long_short = run_backtest(
        panel,
        prepared_by_t,
        keys,
        mode="long_short",
        rebalance=config.rebalance,
        top_fraction=config.top_fraction,
        target_vol=config.target_vol,
        cost_bps=config.cost_bps,
        ic_by_key=ic_by_key,
    )
    benchmark = run_backtest(
        panel,
        prepared_by_t,
        keys,
        mode="benchmark",
        rebalance=config.rebalance,
        cost_bps=config.cost_bps,
        benchmark=True,
        ic_by_key=ic_by_key,
    )

    factor_result = cross_sectional_factor_returns(panel, prepared_by_t, keys)
    risk = build_risk_model(panel, prepared_by_t, keys, adaptive["weights"], factor_result=factor_result)
    stress_rows = risk.get("stress", []) if risk.get("ok") else []
    worst_stress = max((-row["pnl"] for row in stress_rows), default=0.0)
    hedge_beta = max(risk.get("beta", 1.0) if risk.get("ok") else 1.0, worst_stress / 0.20)
    hedge_beta = min(hedge_beta, 1.5)
    hedge = protective_put_overlay(
        portfolio_value=config.portfolio_value,
        beta=hedge_beta,
        vol=max(0.18, risk.get("total_vol", 0.20) if risk.get("ok") else 0.20),
        loss_cap=0.10,
        stress_move=-0.20,
    )
    hedge["beta_source"] = "max(portfolio beta, worst stress loss / 20%)"

    ranked = [row for row in factor_rows if row["n"] >= 60]
    ranked.sort(key=lambda row: row["icir"], reverse=True)
    equal_factor_weights = {key: 1.0 / len(keys) for key in keys}
    composite_by_t = {
        t: composite_scores(prepared_by_t[t].get("scores", {}), equal_factor_weights)
        for t in prepared_by_t
    }
    quantile = quantile_from_scores(panel, composite_by_t) if composite_by_t else {"series": {}, "summary": {}}

    latest_rebalance = adaptive["weight_history"][-1] if adaptive.get("weight_history") else None
    composite = {}
    if latest_rebalance:
        t = panel.index(latest_rebalance["date"])
        factor_weights = latest_rebalance.get("detail", {}).get("factor_weights") or {key: 1.0 / len(keys) for key in keys}
        composite = composite_scores(prepared_by_t.get(t, {}).get("scores", {}), factor_weights)
    holdings = latest_holdings(panel, adaptive, composite)
    for row in holdings:
        row["market_cap"] = row.get("market_cap")

    dates, maps = _merge_points(
        {
            "adaptive": adaptive["points"],
            "equal": equal["points"],
            "long_short": long_short["points"],
            "benchmark": benchmark["points"],
        }
    )
    equity = {}
    drawdown = {}
    for name, points in (
        ("adaptive", adaptive["points"]),
        ("equal", equal["points"]),
        ("long_short", long_short["points"]),
        ("benchmark", benchmark["points"]),
    ):
        equity[name] = {day: value for day, value in zip(dates, cumulative([maps[name].get(day, 0.0) for day in dates]))}
        drawdown[name] = {day: value for day, value in drawdown_series([(day, maps[name].get(day, 0.0)) for day in dates])}

    generated = datetime.now(HONG_KONG).isoformat(timespec="seconds")
    summary = {
        "meta": {
            "engine": "FactorLab",
            "version": __version__,
            "label": config.label,
            "generated_at": generated,
            "data_kind": "synthetic" if panel.is_synthetic else "csv",
            "disclaimer": "合成数据仅用于方法验证，不是实盘回测，不构成投资建议。",
            "panel": panel.describe(),
            "config": {
                "seed": config.seed,
                "years": config.years,
                "n_symbols": config.n_symbols,
                "start": config.start,
                "target_vol": config.target_vol,
                "cost_bps": config.cost_bps,
                "rebalance": config.rebalance,
                "top_fraction": config.top_fraction,
                "portfolio_value": config.portfolio_value,
            },
        },
        "factor_definitions": spec_table(),
        "factors": factor_rows,
        "decay": decay_map,
        "correlation": {
            "before": average_before,
            "after": average_after,
            "daily_average": correlation_summary,
            "latest_join": prepared_by_t[max(prepared_by_t)].get("diagnostics", {}).get("orthogonalization", {}),
        },
        "backtest": {
            "adaptive": {"metrics": adaptive["metrics"], "turnover": adaptive["turnover"], "regime": adaptive["regime_log"]},
            "equal": {"metrics": equal["metrics"], "turnover": equal["turnover"]},
            "long_short": {"metrics": long_short["metrics"], "turnover": long_short["turnover"]},
            "benchmark": {"metrics": benchmark["metrics"]},
            "dates": dates,
            "returns": {name: [maps[name].get(day, 0.0) for day in dates] for name in maps},
            "equity": {name: [equity[name][day] for day in dates] for name in equity},
            "drawdown": {name: [drawdown[name][day] for day in dates] for name in drawdown},
        },
        "quantile": {
            "factor": "composite",
            "label": "综合因子（等权）",
            "summary": quantile.get("summary", {}),
            "series": {
                name: {"dates": [day for day, _ in points], "values": [value for _, value in points]}
                for name, points in quantile.get("series", {}).items()
            },
        },
        "holdings": holdings,
        "risk": risk,
        "hedge": hedge,
        "diagnostics": {
            "truth_check": _truth_check(
                panel,
                truth,
                factor_result,
                [key for key in keys if key in ("value", "quality", "illiquidity", "low_vol")],
            ),
            "factor_return_observations": {key: len(factor_result["series"].get(key, [])) for key in keys},
        },
    }
    _write_json(out_dir / "summary.json", summary)
    _write_csv(
        out_dir / "factor_ic.csv",
        ["factor", "label", "category", "ic_mean", "ic_std", "icir", "tstat", "hit_rate", "n", "half_life", "vif_before", "vif_after"],
        [
            [
                row["key"],
                row["label"],
                row["category"],
                row["ic_mean"],
                row["ic_std"],
                row["icir"],
                row["tstat"],
                row["hit_rate"],
                row["n"],
                row["half_life"],
                row["vif_before"],
                row["vif_after"],
            ]
            for row in factor_rows
        ],
    )
    _write_csv(
        out_dir / "equity_curve.csv",
        ["date", "adaptive", "equal", "benchmark", "adaptive_drawdown"],
        [
            [day, equity["adaptive"][day], equity["equal"][day], equity["benchmark"][day], drawdown["adaptive"][day]]
            for day in dates
        ],
    )
    _write_csv(
        out_dir / "holdings.csv",
        ["symbol", "weight", "industry", "market_cap", "composite_score"],
        [
            [row["symbol"], row["weight"], row["industry"], row.get("market_cap"), row.get("score")]
            for row in holdings
        ],
    )
    stress = risk.get("stress", []) if risk.get("ok") else []
    _write_csv(
        out_dir / "stress_tests.csv",
        ["scenario", "market_shock", "portfolio_pnl", "description"],
        [[row["name"], row["market"], row["pnl"], row["description"]] for row in stress],
    )
    from .report import render

    html = render(summary)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / "README.md").write_text(
        "\n".join(
            [
                "# FactorLab demo output",
                "",
                f"- Generated: {generated}",
                f"- Data: {panel.name} ({panel.source})",
                "- This is synthetic research data, not an investment record.",
                "- Open `index.html` for the report; `summary.json` contains every metric.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {"summary": summary, "out_dir": str(out_dir)}

