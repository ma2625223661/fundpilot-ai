"""Black-Scholes pricing, Greeks and a protective-put sizing overlay."""
from __future__ import annotations

import math


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes(
    spot: float,
    strike: float,
    years: float,
    rate: float,
    vol: float,
    kind: str = "put",
) -> dict:
    if spot <= 0 or strike <= 0 or years <= 0:
        raise ValueError("spot, strike and maturity must be positive")
    vol = max(vol, 1e-6)
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    discount = math.exp(-rate * years)
    if kind == "call":
        price = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (
            -spot * _norm_pdf(d1) * vol / (2.0 * sqrt_t)
            - rate * strike * discount * _norm_cdf(d2)
        )
    else:
        price = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (
            -spot * _norm_pdf(d1) * vol / (2.0 * sqrt_t)
            + rate * strike * discount * _norm_cdf(-d2)
        )
    gamma = _norm_pdf(d1) / (spot * vol * sqrt_t)
    vega = spot * _norm_pdf(d1) * sqrt_t
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "vega": vega / 100.0,
        "theta": theta / 252.0,
        "d1": d1,
        "d2": d2,
        "intrinsic": max(strike - spot, 0.0) if kind == "put" else max(spot - strike, 0.0),
    }


def put_price(spot: float, strike: float, years: float, rate: float, vol: float) -> float:
    return black_scholes(spot, strike, years, rate, vol, "put")["price"]


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    kind: str = "put",
    low: float = 1e-4,
    high: float = 5.0,
) -> float | None:
    intrinsic = max(strike - spot, 0.0) if kind == "put" else max(spot - strike, 0.0)
    if price < intrinsic - 1e-8 or price <= 0:
        return None
    for _ in range(100):
        mid = 0.5 * (low + high)
        value = black_scholes(spot, strike, years, rate, mid, kind)["price"]
        if abs(value - price) < 1e-8:
            return mid
        if value > price:
            high = mid
        else:
            low = mid
    return 0.5 * (low + high)


def protective_put_overlay(
    portfolio_value: float,
    beta: float,
    spot: float = 100.0,
    horizon_years: float = 0.25,
    rate: float = 0.04,
    vol: float = 0.20,
    otm: float = 0.10,
    loss_cap: float = 0.10,
    stress_move: float = -0.20,
) -> dict:
    """Size a put position to cap a beta-adjusted loss at ``loss_cap``.

    The hedge is applied to the portfolio's equity beta, not to its full
    notional, and the option is priced on a normalised index level of 100.
    """
    strike = spot * (1.0 - otm)
    option = black_scholes(spot, strike, horizon_years, rate, vol, "put")
    payoff_per_notional = max(-otm - stress_move, 0.0)
    required_loss = max(beta * abs(stress_move) - loss_cap, 0.0) * portfolio_value
    hedge_notional = required_loss / payoff_per_notional if payoff_per_notional > 0 else 0.0
    hedge_notional = min(hedge_notional, 1.5 * portfolio_value)
    cost = hedge_notional * option["price"] / spot
    shocks = (-0.30, -0.20, -0.10, 0.0, 0.10)
    vols = (0.15, 0.20, 0.25, 0.30)
    stress = []
    for shock in shocks:
        new_spot = spot * (1.0 + shock)
        revalued = black_scholes(new_spot, strike, horizon_years, rate, vol, "put")["price"]
        unhedged = beta * shock * portfolio_value
        hedged = unhedged + hedge_notional * (revalued - option["price"]) / spot - cost
        stress.append(
            {
                "spot_shock": shock,
                "unhedged_pct": unhedged / portfolio_value,
                "hedged_pct": hedged / portfolio_value,
                "put_value": revalued,
            }
        )
    matrix = []
    for shock in shocks:
        new_spot = spot * (1.0 + shock)
        row = []
        for scenario_vol in vols:
            revalued = black_scholes(new_spot, strike, horizon_years, rate, scenario_vol, "put")["price"]
            hedged = (
                beta * shock * portfolio_value
                + hedge_notional * (revalued - option["price"]) / spot
                - cost
            )
            row.append(hedged / portfolio_value)
        matrix.append({"spot_shock": shock, "values": row})
    return {
        "spot": spot,
        "strike": strike,
        "vol": vol,
        "otm": otm,
        "horizon_years": horizon_years,
        "loss_cap": loss_cap,
        "stress_move": stress_move,
        "portfolio_value": portfolio_value,
        "beta": beta,
        "hedge_notional": hedge_notional,
        "hedge_notional_pct": hedge_notional / portfolio_value if portfolio_value else 0.0,
        "put_price": option["price"],
        "put_price_pct": option["price"] / spot,
        "cost": cost,
        "cost_pct": cost / portfolio_value if portfolio_value else 0.0,
        "greeks": {
            "delta": option["delta"] * hedge_notional,
            "gamma": option["gamma"] * hedge_notional,
            "vega": option["vega"] * hedge_notional,
            "theta": option["theta"] * hedge_notional,
        },
        "stress": stress,
        "greeks_matrix": {
            "vols": list(vols),
            "rows": matrix,
        },
    }

