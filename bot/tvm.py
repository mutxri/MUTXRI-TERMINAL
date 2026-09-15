#!/usr/bin/env python3
"""bot/tvm.py - time value of money, capital budgeting, returns and break-even.

The arithmetic underneath every other number in finance: what money is worth
at another date, whether a project earns its cost of capital, how a return
compounds, and how many units a business must sell to stop losing money.

Rates are percentages (10 means 10%). Cash flow lists start at time zero, so
[-1000, 500, 500, 500] is an outlay today and three annual inflows.

IRR is found by bracketing and bisection rather than Newton's method, which can
wander off or divide by a near-zero derivative. A cash flow stream whose sign
changes more than once can have several IRRs; irr_report says so, because the
honest answer there is NPV or MIRR, not whichever root a solver lands on.
"""
import datetime as dt
import math


# ------------------------------------------------------------ single sums
def fv(present_value, rate_pct, years, per_year=1):
    return present_value * (1 + rate_pct / 100.0 / per_year) ** (years * per_year)


def pv(future_value, rate_pct, years, per_year=1):
    return future_value / (1 + rate_pct / 100.0 / per_year) ** (years * per_year)


def fv_continuous(present_value, rate_pct, years):
    return present_value * math.exp(rate_pct / 100.0 * years)


def pv_continuous(future_value, rate_pct, years):
    return future_value * math.exp(-rate_pct / 100.0 * years)


def simple_interest(principal, rate_pct, years):
    return principal * rate_pct / 100.0 * years


# --------------------------------------------------------------- annuities
def annuity_pv(payment, rate_pct, periods, due=False):
    r = rate_pct / 100.0
    base = payment * periods if r == 0 else payment * (1 - (1 + r) ** -periods) / r
    return base * (1 + r) if due else base


def annuity_fv(payment, rate_pct, periods, due=False):
    r = rate_pct / 100.0
    base = payment * periods if r == 0 else payment * ((1 + r) ** periods - 1) / r
    return base * (1 + r) if due else base


def annuity_payment(principal, rate_pct, periods, balloon=0.0, due=False):
    """The level payment that repays `principal`, leaving `balloon` at the end."""
    r = rate_pct / 100.0
    if periods <= 0:
        raise ValueError("periods must be positive")
    if r == 0:
        pmt = (principal - balloon) / periods
    else:
        pmt = (principal - balloon / (1 + r) ** periods) * r / (1 - (1 + r) ** -periods)
    return pmt / (1 + r) if due else pmt


def growing_annuity_pv(first_payment, rate_pct, growth_pct, periods):
    r, g = rate_pct / 100.0, growth_pct / 100.0
    if abs(r - g) < 1e-12:
        return first_payment * periods / (1 + r)
    return first_payment / (r - g) * (1 - ((1 + g) / (1 + r)) ** periods)


def perpetuity(payment, rate_pct):
    if rate_pct <= 0:
        raise ValueError("a perpetuity needs a positive rate")
    return payment / (rate_pct / 100.0)


def growing_perpetuity(next_payment, rate_pct, growth_pct):
    if rate_pct <= growth_pct:
        raise ValueError("the rate must exceed growth for a finite value")
    return next_payment / ((rate_pct - growth_pct) / 100.0)


# ------------------------------------------------------------------ rates
def ear(nominal_pct, per_year):
    """Effective annual rate of a nominal rate compounded per_year times."""
    return ((1 + nominal_pct / 100.0 / per_year) ** per_year - 1) * 100


def ear_continuous(nominal_pct):
    return (math.exp(nominal_pct / 100.0) - 1) * 100


def nominal_from_ear(ear_pct, per_year):
    return per_year * ((1 + ear_pct / 100.0) ** (1.0 / per_year) - 1) * 100


def cagr(begin, end, years):
    if begin <= 0 or end <= 0 or years <= 0:
        raise ValueError("CAGR needs positive start and end values and a positive span")
    return ((end / float(begin)) ** (1.0 / years) - 1) * 100


