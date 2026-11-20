"""Command line entry point for FactorLab."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .csv_loader import load_panel
from .pipeline import RunConfig, run

ROOT = Path(__file__).resolve().parents[2]


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", default=str(ROOT / "reports" / "factorlab-demo"))
    parser.add_argument("--target-vol", type=float, default=0.10)
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--rebalance", type=int, default=21)
    parser.add_argument("--top-fraction", type=float, default=0.20)
    parser.add_argument("--portfolio-value", type=float, default=1_000_000.0)
    parser.add_argument("--quiet", action="store_true")


def _print_result(result: dict) -> None:
    summary = result["summary"]
    metrics = summary["backtest"]["adaptive"]["metrics"]
    print("")
    print(f"report      {Path(result['out_dir']).resolve() / 'index.html'}")
    print(f"summary     {Path(result['out_dir']).resolve() / 'summary.json'}")
    print(f"data        {summary['meta']['panel']['start']} .. {summary['meta']['panel']['end']}")
    print(f"CAGR        {metrics['cagr'] * 100:+.2f}%")
    print(f"Sharpe      {metrics['sharpe']:.2f}")
    print(f"max drawdown{metrics['max_drawdown'] * 100:+.2f}%")
    print(f"turnover    {metrics['annual_turnover'] * 100:.2f}% / year")
    print(f"factors     {', '.join(row['label'] for row in summary['factors'])}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m quant.cli", description="FactorLab research engine")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the reproducible synthetic research demo")
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--years", type=int, default=6)
    demo.add_argument("--symbols", type=int, default=80)
    demo.add_argument("--start", default="2020-01-02")
    _common(demo)

    csv_parser = sub.add_parser("csv", help="run on a real CSV panel")
    csv_parser.add_argument("--prices", required=True)
    csv_parser.add_argument("--fundamentals", default=None)
    _common(csv_parser)

    args = parser.parse_args(argv)
    if args.command == "demo":
        config = RunConfig(
            seed=args.seed,
            years=args.years,
            n_symbols=args.symbols,
            start=args.start,
            target_vol=args.target_vol,
            cost_bps=args.cost_bps,
            rebalance=args.rebalance,
            top_fraction=args.top_fraction,
            portfolio_value=args.portfolio_value,
            out_dir=args.out,
            label="FactorLab synthetic demo",
            verbose=not args.quiet,
        )
        result = run(config)
    else:
        panel = load_panel(args.prices, args.fundamentals)
        config = RunConfig(
            start=panel.dates[0],
            target_vol=args.target_vol,
            cost_bps=args.cost_bps,
            rebalance=args.rebalance,
            top_fraction=args.top_fraction,
            portfolio_value=args.portfolio_value,
            out_dir=args.out,
            label=f"FactorLab CSV {Path(args.prices).name}",
            verbose=not args.quiet,
        )
        result = run(config, panel=panel)
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

