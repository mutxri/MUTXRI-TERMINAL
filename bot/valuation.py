#!/usr/bin/env python3
"""bot/valuation.py - intrinsic value, and what the price already assumes.

  capm / wacc        cost of equity from a risk-free rate, beta and an equity
                     risk premium; blended cost of capital after tax
  gordon / ddm       constant-growth perpetuity and dividend discount model
  dcf                explicit free-cash-flow years plus a Gordon terminal value,
                     with the share of value sitting in the terminal reported
  reverse dcf        the growth rate today's price implies - usually the more
                     honest question, because it needs no forecast from us
  sensitivity        per-share value across a grid of discount and terminal
                     growth rates

Every assumption is an input. The bot does not carry a house equity risk
premium, a default beta or a growth forecast: those are opinions, and a DCF
that hides them produces a precise-looking number built on someone else's
guess. The command line shows each assumption beside the answer.

Statement figures and market capitalisation must be in the same units for a
per-share value to mean anything. When a company's two P/E routes disagree
(statements.valuation), the unit alignment is suspect and the result says so.
"""
from . import statements as S

TERMINAL_WARN = 75.0     # % of enterprise value in the terminal year


def capm(rf_pct, beta, erp_pct, country_premium_pct=0.0):
    return rf_pct + beta * erp_pct + country_premium_pct


def wacc(equity, debt, cost_equity_pct, cost_debt_pct, tax_pct):
    v = float(equity + debt)
    if v <= 0:
        raise ValueError("equity plus debt must be positive")
    return equity / v * cost_equity_pct + debt / v * cost_debt_pct * (1 - tax_pct / 100.0)


def gordon(cash_flow_next, r_pct, g_pct):
    if r_pct <= g_pct:
        raise ValueError("discount rate %.2f%% must exceed growth %.2f%%; a perpetuity "
                         "growing faster than its discount rate has no finite value"
                         % (r_pct, g_pct))
    return cash_flow_next / ((r_pct - g_pct) / 100.0)


def ddm(dividend_now, r_pct, g_pct):
    return gordon(dividend_now * (1 + g_pct / 100.0), r_pct, g_pct)


def _path(growth, years):
    if isinstance(growth, (list, tuple)):
        return [float(g) for g in growth]
    if not years or years < 1:
        raise ValueError("give the number of explicit years")
    return [float(growth)] * int(years)


def dcf(fcf0, r_pct, terminal_g_pct, growth, years=None):
    path = _path(growth, years)
    r = r_pct / 100.0
    flows, pv_sum, cf = [], 0.0, float(fcf0)
    for i, g in enumerate(path, start=1):
        cf *= 1 + g / 100.0
        df = 1 / (1 + r) ** i
        flows.append({"year": i, "growthPct": g, "fcf": cf, "discountFactor": df,
                      "pv": cf * df})
        pv_sum += cf * df
    tv = gordon(cf * (1 + terminal_g_pct / 100.0), r_pct, terminal_g_pct)
    pv_tv = tv / (1 + r) ** len(path)
    ev = pv_sum + pv_tv
    out = {"years": flows, "pvExplicit": pv_sum, "terminalValue": tv,
           "pvTerminal": pv_tv, "enterpriseValue": ev,
           "terminalSharePct": pv_tv / ev * 100 if ev else None}
    if out["terminalSharePct"] and out["terminalSharePct"] > TERMINAL_WARN:
        out["caution"] = ("%.0f%% of the value is in the terminal year, so the answer "
                          "rests mostly on the perpetual growth assumption"
                          % out["terminalSharePct"])
    return out


def equity_bridge(enterprise_value, net_debt, shares):
    eq = enterprise_value - (net_debt or 0.0)
    return {"equityValue": eq, "perShare": eq / shares if shares else None}


def reverse_dcf(target_ev, fcf0, r_pct, terminal_g_pct, years):
    """The constant explicit-period growth that makes the DCF equal target_ev."""
    def ev(g):
        return dcf(fcf0, r_pct, terminal_g_pct, g, years)["enterpriseValue"]
    lo, hi = -50.0, 150.0
    if not ev(lo) <= target_ev <= ev(hi):
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if ev(mid) < target_ev:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return (lo + hi) / 2


def sensitivity(fcf0, growth, years, rates, terminal_growths, net_debt, shares):
    grid = []
    for r in rates:
        row = []
        for g in terminal_growths:
            try:
                ev = dcf(fcf0, r, g, growth, years)["enterpriseValue"]
                row.append(equity_bridge(ev, net_debt, shares)["perShare"])
            except ValueError:
                row.append(None)
        grid.append(row)
    return {"rates": list(rates), "terminalGrowths": list(terminal_growths), "perShare": grid}


def margin_of_safety(value, market_price):
    if not value or not market_price or value <= 0:
        return None
    return {"marginOfSafetyPct": (value - market_price) / value * 100,
            "upsidePct": (value / market_price - 1) * 100}


def company_inputs(doc):
    """The statement figures a DCF on a real company starts from."""
    a = S.analyse(doc)
    rows = a.get("metrics") or []
    cur = rows[0] if rows else {}
    val = a.get("valuation") or {}
    ent = a.get("entity") or {}
    out = {"ticker": ent.get("ticker") or ent.get("id"), "name": ent.get("name"),
           "currency": ent.get("currency"), "period": cur.get("period"),
           "fcf": cur.get("fcf"), "netDebt": cur.get("net_debt"),
           "shares": val.get("sharesOutstanding"), "marketCap": val.get("marketCap"),
           "impliedPrice": val.get("impliedPrice"), "problems": []}
    if out["fcf"] is None:
        out["problems"].append("no free cash flow line in the latest period")
    elif out["fcf"] <= 0:
        out["problems"].append("free cash flow is negative, so a DCF from it has no base")
    if out["netDebt"] is None:
        out["problems"].append("net debt not computable (borrowings or cash missing)")
    if not out["shares"]:
        out["problems"].append("no share count on file")
    pc = val.get("peCrossCheck")
    if pc and pc != "agree":
        out["unitWarning"] = ("the two P/E routes %s, so statement units and market cap "
                              "may not align; treat per-share values with suspicion" % pc)
    return out
