#!/usr/bin/env python3
"""bot/derivatives.py - options, forwards and currency arithmetic.

  black_scholes / greeks   European options on a dividend-paying underlying
                           (Black-Scholes-Merton), with delta, gamma, vega,
                           theta and rho
  implied_vol              the volatility a market price implies (bisection)
  binomial                 Cox-Ross-Rubinstein tree, European or American
  put_call_parity          the missing leg of a call/put pair
  forward_price            cost-of-carry forward on a stock or commodity
  fx_forward               covered interest parity: the forward rate that the
                           two currencies' interest rates imply
  cross_rate               a pair derived through the dollar

Units: rates, volatilities and yields are percentages, time is in years. FX
quotes are units of the domestic (quote) currency per one unit of the foreign
(base) currency - USD/KES 129 means 129 shillings per dollar.

Vega and rho are reported per one percentage point, theta per year and per
calendar day, which is how a desk reads them.
"""
import math


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _kind(kind):
    k = str(kind).lower()
    if k not in ("call", "put"):
        raise ValueError("kind must be call or put")
    return k


def _d(spot, strike, years, r, s, q):
    if spot <= 0 or strike <= 0 or years <= 0 or s <= 0:
        raise ValueError("spot, strike, time and volatility must all be positive")
    v = s * math.sqrt(years)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * s * s) * years) / v
    return d1, d1 - v


def black_scholes(spot, strike, years, rate_pct, vol_pct, dividend_yield_pct=0.0, kind="call"):
    k = _kind(kind)
    r, s, q = rate_pct / 100.0, vol_pct / 100.0, dividend_yield_pct / 100.0
    d1, d2 = _d(spot, strike, years, r, s, q)
    dq, dr = math.exp(-q * years), math.exp(-r * years)
    if k == "call":
        return spot * dq * norm_cdf(d1) - strike * dr * norm_cdf(d2)
    return strike * dr * norm_cdf(-d2) - spot * dq * norm_cdf(-d1)


def greeks(spot, strike, years, rate_pct, vol_pct, dividend_yield_pct=0.0, kind="call"):
    k = _kind(kind)
    r, s, q = rate_pct / 100.0, vol_pct / 100.0, dividend_yield_pct / 100.0
    d1, d2 = _d(spot, strike, years, r, s, q)
    dq, dr = math.exp(-q * years), math.exp(-r * years)
    pdf = norm_pdf(d1)
    common_theta = -spot * dq * pdf * s / (2 * math.sqrt(years))
    if k == "call":
        delta = dq * norm_cdf(d1)
        theta = common_theta - r * strike * dr * norm_cdf(d2) + q * spot * dq * norm_cdf(d1)
        rho = strike * years * dr * norm_cdf(d2)
    else:
        delta = dq * (norm_cdf(d1) - 1)
        theta = common_theta + r * strike * dr * norm_cdf(-d2) - q * spot * dq * norm_cdf(-d1)
        rho = -strike * years * dr * norm_cdf(-d2)
    return {"price": black_scholes(spot, strike, years, rate_pct, vol_pct,
                                   dividend_yield_pct, k),
            "d1": d1, "d2": d2, "delta": delta,
            "gamma": dq * pdf / (spot * s * math.sqrt(years)),
            "vegaPerPoint": spot * dq * pdf * math.sqrt(years) / 100.0,
            "thetaPerYear": theta, "thetaPerDay": theta / 365.0,
            "rhoPerPoint": rho / 100.0}


def implied_vol(price, spot, strike, years, rate_pct, dividend_yield_pct=0.0, kind="call"):
    """Volatility % that reproduces a market price. Price rises with volatility."""
    k = _kind(kind)
    lo, hi = 0.01, 500.0
    p_lo = black_scholes(spot, strike, years, rate_pct, lo, dividend_yield_pct, k)
    p_hi = black_scholes(spot, strike, years, rate_pct, hi, dividend_yield_pct, k)
    if not p_lo <= price <= p_hi:
        raise ValueError("price %.4f is outside what any volatility can produce "
                         "(%.4f to %.4f); check it against intrinsic value" % (price, p_lo, p_hi))
    for _ in range(200):
        mid = (lo + hi) / 2
        if black_scholes(spot, strike, years, rate_pct, mid, dividend_yield_pct, k) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2


def binomial(spot, strike, years, rate_pct, vol_pct, dividend_yield_pct=0.0, steps=200,
             kind="call", american=False):
    k = _kind(kind)
    steps = int(steps)
    if steps < 1 or years <= 0 or vol_pct <= 0:
        raise ValueError("needs at least one step, positive time and volatility")
    r, s, q = rate_pct / 100.0, vol_pct / 100.0, dividend_yield_pct / 100.0
    dt_ = years / steps
    u = math.exp(s * math.sqrt(dt_))
    d = 1 / u
    p = (math.exp((r - q) * dt_) - d) / (u - d)
    if not 0 < p < 1:
        raise ValueError("risk-neutral probability %.3f is outside (0, 1); add steps" % p)
    disc = math.exp(-r * dt_)
    sign = 1 if k == "call" else -1
    values = [max(0.0, sign * (spot * u ** j * d ** (steps - j) - strike))
              for j in range(steps + 1)]
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            cont = disc * (p * values[j + 1] + (1 - p) * values[j])
            if american:
                cont = max(cont, sign * (spot * u ** j * d ** (i - j) - strike))
            values[j] = cont
    return values[0]


def put_call_parity(spot, strike, years, rate_pct, dividend_yield_pct=0.0, call=None, put=None):
    """C - P = S e^(-qT) - K e^(-rT). Give one leg, get the other."""
    carry = (spot * math.exp(-dividend_yield_pct / 100.0 * years)
             - strike * math.exp(-rate_pct / 100.0 * years))
    if call is not None and put is None:
        return {"put": call - carry}
    if put is not None and call is None:
        return {"call": put + carry}
    if call is not None and put is not None:
        return {"parityGap": (call - put) - carry}
    raise ValueError("give call or put")


def option_payoff(kind, price_at_expiry, strike, premium=0.0, long=True):
    k = _kind(kind)
    intrinsic = max(0.0, (price_at_expiry - strike) if k == "call" else (strike - price_at_expiry))
    pnl = intrinsic - premium
    return {"intrinsic": intrinsic, "profit": pnl if long else -pnl}


def forward_price(spot, rate_pct, years, dividend_yield_pct=0.0, carry_pct=0.0):
    """Cost of carry: S e^((r - q + storage) T)."""
    return spot * math.exp((rate_pct - dividend_yield_pct + carry_pct) / 100.0 * years)


def fx_forward(spot, domestic_rate_pct, foreign_rate_pct, years):
    """Covered interest parity. Simple interest inside a year, compounded beyond."""
    id_, if_ = domestic_rate_pct / 100.0, foreign_rate_pct / 100.0
    if years <= 1:
        return spot * (1 + id_ * years) / (1 + if_ * years)
    return spot * ((1 + id_) / (1 + if_)) ** years


def forward_points(spot, forward):
    return forward - spot


def forward_premium(spot, forward):
    return (forward / spot - 1) * 100


def cross_rate(base_per_usd, quote_per_usd):
    """Units of the quote currency per one unit of the base, through the dollar."""
    return quote_per_usd / base_per_usd


def fx_adjusted_return(local_return_pct, currency_change_pct):
    """A foreign investor's return: the local return compounded with the move in
    the local currency against theirs."""
    return ((1 + local_return_pct / 100.0) * (1 + currency_change_pct / 100.0) - 1) * 100