def periods_to_grow(present_value, future_value, rate_pct):
    if present_value <= 0 or future_value <= 0 or rate_pct <= -100 or rate_pct == 0:
        raise ValueError("needs positive values and a non-zero rate")
    return math.log(future_value / present_value) / math.log(1 + rate_pct / 100.0)


def rule_of_72(rate_pct):
    return 72.0 / rate_pct


def doubling_time(rate_pct):
    return math.log(2) / math.log(1 + rate_pct / 100.0)


# ------------------------------------------------------ capital budgeting
def npv(rate_pct, cashflows):
    r = rate_pct / 100.0
    return sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))


def _sign_changes(values):
    signs = [v > 0 for v in values if v != 0]
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


_GRID = [-99.0, -90.0, -75.0, -50.0, -25.0, -10.0, 0.0, 5.0, 10.0, 15.0, 20.0, 30.0,
         50.0, 75.0, 100.0, 200.0, 500.0, 1000.0]


def _root(f):
    """First rate on the grid where f changes sign, refined by bisection."""
    px, pf = _GRID[0], f(_GRID[0])
    for x in _GRID[1:]:
        fx = f(x)
        if pf == 0:
            return px
        if pf * fx < 0:
            lo, hi, flo = px, x, pf
            for _ in range(300):
                mid = (lo + hi) / 2
                fm = f(mid)
                if fm == 0 or hi - lo < 1e-12:
                    return mid
                if flo * fm < 0:
                    hi = mid
                else:
                    lo, flo = mid, fm
            return (lo + hi) / 2
        px, pf = x, fx
    return None


def irr(cashflows):
    """Internal rate of return in percent, or None when no rate solves it."""
    if _sign_changes(cashflows) == 0:
        return None
    return _root(lambda x: npv(x, cashflows))


def irr_report(cashflows):
    n = _sign_changes(cashflows)
    out = {"irrPct": irr(cashflows), "signChanges": n}
    if n > 1:
        out["caution"] = ("the cash flows change sign %d times, so more than one IRR can "
                          "exist; judge the project on NPV or MIRR" % n)
    if out["irrPct"] is None:
        out["reason"] = "no rate between -99% and 1000% sets NPV to zero"
    return out


def mirr(cashflows, finance_pct, reinvest_pct):
    """Outflows discounted at the finance rate, inflows compounded at the
    reinvestment rate - which removes IRR's assumption that interim cash earns
    the IRR itself."""
    n = len(cashflows) - 1
    fr, rr = finance_pct / 100.0, reinvest_pct / 100.0
    pv_out = sum(cf / (1 + fr) ** t for t, cf in enumerate(cashflows) if cf < 0)
    fv_in = sum(cf * (1 + rr) ** (n - t) for t, cf in enumerate(cashflows) if cf > 0)
    if n < 1 or pv_out == 0 or fv_in == 0:
        return None
    return ((fv_in / -pv_out) ** (1.0 / n) - 1) * 100


def _dated(dated_cashflows):
    rows = [(d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)), float(a))
            for d, a in dated_cashflows]
    if not rows:
        raise ValueError("no cash flows")
    return rows


def xnpv(rate_pct, dated_cashflows):
    """NPV of cash flows on actual dates, actual/365."""
    rows = _dated(dated_cashflows)
    d0 = min(d for d, _ in rows)
    r = rate_pct / 100.0
    return sum(a / (1 + r) ** ((d - d0).days / 365.0) for d, a in rows)


def xirr(dated_cashflows):
    rows = _dated(dated_cashflows)
    if _sign_changes([a for _, a in sorted(rows)]) == 0:
        return None
    return _root(lambda x: xnpv(x, rows))


def payback(cashflows):
    """Years until cumulative cash flow turns non-negative, interpolated."""
    cum = cashflows[0]
    if cum >= 0:
        return 0.0
    for t, cf in enumerate(cashflows[1:], start=1):
        prev = cum
        cum += cf
        if cum >= 0:
            return (t - 1) + (-prev / cf)
    return None


