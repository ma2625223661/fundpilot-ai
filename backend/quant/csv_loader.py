"""CSV ingestion for real research panels.

prices.csv columns:
    date,symbol,close,volume,market_cap,industry

fundamentals.csv columns (optional but required for value/quality):
    symbol,publish_date,period,roe,earnings_yield,book_to_price,accruals

``close`` must be split/dividend adjusted. ``publish_date`` must be the date
the report became public, not the fiscal period end. Missing values stay
missing; the loader does not forward-fill prices or fundamentals.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .panel import Fundamental, Panel


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return float(text)


def load_prices(path: str | Path) -> dict:
    rows = defaultdict(dict)
    industries = {}
    dates = set()
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "symbol", "close", "volume", "market_cap"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"prices.csv missing columns: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            symbol = (row.get("symbol") or "").strip()
            day = (row.get("date") or "").strip()
            if not symbol or not day:
                raise ValueError(f"prices.csv line {line}: empty symbol or date")
            close = _float(row.get("close"))
            volume = _float(row.get("volume"))
            cap = _float(row.get("market_cap"))
            if close is not None and close <= 0:
                close = None
            if volume is not None and volume < 0:
                volume = None
            if cap is not None and cap <= 0:
                cap = None
            rows[symbol][day] = (close, volume, cap)
            dates.add(day)
            industry = (row.get("industry") or "").strip()
            if industry:
                industries[symbol] = industry
    dates = sorted(dates)
    symbols = sorted(rows)
    if not dates or not symbols:
        raise ValueError("prices.csv has no usable rows")
    close, volume, market_cap = {}, {}, {}
    for symbol in symbols:
        close[symbol] = [rows[symbol].get(day, (None, None, None))[0] for day in dates]
        volume[symbol] = [rows[symbol].get(day, (None, None, None))[1] for day in dates]
        market_cap[symbol] = [rows[symbol].get(day, (None, None, None))[2] for day in dates]
    return {
        "dates": dates,
        "symbols": symbols,
        "close": close,
        "volume": volume,
        "market_cap": market_cap,
        "industry": {symbol: industries.get(symbol, "Unknown") for symbol in symbols},
    }


def load_fundamentals(path: str | Path) -> dict[str, list[Fundamental]]:
    out: dict[str, list[Fundamental]] = defaultdict(list)
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "publish_date", "period"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"fundamentals.csv missing columns: {', '.join(sorted(missing))}")
        for line, row in enumerate(reader, start=2):
            symbol = (row.get("symbol") or "").strip()
            publish = (row.get("publish_date") or "").strip()
            period = (row.get("period") or "").strip()
            if not symbol or not publish:
                raise ValueError(f"fundamentals.csv line {line}: empty symbol or publish_date")
            out[symbol].append(
                Fundamental(
                    publish_date=publish,
                    period=period,
                    roe=_float(row.get("roe")),
                    earnings_yield=_float(row.get("earnings_yield")),
                    book_to_price=_float(row.get("book_to_price")),
                    accruals=_float(row.get("accruals")),
                )
            )
    return dict(out)


def load_panel(prices_path: str | Path, fundamentals_path: str | Path | None = None) -> Panel:
    payload = load_prices(prices_path)
    fundamentals = load_fundamentals(fundamentals_path) if fundamentals_path else {}
    return Panel(
        dates=payload["dates"],
        symbols=payload["symbols"],
        close=payload["close"],
        volume=payload["volume"],
        market_cap=payload["market_cap"],
        industry=payload["industry"],
        fundamentals=fundamentals,
        name=f"csv:{Path(prices_path).name}",
        source=f"csv:{Path(prices_path).resolve()}",
        is_synthetic=False,
    )

