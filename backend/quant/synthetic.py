"""Reproducible synthetic US-equity panel with a known factor structure.

This is a laboratory dataset, not market data. It exists so the whole research
pipeline can be run and tested without a paid data feed. Factor premia switch
with a two-state market regime, idiosyncratic returns have jumps, and a few
short trading halts exercise the missing-data path.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from .panel import Fundamental, Panel

STYLE_FACTORS = ("momentum", "value", "quality", "low_vol", "size", "illiquidity", "reversal")
PREMIUM_SCALE = 0.75
VOL_SCALE = 1.15
SECTORS = (
    "Technology",
    "Health Care",
    "Financials",
    "Consumer",
    "Industrials",
    "Energy",
    "Utilities",
    "Materials",
)


@dataclass(frozen=True)
class SyntheticConfig:
    seed: int = 42
    years: int = 6
    n_symbols: int = 80
    start: str = "2020-01-02"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def _holidays(year: int) -> set[date]:
    days = {
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
    }
    for month, day in ((1, 1), (6, 19), (7, 4), (12, 25)):
        value = date(year, month, day)
        if value.weekday() == 5:
            value -= timedelta(days=1)
        elif value.weekday() == 6:
            value += timedelta(days=1)
        days.add(value)
    return days


def us_trading_days(start: str, years: int) -> list[str]:
    current = date.fromisoformat(start)
    end = date(current.year + years, current.month, current.day) - timedelta(days=1)
    holidays = set()
    for year in range(current.year, end.year + 1):
        holidays.update(_holidays(year))
    out = []
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            out.append(current.isoformat())
        current += timedelta(days=1)
    return out


def _stress_window(day: str) -> bool:
    if "2020-02-24" <= day <= "2020-04-03":
        return True
    if "2022-05-18" <= day <= "2022-06-24":
        return True
    if "2024-07-24" <= day <= "2024-08-09":
        return True
    return False


def _quarter_ends(dates: list[str]) -> list[tuple[str, str]]:
    seen = set()
    out = []
    for day in dates:
        year, month, _ = day.split("-")
        quarter = (int(month) - 1) // 3 + 1
        key = f"{year}Q{quarter}"
        if key not in seen:
            seen.add(key)
            out.append((day, key))
    return out


def _publish_date(period_end: str, days: int = 35) -> str:
    return (date.fromisoformat(period_end) + timedelta(days=days)).isoformat()


def generate_dataset(config: SyntheticConfig | None = None) -> tuple[Panel, dict]:
    config = config or SyntheticConfig()
    rng = random.Random(config.seed)
    dates = us_trading_days(config.start, config.years)
    n_days = len(dates)
    symbols = [f"S{index:03d}" for index in range(1, config.n_symbols + 1)]
    industries = [SECTORS[(index - 1) % len(SECTORS)] for index in range(1, config.n_symbols + 1)]
    industry_of = dict(zip(symbols, industries))

    exposures: dict[str, dict[str, float]] = {}
    betas: dict[str, float] = {}
    log_caps: dict[str, float] = {}
    shares: dict[str, float] = {}
    for index, symbol in enumerate(symbols):
        value_exp = rng.gauss(0.0, 1.0)
        quality_exp = -0.2 * value_exp + rng.gauss(0.0, 0.95)
        size_exp = rng.gauss(0.0, 1.0)
        vol_exp = rng.gauss(0.0, 1.0)
        illiq_exp = 0.55 * size_exp + rng.gauss(0.0, 0.8)
        momentum_exp = rng.gauss(0.0, 1.0)
        reversal_exp = rng.gauss(0.0, 1.0)
        sector_tilt = (SECTORS.index(industries[index]) - 3.5) * 0.08
        exposures[symbol] = {
            "value": value_exp + sector_tilt,
            "quality": quality_exp,
            "momentum": momentum_exp,
            "low_vol": vol_exp,
            "size": size_exp,
            "illiquidity": illiq_exp,
            "reversal": reversal_exp,
        }
        betas[symbol] = max(0.35, 1.0 - 0.28 * vol_exp + rng.gauss(0.0, 0.12))
        log_caps[symbol] = rng.uniform(20.8, 25.6) - 0.55 * size_exp
        shares[symbol] = 10 ** rng.uniform(7.3, 9.3)

    regime: dict[str, str] = {}
    factor_returns: dict[str, list[float]] = {key: [] for key in ("market",) + STYLE_FACTORS}
    industry_returns: dict[str, list[float]] = {sector: [] for sector in SECTORS}
    market_returns: list[float] = []
    current = "calm"
    for index, day in enumerate(dates):
        if _stress_window(day):
            current = "stress"
        elif current == "stress":
            if rng.random() < 0.045:
                current = "calm"
        else:
            if rng.random() < 0.0035:
                current = "stress"
        regime[day] = current
        if current == "stress":
            market_mean, market_vol = -0.0022, 0.027
            premia = {
                "momentum": -0.0021,
                "value": 0.00020,
                "quality": 0.00018,
                "low_vol": 0.00090,
                "size": -0.00050,
                "illiquidity": -0.00135,
                "reversal": 0.00025,
            }
            vols = {
                "momentum": 0.0095,
                "value": 0.0065,
                "quality": 0.0055,
                "low_vol": 0.0075,
                "size": 0.0090,
                "illiquidity": 0.0095,
                "reversal": 0.0080,
            }
        else:
            market_mean, market_vol = 0.00038, 0.0088
            premia = {
                "momentum": 0.00034,
                "value": 0.00020,
                "quality": 0.00022,
                "low_vol": 0.00035,
                "size": 0.00028,
                "illiquidity": 0.00022,
                "reversal": 0.00026,
            }
            vols = {
                "momentum": 0.0042,
                "value": 0.0034,
                "quality": 0.0031,
                "low_vol": 0.0030,
                "size": 0.0038,
                "illiquidity": 0.0041,
                "reversal": 0.0045,
            }
        market = market_mean + market_vol * rng.gauss(0.0, 1.0)
        if rng.random() < 0.0025:
            market += rng.choice((-1.0, 1.0)) * rng.uniform(0.02, 0.06)
        market_returns.append(market)
        factor_returns["market"].append(market)
        for key in STYLE_FACTORS:
            shock = rng.gauss(0.0, 1.0)
            if rng.random() < 0.004:
                shock *= 2.8
            factor_returns[key].append(premia[key] * PREMIUM_SCALE + vols[key] * VOL_SCALE * shock)
        for sector in SECTORS:
            industry_returns[sector].append(rng.gauss(0.0, 0.0026))

    returns: dict[str, list[float | None]] = {symbol: [None] * n_days for symbol in symbols}
    close: dict[str, list[float | None]] = {symbol: [None] * n_days for symbol in symbols}
    volume: dict[str, list[float | None]] = {symbol: [0.0] * n_days for symbol in symbols}
    market_cap: dict[str, list[float | None]] = {symbol: [None] * n_days for symbol in symbols}

    state = {}
    for symbol in symbols:
        log_cap = log_caps[symbol]
        state[symbol] = {
            "log_cap": log_cap,
            "price": max(4.0, min(600.0, math.exp(log_cap) / shares[symbol])),
            "recent": [],
            "halted": set(),
            "price_by_index": [None] * n_days,
        }
    return_factors = tuple(key for key in STYLE_FACTORS if key != "size")
    for index, day in enumerate(dates):
        mean_log_cap = sum(item["log_cap"] for item in state.values()) / len(state)
        for symbol in symbols:
            item = state[symbol]
            log_cap = item["log_cap"]
            price = item["price"]
            recent = item["recent"]
            halted = item["halted"]
            price_by_index = item["price_by_index"]
            if index > 320 and symbol in ("S012", "S031", "S057") and rng.random() < 0.004:
                for offset in range(rng.randint(3, 7)):
                    if index + offset < n_days:
                        halted.add(index + offset)
            if index in halted:
                market_cap[symbol][index] = math.exp(log_cap)
                volume[symbol][index] = 0.0
                continue
            style_part = sum(exposures[symbol][key] * factor_returns[key][index] for key in return_factors)
            size_part = (0.00014 if regime[day] == "calm" else -0.00027) * (-(log_cap - mean_log_cap))
            industry_part = industry_returns[industry_of[symbol]][index]
            idio_scale = max(0.007, min(0.016, 0.0115 - 0.0035 * exposures[symbol]["low_vol"]))
            idio = rng.gauss(0.0, idio_scale)
            if rng.random() < 0.006:
                idio += rng.choice((-1.0, 1.0)) * rng.uniform(0.025, 0.075)
            reversal_part = 0.0
            if len(recent) >= 5:
                past = math.prod(1.0 + value for value in recent[-5:]) - 1.0
                reversal_part = -0.028 * past
            momentum_part = 0.0
            if index >= 252 and price_by_index[index - 252] and price_by_index[index - 21]:
                past_year = price_by_index[index - 21] / price_by_index[index - 252] - 1.0
                past_year = max(-0.55, min(0.55, past_year))
                momentum_part = (0.0008 if regime[day] == "calm" else -0.00055) * past_year
            daily = (
                betas[symbol] * market_returns[index]
                + style_part
                + size_part
                + industry_part
                + reversal_part
                + momentum_part
                + idio
            )
            daily = max(-0.19, min(0.19, daily))
            price = max(1.5, price * (1.0 + daily))
            returns[symbol][index] = daily
            recent.append(daily)
            if len(recent) > 30:
                recent.pop(0)
            log_cap += daily + rng.gauss(0.0, 0.0015)
            item["log_cap"] = log_cap
            item["price"] = price
            cap = math.exp(log_cap)
            turnover = 0.0045 * math.exp(-0.35 * exposures[symbol]["illiquidity"] + rng.gauss(0.0, 0.28))
            turnover = max(0.0004, min(0.04, turnover))
            dollar_volume = cap * turnover
            close[symbol][index] = round(price, 4)
            market_cap[symbol][index] = cap
            volume[symbol][index] = max(1.0, dollar_volume / price)
            price_by_index[index] = price

    fundamentals: dict[str, list[Fundamental]] = {symbol: [] for symbol in symbols}
    for period_end, period in _quarter_ends(dates):
        published = _publish_date(period_end)
        if published > dates[-1]:
            continue
        for symbol in symbols:
            value_noise = rng.gauss(0.0, 0.010)
            quality_noise = rng.gauss(0.0, 0.028)
            ep = max(-0.06, min(0.18, 0.045 + 0.028 * exposures[symbol]["value"] + value_noise))
            bp = max(0.03, min(1.6, 0.34 + 0.17 * exposures[symbol]["value"] + rng.gauss(0.0, 0.055)))
            roe = max(-0.30, min(0.55, 0.115 + 0.055 * exposures[symbol]["quality"] + quality_noise))
            accruals = rng.gauss(0.0, 0.025) - 0.012 * exposures[symbol]["quality"]
            fundamentals[symbol].append(
                Fundamental(
                    publish_date=published,
                    period=period,
                    roe=roe,
                    earnings_yield=ep,
                    book_to_price=bp,
                    accruals=accruals,
                )
            )

    panel = Panel(
        dates=dates,
        symbols=symbols,
        close=close,
        volume=volume,
        market_cap=market_cap,
        industry=industry_of,
        fundamentals=fundamentals,
        regime=regime,
        name=f"synthetic-us-equity-{config.n_symbols}x{config.years}y",
        source=f"FactorLab synthetic generator seed={config.seed}",
        is_synthetic=True,
    )
    truth = {
        "config": {
            "seed": config.seed,
            "years": config.years,
            "n_symbols": config.n_symbols,
            "start": config.start,
        },
        "factor_returns": dict(zip(dates, zip(*(factor_returns[key] for key in ("market",) + STYLE_FACTORS)))),
        "factor_series": factor_returns,
        "exposures": exposures,
        "betas": betas,
    }
    return panel, truth


def generate_panel(config: SyntheticConfig | None = None) -> Panel:
    return generate_dataset(config)[0]

