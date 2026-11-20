"""Self-contained HTML report for a FactorLab run."""
from __future__ import annotations

import html
import math


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _pct(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value * 100:+,.{digits}f}%"


def _pct_plain(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value * 100:,.{digits}f}%"


def _num(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value:,.{digits}f}"


def _signed(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value:+,.{digits}f}"


def _downsample(values: list[float], limit: int = 900) -> tuple[list[float], list[int]]:
    if len(values) <= limit:
        return values, list(range(len(values)))
    step = max(1, math.ceil(len(values) / limit))
    indices = list(range(0, len(values), step))
    if indices[-1] != len(values) - 1:
        indices.append(len(values) - 1)
    return [values[index] for index in indices], indices


def _line_chart(
    dates: list[str],
    series: dict[str, list[float]],
    colors: dict[str, str],
    height: int = 260,
    percent: bool = True,
    zero_line: bool = False,
) -> str:
    width = 1000
    pad_l, pad_r, pad_t, pad_b = 58, 18, 18, 34
    values = [value for items in series.values() for value in items if value is not None and math.isfinite(value)]
    if not values or not dates:
        return "<p class=\"empty\">暂无数据</p>"
    low, high = min(values), max(values)
    if zero_line:
        low, high = min(low, 0.0), max(high, 0.0)
    if high - low < 1e-9:
        high = low + 0.01
    margin = (high - low) * 0.08
    low -= margin
    high += margin
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def x(index: int) -> float:
        return pad_l + (plot_w * index / max(1, len(dates) - 1))

    def y(value: float) -> float:
        return pad_t + plot_h * (1.0 - (value - low) / (high - low))

    grid = []
    for step in range(5):
        value = low + (high - low) * step / 4.0
        yy = y(value)
        label = f"{value * 100:.1f}%" if percent else _num(value)
        grid.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" class="grid"/>'
            f'<text x="{pad_l - 8}" y="{yy + 3:.1f}" class="axis right">{label}</text>'
        )
    if zero_line and low < 0 < high:
        grid.append(
            f'<line x1="{pad_l}" y1="{y(0):.1f}" x2="{width - pad_r}" y2="{y(0):.1f}" class="zero"/>'
        )
    x_labels = []
    for index in (0, len(dates) // 2, len(dates) - 1):
        x_labels.append(
            f'<text x="{x(index):.1f}" y="{height - 8}" class="axis">{_esc(dates[index])}</text>'
        )
    paths = []
    legend = []
    for name, items in series.items():
        if not items:
            continue
        sampled, _ = _downsample(items)
        points = " ".join(f"{x(index):.1f},{y(value):.1f}" for index, value in enumerate(sampled))
        color = colors.get(name, "#4f8cff")
        paths.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.1"/>')
        legend.append(
            f'<span class="legend-item"><span class="swatch" style="background:{color}"></span>{_esc(name)}</span>'
        )
    svg = (
        f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">'
        + "".join(grid)
        + f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" y2="{pad_t + plot_h}" class="frame"/>'
        + "".join(paths)
        + "".join(x_labels)
        + "</svg>"
    )
    return f'<div class="legend">{"".join(legend)}</div>{svg}'


def _bar_chart(labels: list[str], values: list[float], height: int = 230, percent: bool = True) -> str:
    width = 1000
    pad_l, pad_r, pad_t, pad_b = 58, 18, 24, 42
    if not values:
        return "<p class=\"empty\">暂无数据</p>"
    low, high = min(0.0, min(values)), max(0.0, max(values))
    if high - low < 1e-9:
        high = low + 0.01
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    def y(value: float) -> float:
        return pad_t + plot_h * (1.0 - (value - low) / (high - low))

    slot = plot_w / max(1, len(values))
    bars = []
    zero = y(0.0)
    for index, value in enumerate(values):
        x0 = pad_l + slot * index + slot * 0.18
        bar_w = slot * 0.64
        top = y(value)
        color = "#e05a5a" if value >= 0 else "#2f9e6f"
        bars.append(
            f'<rect x="{x0:.1f}" y="{min(top, zero):.1f}" width="{bar_w:.1f}" '
            f'height="{abs(zero - top):.1f}" fill="{color}" opacity="0.88"/>'
            f'<text x="{x0 + bar_w / 2:.1f}" y="{height - 14}" class="axis center">{_esc(labels[index])}</text>'
            f'<text x="{x0 + bar_w / 2:.1f}" y="{min(top, zero) - 7:.1f}" class="value center">'
            f'{value * 100:+.2f}%</text>'
        )
    grid = []
    for step in range(5):
        value = low + (high - low) * step / 4.0
        yy = y(value)
        grid.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" class="grid"/>'
            f'<text x="{pad_l - 8}" y="{yy + 3:.1f}" class="axis right">{value * 100:.1f}%</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">'
        + "".join(grid)
        + f'<line x1="{pad_l}" y1="{zero:.1f}" x2="{width - pad_r}" y2="{zero:.1f}" class="zero"/>'
        + "".join(bars)
        + "</svg>"
    )