def discounted_payback(rate_pct, cashflows):
    r = rate_pct / 100.0
    return payback([cf / (1 + r) ** t for t, cf in enumerate(cashflows)])


def profitability_index(rate_pct, cashflows):
    if not cashflows or cashflows[0] >= 0:
        raise ValueError("the first cash flow must be the initial outlay (negative)")
    return npv(rate_pct, [0.0] + list(cashflows[1:])) / abs(cashflows[0])


def equivalent_annual_annuity(rate_pct, cashflows):
    """NPV spread into a level annual amount, to compare projects of unequal lives."""
    n = len(cashflows) - 1
    r = rate_pct / 100.0
    if n < 1:
        raise ValueError("needs at least one period after the outlay")
    value = npv(rate_pct, cashflows)
    return value / n if r == 0 else value * r / (1 - (1 + r) ** -n)


def amortisation(principal, rate_pct, years, per_year=12):
    n = int(round(years * per_year))
    r = rate_pct / 100.0 / per_year
    pmt = annuity_payment(principal, rate_pct / per_year, n)
    bal, rows, total_int = float(principal), [], 0.0
    for k in range(1, n + 1):
        interest = bal * r
        princ = pmt - interest
        bal -= princ
        total_int += interest
        rows.append({"period": k, "payment": pmt, "interest": interest,
                     "principal": princ, "balance": max(bal, 0.0) if k == n else bal})
    return {"payment": pmt, "periods": n, "totalPaid": pmt * n,
            "totalInterest": total_int, "schedule": rows}


# ---------------------------------------------------------------- returns
def holding_period_return(buy_price, sell_price, income=0.0):
    if buy_price <= 0:
        raise ValueError("buy price must be positive")
    return (sell_price - buy_price + income) / buy_price * 100


def annualise(total_return_pct, years):
    if years <= 0 or total_return_pct <= -100:
        raise ValueError("needs a positive span and a return above -100%")
    return ((1 + total_return_pct / 100.0) ** (1.0 / years) - 1) * 100


def twr(period_returns_pct):
    """Time-weighted return: chain the sub-period returns, so cash moving in
    and out does not distort the manager's result."""
    g = 1.0
    for r in period_returns_pct:
        g *= 1 + r / 100.0
    return (g - 1) * 100


def arithmetic_mean_return(returns_pct):
    return sum(returns_pct) / float(len(returns_pct))


def geometric_mean_return(returns_pct):
    g = 1.0
    for r in returns_pct:
        g *= 1 + r / 100.0
    if g <= 0:
        raise ValueError("a cumulative loss of 100% or more has no geometric mean")
    return (g ** (1.0 / len(returns_pct)) - 1) * 100


def expected_return(outcomes_pct, probabilities):
    if len(outcomes_pct) != len(probabilities):
        raise ValueError("one probability per outcome")
    if abs(sum(probabilities) - 1) > 1e-6:
        raise ValueError("probabilities must sum to 1")
    return sum(o * p for o, p in zip(outcomes_pct, probabilities))


# -------------------------------------------------------- cost and leverage
def contribution_margin_ratio(price, variable_cost):
    return (price - variable_cost) / price * 100


def breakeven_units(fixed_costs, price, variable_cost):
    if price <= variable_cost:
        raise ValueError("price must exceed variable cost per unit, or no volume breaks even")
    return fixed_costs / (price - variable_cost)


def breakeven_revenue(fixed_costs, contribution_margin_pct):
    if contribution_margin_pct <= 0:
        raise ValueError("contribution margin must be positive")
    return fixed_costs / (contribution_margin_pct / 100.0)


def margin_of_safety_sales(sales, breakeven_sales):
    return (sales - breakeven_sales) / sales * 100


def degree_financial_leverage(ebit, interest):
    if ebit == interest:
        raise ValueError("EBIT equal to interest leaves nothing for shareholders")
    return ebit / (ebit - interest)
