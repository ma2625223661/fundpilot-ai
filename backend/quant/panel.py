"""Aligned daily panel used by the factor engine.

All series are symbol-major lists aligned to ``Panel.dates``. A missing close
or a zero volume marks a non-tradable day; nothing is silently filled with
zero. Fundamental records carry their publication date so a signal computed
on day t can only use reports published before t.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Fundamental:
    publish_date: str
    period: str
    roe: float | None = None
    earnings_yield: float | None = None
    book_to_price: float | None = None
    accruals: float | None = None


@dataclass
class Panel:
    dates: list[str]
    symbols: list[str]
    close: dict[str, list[float | None]]
    volume: dict[str, list[float | None]]
    market_cap: dict[str, list[float | None]]
    industry: dict[str, str]
    fundamentals: dict[str, list[Fundamental]] = field(default_factory=dict)
    regime: dict[str, str] = field(default_factory=dict)
    name: str = "panel"
    source: str = ""
    is_synthetic: bool = False
    _returns: dict[str, list[float | None]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.dates or not self.symbols:
            raise ValueError("panel needs at least one date and one symbol")
        if list(self.dates) != sorted(self.dates):
            raise ValueError("dates must be sorted ascending")
        if len(set(self.dates)) != len(self.dates):
            raise ValueError("duplicate dates")
        n = len(self.dates)
        for symbol in self.symbols:
            for label, series in (
                ("close", self.close),
                ("volume", self.volume),
                ("market_cap", self.market_cap),
            ):
                if symbol not in series:
                    raise ValueError(f"{label} missing symbol {symbol}")
                if len(series[symbol]) != n:
                    raise ValueError(f"{label} length mismatch for {symbol}")
        for symbol in self.symbols:
            records = self.fundamentals.get(symbol, [])
            self.fundamentals[symbol] = sorted(records, key=lambda item: item.publish_date)

    def index(self, day: str) -> int:
        return self.dates.index(day)

    def returns(self, symbol: str) -> list[float | None]:
        cached = self._returns.get(symbol)
        if cached is not None:
            return cached
        closes = self.close[symbol]
        out: list[float | None] = [None] * len(closes)
        for i in range(1, len(closes)):
            previous = closes[i - 1]
            current = closes[i]
            if previous and current and previous > 0:
                out[i] = current / previous - 1.0
        self._returns[symbol] = out
        return out

    def return_at(self, symbol: str, t: int) -> float | None:
        values = self.returns(symbol)
        return values[t] if 0 <= t < len(values) else None

    def fundamental_asof(self, symbol: str, t: int, lag_days: int = 1) -> Fundamental | None:
        """Latest report published at least ``lag_days`` trading days ago."""
        if t - lag_days < 0:
            return None
        cutoff = self.dates[t - lag_days]
        records = self.fundamentals.get(symbol, [])
        if not records:
            return None
        positions = [item.publish_date for item in records]
        idx = bisect.bisect_right(positions, cutoff) - 1
        return records[idx] if idx >= 0 else None

    def eligible(
        self,
        t: int,
        min_history: int = 120,
        min_price: float = 1.0,
        min_volume: float = 0.0,
    ) -> list[str]:
        """Tradable universe on date t, using only information known that day."""
        if t < 1 or t >= len(self.dates):
            return []
        start = max(0, t - max(min_history, 1) + 1)
        out = []
        for symbol in self.symbols:
            closes = self.close[symbol]
            current = closes[t]
            previous = closes[t - 1]
            volume = self.volume[symbol][t]
            cap = self.market_cap[symbol][t]
            if current is None or previous is None or volume is None or cap is None:
                continue
            if current < min_price or volume <= min_volume or cap <= 0:
                continue
            valid = sum(1 for i in range(start, t + 1) if closes[i] is not None)
            required = int(max(min_history, 2) * 0.9)
            if valid < required:
                continue
            out.append(symbol)
        return out

    def market_return(self, t: int, universe: Iterable[str] | None = None) -> float | None:
        names = list(universe) if universe is not None else self.symbols
        values = []
        for symbol in names:
            value = self.return_at(symbol, t)
            if value is not None:
                values.append(value)
        return sum(values) / len(values) if values else None

    def dollar_volume(self, symbol: str, t: int) -> float | None:
        price = self.close[symbol][t]
        volume = self.volume[symbol][t]
        if price is None or volume is None:
            return None
        value = price * volume
        return value if value > 0 else None

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.name.encode("utf-8"))
        digest.update(",".join(self.dates).encode("utf-8"))
        digest.update(",".join(self.symbols).encode("utf-8"))
        for symbol in self.symbols:
            for value in self.close[symbol]:
                digest.update(("" if value is None else f"{value:.6f}").encode("ascii"))
                digest.update(b"|")
        return digest.hexdigest()

    def describe(self) -> dict:
        first = self.dates[0]
        last = self.dates[-1]
        return {
            "name": self.name,
            "source": self.source,
            "is_synthetic": self.is_synthetic,
            "start": first,
            "end": last,
            "trading_days": len(self.dates),
            "symbols": len(self.symbols),
            "industries": sorted(set(self.industry.values())),
            "fingerprint": self.fingerprint(),
        }


def finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def write_panel_json(panel: Panel, path) -> None:
    payload = {
        "meta": panel.describe(),
        "dates": panel.dates,
        "symbols": panel.symbols,
        "industry": panel.industry,
        "close": {key: panel.close[key] for key in panel.symbols},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))