def _heatmap(keys: list[str], matrix: list[list[float]], labels: dict[str, str], small: bool = False) -> str:
    if not matrix:
        return "<p class=\"empty\">暂无数据</p>"
    head = "".join(f"<th>{_esc(labels.get(key, key))}</th>" for key in keys)
    rows = []
    for index, key in enumerate(keys):
        cells = []
        for value in matrix[index]:
            magnitude = min(abs(value), 1.0)
            if value >= 0:
                background = f"rgba(79,140,255,{0.06 + 0.5 * magnitude:.3f})"
            else:
                background = f"rgba(224,90,90,{0.06 + 0.5 * magnitude:.3f})"
            cells.append(
                f'<td style="background:{background}" class="{"small" if small else ""}">{value:+.2f}</td>'
            )
        rows.append(f"<tr><th>{_esc(labels.get(key, key))}</th>{''.join(cells)}</tr>")
    return (
        f'<div class="table-wrap"><table class="heatmap"><thead><tr><th></th>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _metrics_table(backtest: dict) -> str:
    rows = []
    labels = (
        ("adaptive", "ICIR 自适应"),
        ("equal", "等权因子"),
        ("long_short", "纯因子多空"),
        ("benchmark", "等权基准"),
    )
    metrics = [(name, backtest[name]["metrics"]) for name, _ in labels]
    fields = (
        ("cagr", "年化收益", _pct),
        ("annual_vol", "年化波动", _pct_plain),
        ("sharpe", "Sharpe", _num),
        ("max_drawdown", "最大回撤", _pct),
        ("calmar", "Calmar", _num),
        ("hit_rate", "日胜率", _pct_plain),
        ("annual_turnover", "年化换手", _pct_plain),
        ("average_gross", "平均总敞口", _pct_plain),
    )
    for key, label, formatter in fields:
        cells = "".join(f"<td>{formatter(item[1].get(key))}</td>" for item in metrics)
        rows.append(f"<tr><th>{label}</th>{cells}</tr>")
    head = "".join(f"<th>{label}</th>" for _, label in labels)
    return (
        f'<div class="table-wrap"><table><thead><tr><th>指标</th>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def _factor_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td class=\"left\">{_esc(row['label'])}</td>"
            f"<td class=\"left muted\">{_esc(row['category'])}</td>"
            f"<td>{_pct(row['ic_mean'])}</td>"
            f"<td>{_num(row['icir'], 2)}</td>"
            f"<td>{_num(row['tstat'], 2)}</td>"
            f"<td>{_pct_plain(row['hit_rate'], 1)}</td>"
            f"<td>{_num(row['half_life'], 0) if row['half_life'] else '—'}</td>"
            f"<td>{_num(row['vif_before'], 2)}</td>"
            f"<td>{_num(row['vif_after'], 2)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>因子</th><th>类别</th><th>IC 均值</th><th>ICIR</th><th>t 值</th>"
        "<th>IC 胜率</th><th>半衰期(日)</th><th>VIF 前</th><th>VIF 后</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _decay_table(rows: list[dict], decay: dict) -> str:
    horizons = sorted({point["horizon"] for values in decay.values() for point in values})
    if not horizons:
        return "<p class=\"empty\">暂无数据</p>"
    head = "".join(f"<th>{horizon}D</th>" for horizon in horizons)
    body = []
    for row in rows:
        values = {point["horizon"]: point["ic"] for point in decay.get(row["key"], [])}
        cells = "".join(f"<td>{_pct(values.get(horizon))}</td>" for horizon in horizons)
        body.append(f"<tr><th class=\"left\">{_esc(row['label'])}</th>{cells}</tr>")
    return (
        f'<div class="table-wrap"><table><thead><tr><th>因子</th>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _risk_table(risk: dict, labels: dict[str, str]) -> str:
    if not risk.get("ok"):
        return "<p class=\"empty\">风险模型样本不足</p>"
    body = []
    for row in risk.get("factors", []):
        body.append(
            "<tr>"
            f"<td class=\"left\">{_esc(labels.get(row['factor'], row['factor']))}</td>"
            f"<td>{_signed(row['exposure'], 3)}</td>"
            f"<td>{_pct(row['annual_return'])}</td>"
            f"<td>{_pct_plain(row['annual_vol'])}</td>"
            f"<td>{_num(row['sharpe'])}</td>"
            f"<td>{_num(row['tstat'])}</td>"
            f"<td>{_pct(row['risk_share'])}</td>"
            "</tr>"
        )
    specific_vol = risk.get("specific_vol", 0.0) or 0.0
    factor_vol = risk.get("factor_vol", 0.0) or 0.0
    total_var = factor_vol ** 2 + specific_vol ** 2
    specific_share = specific_vol ** 2 / total_var if total_var > 1e-15 else 0.0
    body.append(
        "<tr>"
        "<td class=\"left\">特质风险</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>"
        f"<td>{_pct(specific_share)}</td>"
        "</tr>"
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>因子</th><th>组合暴露</th><th>因子年化收益</th><th>因子年化波动</th>"
        "<th>因子 Sharpe</th><th>t 值</th><th>风险占比</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _stress_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td class=\"left\">{_esc(row['name'])}</td>"
            f"<td>{_pct(row['market'])}</td>"
            f"<td class=\"{'rise' if row['pnl'] >= 0 else 'fall'}\">{_pct(row['pnl'])}</td>"
            f"<td class=\"left muted\">{_esc(row['description'])}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>情景</th><th>市场冲击</th><th>组合损益</th><th>说明</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _hedge_table(hedge: dict) -> str:
    body = []
    for row in hedge.get("stress", []):
        body.append(
            "<tr>"
            f"<td>{_pct_plain(row['spot_shock'])}</td>"
            f"<td class=\"fall\">{_pct(row['unhedged_pct'])}</td>"
            f"<td class=\"{'rise' if row['hedged_pct'] >= 0 else 'fall'}\">{_pct(row['hedged_pct'])}</td>"
            f"<td>{_num(row['put_value'], 2)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>指数变动</th><th>未对冲组合</th><th>对冲后组合</th><th>看跌期权价值</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _greeks_matrix(hedge: dict) -> str:
    payload = hedge.get("greeks_matrix", {})
    vols = payload.get("vols", [])
    rows = payload.get("rows", [])
    if not vols or not rows:
        return "<p class=\"empty\">暂无数据</p>"
    head = "".join(f"<th>波动率 {vol * 100:.0f}%</th>" for vol in vols)
    body = []
    for row in rows:
        cells = []
        for value in row["values"]:
            magnitude = min(abs(value) / 0.30, 1.0)
            color = f"rgba(224,90,90,{0.06 + 0.45 * magnitude:.3f})" if value >= 0 else f"rgba(47,158,111,{0.06 + 0.45 * magnitude:.3f})"
            cells.append(f'<td style="background:{color}">{_pct(value)}</td>')
        body.append(f"<tr><th>{_pct(row['spot_shock'])}</th>{''.join(cells)}</tr>")
    return (
        f'<div class="table-wrap"><table><thead><tr><th>指数变动 / 波动率</th>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _holdings_table(rows: list[dict]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td class=\"left mono\">{_esc(row['symbol'])}</td>"
            f"<td>{_pct_plain(row['weight'])}</td>"
            f"<td class=\"left\">{_esc(row['industry'])}</td>"
            f"<td>{_num((row.get('market_cap') or 0) / 1e9, 2)}B</td>"
            f"<td>{_signed(row.get('score') or 0.0, 2)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>代码</th><th>权重</th><th>行业</th><th>市值</th><th>综合因子分</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def render(summary: dict) -> str:
    meta = summary["meta"]
    factors = summary["factors"]
    labels = {row["key"]: row["label"] for row in factors}
    best = max(factors, key=lambda row: row["icir"]) if factors else None
    adaptive = summary["backtest"]["adaptive"]["metrics"]
    equal = summary["backtest"]["equal"]["metrics"]
    long_short = summary["backtest"].get("long_short", {}).get("metrics", {})
    benchmark = summary["backtest"]["benchmark"]["metrics"]
    risk = summary.get("risk", {})
    hedge = summary.get("hedge", {})
    corr = summary["correlation"]
    before_matrix = corr.get("before", {}).get("matrix", [])
    after_matrix = corr.get("after", {}).get("matrix", [])
    keys = corr.get("after", {}).get("keys", [])
    latest_join = corr.get("latest_join", {})
    quantile = summary.get("quantile", {})
    quantile_summary = quantile.get("summary", {})
    q_labels = [name for name in ("Q1", "Q2", "Q3", "Q4", "Q5") if name in quantile_summary]
    q_values = [quantile_summary[name]["cagr"] for name in q_labels]
    if "Q5-Q1" in quantile_summary:
        q_labels.append("Q5-Q1")
        q_values.append(quantile_summary["Q5-Q1"]["cagr"])
    dates = summary["backtest"]["dates"]
    equity = summary["backtest"]["equity"]
    drawdown = summary["backtest"]["drawdown"]
    equity_chart = _line_chart(
        dates,
        {
            "ICIR 自适应": equity["adaptive"],
            "等权因子": equity["equal"],
            "纯因子多空": equity.get("long_short", equity["adaptive"]),
            "等权基准": equity["benchmark"],
        },
        {"ICIR 自适应": "#4f8cff", "等权因子": "#c9a227", "纯因子多空": "#b07cff", "等权基准": "#8a93a6"},
        percent=False,
    )
    drawdown_chart = _line_chart(
        dates,
        {"自适应组合回撤": drawdown["adaptive"], "纯因子多空回撤": drawdown.get("long_short", drawdown["adaptive"])},
        {"自适应组合回撤": "#2f9e6f", "纯因子多空回撤": "#b07cff"},
        height=210,
        zero_line=True,
    )
    ic_chart = _bar_chart([row["label"] for row in factors], [row["ic_mean"] for row in factors])
    quantile_chart = _bar_chart(q_labels, q_values) if q_labels else "<p class=\"empty\">暂无数据</p>"
    stress_rows = risk.get("stress", []) if risk.get("ok") else []
    truth_rows = summary.get("diagnostics", {}).get("truth_check", [])
    turnover = summary["backtest"]["adaptive"].get("turnover", [])
    turnover_subset = turnover[-min(len(turnover), 40):]
    turnover_values = [item["turnover"] for item in turnover_subset]
    turnover_chart = ""
    if turnover_subset:
        turnover_chart = _line_chart(
            [item["date"] for item in turnover_subset],
            {"单次换手率": turnover_values},
            {"单次换手率": "#c9a227"},
            height=190,
            zero_line=True,
        )
    best_text = (
        f"{best['label']}（IC {_pct(best['ic_mean'])}，ICIR {_num(best['icir'])}）"
        if best
        else "样本不足"
    )
    impact = adaptive["cagr"] - equal["cagr"]
    impact_text = f"自适应相对等权因子年化收益差 {_pct(impact)}" if factors else "无"
    hedge_text = (
        f"3 个月 10% 虚值保护性看跌期权成本约 {_pct_plain(hedge.get('cost_pct'))}，"
        f"对冲名义本金 {_pct_plain(hedge.get('hedge_notional_pct'))}"
        if hedge
        else "未启用"
    )
    factor_bars = "".join(
        f"<li><span>{_esc(row['label'])}</span><span>{_pct(row['ic_mean'])}</span></li>" for row in factors
    )
    data_start, data_end = meta["panel"]["start"], meta["panel"]["end"]
    hold_count = len(summary.get("holdings", []))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FactorLab 因子研究报告</title>
<style>
:root {{
  --bg: #0f1115;
  --panel: #171a21;
  --panel-2: #1d212a;
  --border: #2a303c;
  --text: #e6e8ee;
  --muted: #9aa3b2;
  --accent: #4f8cff;
  --gold: #c9a227;
  --rise: #e05a5a;
  --fall: #2f9e6f;
  --mono: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-size: 14px;
  line-height: 1.65;
  font-variant-numeric: tabular-nums;
}}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 36px 22px 80px; }}
header {{ border-bottom: 1px solid var(--border); padding-bottom: 22px; margin-bottom: 24px; }}
.eyebrow {{ color: var(--accent); font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }}
h1 {{ font-size: 34px; line-height: 1.2; margin: 8px 0 6px; letter-spacing: -0.02em; }}
.sub {{ color: var(--muted); max-width: 860px; }}
.badges {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
.badge {{ border: 1px solid var(--border); background: var(--panel); color: var(--muted); padding: 3px 9px; border-radius: 999px; font-size: 12px; }}
.badge.warn {{ border-color: #6b5520; color: #e8c56b; background: #211c10; }}
.notice {{ border-left: 3px solid var(--gold); background: #1c1911; padding: 12px 16px; margin: 20px 0 4px; color: #d9c89b; }}
.kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 22px 0 8px; }}
.kpi {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }}
.kpi .label {{ color: var(--muted); font-size: 12px; }}
.kpi .value {{ font-size: 24px; font-weight: 650; margin-top: 3px; }}
.kpi .note {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
.rise {{ color: var(--rise); }}
.fall {{ color: var(--fall); }}
.flat {{ color: var(--muted); }}
section {{ margin-top: 36px; }}
h2 {{ font-size: 21px; margin: 0 0 6px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
h3 {{ font-size: 16px; margin: 22px 0 8px; }}
p {{ margin: 8px 0; }}
.muted {{ color: var(--muted); }}
.small {{ font-size: 12px; }}
.grid2 {{ display: grid; grid-template-columns: 1.2fr .8fr; gap: 18px; }}
.card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
.card h3 {{ margin-top: 0; }}
.table-wrap {{ overflow-x: auto; margin: 10px 0; }}
table {{ border-collapse: collapse; width: 100%; min-width: 620px; background: var(--panel); }}
th, td {{ border-bottom: 1px solid var(--border); padding: 8px 10px; text-align: right; vertical-align: top; }}
th {{ color: var(--muted); font-weight: 600; font-size: 12px; background: var(--panel-2); }}
th.left, td.left {{ text-align: left; }}
tbody tr:hover {{ background: #1b1f27; }}
.heatmap td {{ text-align: center; font-family: var(--mono); }}
.heatmap th {{ text-align: center; }}
.mono {{ font-family: var(--mono); }}
.legend {{ display: flex; gap: 18px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin: 6px 0 2px; }}
.legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
.swatch {{ width: 16px; height: 3px; display: inline-block; border-radius: 2px; }}
.chart {{ width: 100%; height: auto; display: block; }}
.chart .grid {{ stroke: #262c37; stroke-width: 1; }}
.chart .frame {{ stroke: #343b49; stroke-width: 1; }}
.chart .zero {{ stroke: #4b5364; stroke-width: 1; stroke-dasharray: 4 4; }}
.chart .axis {{ fill: #8791a2; font-size: 11px; }}
.chart .axis.right {{ text-anchor: end; }}
.chart .axis.center {{ text-anchor: middle; }}
.chart .value {{ fill: #cfd5df; font-size: 11px; font-family: var(--mono); }}
.columns {{ columns: 2; column-gap: 26px; }}
.columns li {{ break-inside: avoid; margin-bottom: 6px; }}
ul {{ margin: 8px 0; padding-left: 20px; }}
li {{ margin: 4px 0; }}
.formula {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; font-family: var(--mono); font-size: 12.5px; color: #cfd6e2; overflow-x: auto; }}
.tag {{ display: inline-block; border: 1px solid var(--border); border-radius: 4px; padding: 0 6px; color: var(--muted); font-size: 11px; }}
.footer {{ margin-top: 42px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }}
.empty {{ color: var(--muted); padding: 12px 0; }}
@media (max-width: 860px) {{
  .kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .grid2 {{ grid-template-columns: 1fr; }}
  .columns {{ columns: 1; }}
  h1 {{ font-size: 27px; }}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">FactorLab / Cross-sectional Equity Research</div>
  <h1>多因子风险归因与正交化研究</h1>
  <div class="sub">从因子清洗、Barra 风格中性化、对称正交、IC 衰减，到自适应权重、组合回测、压力测试和保护性看跌期权对冲的完整闭环。</div>
  <div class="badges">
    <span class="badge">引擎 {_esc(meta['version'])}</span>
    <span class="badge">{_esc(data_start)} 至 {_esc(data_end)}</span>
    <span class="badge">{meta['panel']['symbols']} 只标的 / {meta['panel']['trading_days']} 个交易日</span>
    <span class="badge">{len(factors)} 个因子</span>
    <span class="badge">{_esc(meta['generated_at'])}</span>
    <span class="badge warn">合成数据，仅方法验证</span>
  </div>
</header>

<div class="notice"><strong>口径声明：</strong>{_esc(meta['disclaimer'])}本报告展示的是研究引擎在可复现合成市场上的计算结果，不是实盘业绩，也不能直接作为收益承诺。真实资金使用前必须接入带披露日、停牌、复权和交易成本的实盘数据重新验证。</div>

<div class="kpis">
  <div class="kpi"><div class="label">Long-only 年化</div><div class="value">{_pct(adaptive['cagr'])}</div><div class="note">Sharpe {_num(adaptive['sharpe'])} / 回撤 {_pct(adaptive['max_drawdown'])}</div></div>
  <div class="kpi"><div class="label">纯因子多空年化</div><div class="value">{_pct(long_short.get('cagr'))}</div><div class="note">Sharpe {_num(long_short.get('sharpe'))} / 总敞口 {_pct_plain(long_short.get('average_gross'))}</div></div>
  <div class="kpi"><div class="label">最强单因子</div><div class="value">{_esc(best['label']) if best else '—'}</div><div class="note">{_esc(best_text)}</div></div>
  <div class="kpi"><div class="label">尾部对冲成本</div><div class="value">{_pct_plain(hedge.get('cost_pct'))}</div><div class="note">损失上限 {_pct_plain(hedge.get('loss_cap', 0.10))} / 压力等效 Beta {_num(hedge.get('beta'))}</div></div>
</div>

<section>
  <h2>01 结论摘要</h2>
  <div class="grid2">
    <div>
      <ul>
        <li>因子池覆盖动量、短期反转、低波动、非流动性、小市值、价值和质量，全部按“分数越高、预期收益越高”统一方向。</li>
        <li>最强单因子为 {_esc(best_text)}；IC 胜率 {_pct_plain(best['hit_rate'], 1) if best else '—'}，半衰期 {_num(best['half_life'], 0) if best and best['half_life'] else '超过 60 日'}。</li>
        <li>{_esc(impact_text)}；纯因子多空组合年化 {_pct(long_short.get('cagr'))}、Sharpe {_num(long_short.get('sharpe'))}，用于展示剥离市场 Beta 后的因子收益序列。</li>
        <li>自适应权重使用过去 252 日 ICIR，并对权重做 50% 向等权收缩和 32% 单因子上限。</li>
        <li>市场波动进入过去一年 75% 分位以上时，临时提高低波动、质量权重，压低动量与非流动性权重；这是规则型风险开关，不是拟合出来的择时模型。</li>
        <li>{_esc(hedge_text)}。对冲只覆盖 Beta 暴露，不能消除因子拥挤、跳空和流动性折价。</li>
      </ul>
    </div>
    <div class="card">
      <h3>因子 IC 一览</h3>
      <ul style="list-style:none;padding:0;margin:0">{factor_bars}</ul>
      <p class="small muted">IC 为日度 Spearman 秩相关，使用 t 日因子分数与 t+1 日收益。合成市场中的数值用于验证管道，不代表真实市场可持续性。</p>
    </div>
  </div>
</section>

<section>
  <h2>02 数据与无未来函数约束</h2>
  <div class="grid2">
    <div class="card">
      <table>
        <tbody>
          <tr><th class="left">数据源</th><td class="left">{_esc(meta['panel']['source'])}</td></tr>
          <tr><th class="left">样本区间</th><td class="left">{_esc(data_start)} 至 {_esc(data_end)}</td></tr>
          <tr><th class="left">标的数量</th><td class="left">{meta['panel']['symbols']}</td></tr>
          <tr><th class="left">行业数量</th><td class="left">{len(meta['panel']['industries'])}</td></tr>
          <tr><th class="left">数据指纹</th><td class="left mono small">{_esc(meta['panel']['fingerprint'][:24])}…</td></tr>
          <tr><th class="left">复权口径</th><td class="left">合成价格已包含分红再投资假设；真实 CSV 必须使用复权价</td></tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <h3>约束</h3>
      <ul>
        <li>t 日收盘后计算信号，t+1 日开盘执行，收益从 t+1 日收盘开始计。</li>
        <li>财报只使用发布日在 t-1 及之前的记录，不使用报告期倒推。</li>
        <li>停牌、缺失收盘和零成交不参与选股；组合内缺失收益按 0 处理并保留现金。</li>
        <li>每次调仓计入 {_num(meta['config']['cost_bps'], 1)} bp 单边换手成本。</li>
      </ul>
    </div>
  </div>
</section>

<section>
  <h2>03 因子定义与 IC / IR</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th class="left">因子</th><th class="left">定义</th><th>最小历史</th></tr></thead>
      <tbody>
        {''.join(f"<tr><td class='left'>{_esc(row['label'])}</td><td class='left muted'>{_esc(row['description'])}</td><td>{row['min_history']} 日</td></tr>" for row in summary['factor_definitions'])}
      </tbody>
    </table>
  </div>
  <h3>IC 与显著性</h3>
  {_factor_table(factors)}
  <div class="grid2">
    <div><h3>IC 均值</h3>{ic_chart}</div>
    <div><h3>IC 衰减</h3>{_decay_table(factors, summary['decay'])}</div>
  </div>
  <p class="small muted">ICIR = IC 均值 / IC 标准差；t 值按日度 IC 序列计算。半衰期是第一个 IC 低于首日一半的持有期；未达到 60 日门槛时显示为超过 60 日。多周期 IC 使用重叠收益，长周期数值会放大自相关，不能把它当作独立样本的显著性。</p>
</section>

<section>
  <h2>04 中性化与对称正交</h2>
  <div class="grid2">
    <div class="card">
      <h3>处理流程</h3>
      <div class="formula">score → MAD 缩尾 → 截面 z-score → WLS(行业哑变量 + log 市值 + Beta) → 残差 z-score → Löwdin 对称正交 → 再标准化</div>
      <p class="small muted">WLS 权重为 sqrt(总市值)，避免超小市值股票主导截面回归。对称正交对因子顺序不敏感，比逐次 Gram-Schmidt 更适合并列展示。</p>
      <ul>
        <li>最大两两相关（正交前）：{_num(latest_join.get('max_offdiag_before'), 3)}</li>
        <li>最大两两相关（正交后）：{_num(latest_join.get('max_offdiag_after'), 3)}</li>
        <li>条件数（正交前 / 后）：{_num(latest_join.get('condition_before'), 2)} / {_num(latest_join.get('condition_after'), 2)}</li>
        <li>共同样本数：{_num(latest_join.get('n'), 0)}</li>
      </ul>
    </div>
    <div class="card">
      <h3>正交后相关矩阵</h3>
      {_heatmap(keys, after_matrix, labels)}
      <p class="small muted">理想结果为对角为 1、非对角接近 0。保留 5% 向单位阵收缩，避免极端共线性导致逆矩阵放大噪声。</p>
    </div>
  </div>
  <h3>正交前相关矩阵（用于诊断共线性）</h3>
  {_heatmap(corr.get('before', {}).get('keys', []), before_matrix, labels)}
</section>

<section>
  <h2>05 分层回测</h2>
  <p>按 {_esc(quantile.get('label') or '—')} 的截面分数分为五组，组内等权，每 21 个交易日重建组合。Q5 为因子分数最高组，Q5-Q1 为多空价差。</p>
  {quantile_chart}
  <div class="table-wrap">
    <table>
      <thead><tr><th>组合</th><th>年化收益</th><th>年化波动</th><th>Sharpe</th><th>最大回撤</th><th>日胜率</th></tr></thead>
      <tbody>
        {''.join(f"<tr><th class='left'>{_esc(name)}</th><td>{_pct(quantile_summary[name]['cagr'])}</td><td>{_pct_plain(quantile_summary[name]['annual_vol'])}</td><td>{_num(quantile_summary[name]['sharpe'])}</td><td>{_pct(quantile_summary[name]['max_drawdown'])}</td><td>{_pct_plain(quantile_summary[name]['hit_rate'], 1)}</td></tr>" for name in q_labels)}
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>06 组合回测</h2>
  <h3>净值曲线（起点 1.0）</h3>
  {equity_chart}
  <div class="card">
    <h3>关键指标</h3>
    {_metrics_table(summary['backtest'])}
    <p class="small muted">基准为全样本可交易股票的等权组合，按同一调仓频率重建，未做波动率目标。自适应与等权因子均使用 10% 年化波动目标，最高 100% 仓位；纯因子多空允许 1.2 倍总敞口。</p>
  </div>
  <div class="grid2">
    <div><h3>回撤</h3>{drawdown_chart}</div>
    <div><h3>最近调仓换手</h3>{turnover_chart if turnover_chart else '<p class="empty">暂无数据</p>'}</div>
  </div>
</section>

<section>
  <h2>07 风险归因</h2>
  <p>用 Fama-MacBeth 截面回归估计因子日收益，再以因子收益协方差矩阵和组合因子暴露做风险分解。组合 Beta 为持仓个股 Beta 的加权平均。</p>
  <div class="kpis">
    <div class="kpi"><div class="label">组合 Beta</div><div class="value">{_num(risk.get('beta'))}</div><div class="note">相对等权市场</div></div>
    <div class="kpi"><div class="label">预测总波动</div><div class="value">{_pct_plain(risk.get('total_vol'))}</div><div class="note">因子 + 特质</div></div>
    <div class="kpi"><div class="label">因子波动</div><div class="value">{_pct_plain(risk.get('factor_vol'))}</div><div class="note">共同因子部分</div></div>
    <div class="kpi"><div class="label">特质波动</div><div class="value">{_pct_plain(risk.get('specific_vol'))}</div><div class="note">残差分散化后</div></div>
  </div>
  {_risk_table(risk, labels)}
  <p class="small muted">风险占比可能为负，表示该因子暴露在当前协方差结构下对组合风险起到对冲作用。合成市场中的因子收益均值不代表真实溢价。</p>
</section>

<section>
  <h2>08 压力测试</h2>
  <p>情景冲击直接施加到组合 Beta 与标准化因子暴露上；最后一行是样本内最差 20 日市场窗口的实际因子收益重放。</p>
  {_stress_table(stress_rows)}
</section>

<section>
  <h2>09 尾部对冲与 Greeks</h2>
  <div class="grid2">
    <div class="card">
      <h3>保护性看跌期权</h3>
      <table>
        <tbody>
          <tr><th class="left">组合名义本金</th><td>{_num(hedge.get('portfolio_value'), 0)}</td></tr>
          <tr><th class="left">压力等效 Beta</th><td>{_num(hedge.get('beta'))}</td></tr>
          <tr><th class="left">期权期限</th><td>{_num((hedge.get('horizon_years') or 0) * 12, 1)} 个月</td></tr>
          <tr><th class="left">行权价</th><td>{_num(hedge.get('strike'), 2)}（虚值 {_pct_plain(hedge.get('otm') or 0, 0)}）</td></tr>
          <tr><th class="left">对冲名义本金</th><td>{_pct_plain(hedge.get('hedge_notional_pct'))}</td></tr>
          <tr><th class="left">期权成本</th><td>{_pct_plain(hedge.get('cost_pct'))}</td></tr>
          <tr><th class="left">损失上限</th><td>{_pct_plain(hedge.get('loss_cap') or 0, 0)}</td></tr>
          <tr><th class="left">Delta / Gamma</th><td>{_num(hedge.get('greeks', {}).get('delta'), 1)} / {_num(hedge.get('greeks', {}).get('gamma'), 3)}（美元名义）</td></tr>
          <tr><th class="left">Vega / Theta</th><td>{_num(hedge.get('greeks', {}).get('vega'), 1)} / {_num(hedge.get('greeks', {}).get('theta'), 1)}（每波动率点 / 每日）</td></tr>
        </tbody>
      </table>
    </div>
    <div class="card">
      <h3>对冲口径</h3>
      <ul>
        <li>以组合在最差压力情景中的损失换算“压力等效 Beta”，再按 3 个月 10% 虚值看跌期权定价。</li>
        <li>期权波动率取 18% 与组合预测波动的较大值，避免用低波动组合压低估期权成本。</li>
        <li>对冲覆盖市场 Beta 与压力情景，不覆盖因子拥挤、跳空和流动性折价。</li>
      </ul>
      <p class="small muted">损失上限按本金 {_pct_plain(hedge.get('loss_cap') or 0, 0)} 计算；实际执行还需考虑期权买卖价差、保证金和展期成本。</p>
    </div>
  </div>
  <h3>对冲前后损益</h3>
  {_hedge_table(hedge)}
  <h3>Greeks 敏感性矩阵（组合损益，含期权成本）</h3>
  {_greeks_matrix(hedge)}
</section>

<section>
  <h2>10 当前持仓</h2>
  <p>最近一次调仓的目标权重，共 {hold_count} 只；权重未按后续价格漂移调整。组合分数为自适应因子加权后的综合分。</p>
  {_holdings_table(summary.get('holdings', []))}
</section>

<section>
  <h2>11 合成数据回收检验</h2>
  <p>生成器保存了真实因子收益序列。下表计算估计因子收益与真实因子收益的相关系数，用于确认管道方向没有写反；这不是策略有效性证明。</p>
  <div class="table-wrap">
    <table>
      <thead><tr><th class="left">因子</th><th>估计与真实收益相关</th><th>样本数</th></tr></thead>
      <tbody>
        {''.join(f"<tr><td class='left'>{_esc(row['label'])}</td><td>{_num(row['correlation'], 3)}</td><td>{row['n']}</td></tr>" for row in truth_rows) or '<tr><td colspan="3" class="empty">暂无数据</td></tr>'}
      </tbody>
    </table>
  </div>
</section>

<section>
  <h2>12 局限与下一步</h2>
  <div class="columns small">
    <ul>
      <li>当前报告使用合成市场，因子溢价、波动和压力情景均由生成器设定，不能作为实盘证据。</li>
      <li>行业分类来自合成标签；真实数据需要 GICS 或中信行业历史成员表，不能用今天的行业归属回填过去。</li>
      <li>Barra 风险模型只包含行业、市值和 Beta；真实生产应加入国别、风格、非线性规模、残差波动和贝叶斯收缩。</li>
      <li>回测没有模拟涨跌停、融券约束、冲击成本和容量；期权对冲使用 Black-Scholes 理想假设。</li>
      <li>下一步接入美股 ETF/个股真实日线与财报披露日，加入 PIT 财务库、复权因子、退市样本和交易成本模型。</li>
      <li>组合优化将从“分层选股 + 波动率目标”升级为带行业偏离、单票上限、换手惩罚和因子暴露约束的凸优化。</li>
      <li>跨资产模块将用向量自回归和状态切换模型估计股、债、商品、利率之间的传导，而不是直接拼相关系数。</li>
    </ul>
  </div>
</section>

<section>
  <h2>13 复现</h2>
  <div class="formula">cd backend<br>python -m quant.cli demo --out ../reports/factorlab-demo --seed {meta['config']['seed']} --years {meta['config']['years']} --symbols {meta['config']['n_symbols']}</div>
  <p class="small muted">依赖仅 Python 标准库。`summary.json` 保存全部指标与序列，`factor_ic.csv`、`equity_curve.csv`、`holdings.csv`、`stress_tests.csv` 可直接用于复核。</p>
</section>

<div class="footer">
  FactorLab {_esc(meta['version'])} · 生成时间 {_esc(meta['generated_at'])} · 数据指纹 {_esc(meta['panel']['fingerprint'])}<br>
  本报告为研究方法与工程验证材料，不构成投资建议、收益承诺或任何形式的代客理财服务。
</div>
</div>
</body>
</html>"""

