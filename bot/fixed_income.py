#!/usr/bin/env python3
"""bot/fixed_income.py - bond and bill arithmetic.

The bond feeds tell the bot that a Eurobond yield rose or a T-bill auction
cleared higher. This module is what turns that into consequences: what the
price did, how sensitive the paper is, what the investor keeps after tax and
inflation.

  price / ytm        present value of the coupons and principal at a yield, and
                     the yield that solves for a price (bisection, so it cannot
                     diverge the way Newton's method can on deep-discount paper)
  risk               Macaulay and modified duration, convexity, DV01, and the
                     duration-plus-convexity estimate of a price move
  accrued interest   actual/actual between the coupon dates you give it
  bills              money-market yield and discount-rate quoting, both ways
  after tax / real   withholding tax and the Fisher equation
  curve              the yields on file in bonds.json, per country, with each
                     point's date and staleness carried through

Day-count basis for bills differs by market. BILL_BASIS holds the defaults used
when none is given (CBK prices Kenyan bills on a 364-day year); every function
takes the basis as an argument so a different convention is one flag away.
Tax rates are never assumed: withholding is an input, because it depends on the
instrument and the holder.
"""
import datetime as dt
import json
import os
import re

from . import universe as U

BONDS_FILE = os.path.join(U.SD, "bonds.json")
BILL_BASIS = {"NSE": 364, "NGX": 365, "JSE": 365, "EGX": 365}
COUNTRY = {"NSE": "KE", "NGX": "NG", "JSE": "ZA", "EGX": "EG"}


# ------------------------------------------------------------------ bonds
def _cashflows(face, coupon_pct, years, freq):
    periods = years * freq
    n = int(round(periods))
    if n < 1 or abs(n - periods) > 1e-6:
        raise ValueError("years x frequency must be a whole number of coupon periods "
                         "(use accrued_interest for a date between coupons)")
    c = face * coupon_pct / 100.0 / freq
    return [(t, c + (face if t == n else 0.0)) for t in range(1, n + 1)]


def price(face, coupon_pct, ytm_pct, years, freq=2):
    y = ytm_pct / 100.0 / freq
    if y <= -1:
        raise ValueError("yield per period must be above -100%")
    return sum(cf / (1 + y) ** t for t, cf in _cashflows(face, coupon_pct, years, freq))


def ytm(target_price, face, coupon_pct, years, freq=2):
    """Yield to maturity in percent. Price falls as yield rises, so bisect."""
    if target_price <= 0:
        raise ValueError("price must be positive")
    lo, hi = -0.95 * freq * 100, 1000.0
    p_lo, p_hi = price(face, coupon_pct, lo, years, freq), price(face, coupon_pct, hi, years, freq)
    if not p_hi <= target_price <= p_lo:
        raise ValueError("no yield between %.0f%% and %.0f%% gives that price" % (lo, hi))
    for _ in range(200):
        mid = (lo + hi) / 2
        if price(face, coupon_pct, mid, years, freq) > target_price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    return (lo + hi) / 2


def risk(face, coupon_pct, ytm_pct, years, freq=2):
    y = ytm_pct / 100.0 / freq
    flows = _cashflows(face, coupon_pct, years, freq)
    pvs = [(t, cf / (1 + y) ** t) for t, cf in flows]
    p = sum(pv for _, pv in pvs)
    mac = sum((t / float(freq)) * pv for t, pv in pvs) / p
    mod = mac / (1 + y)
    conv = sum(t * (t + 1) * pv for t, pv in pvs) / (p * (1 + y) ** 2 * freq ** 2)
    return {"price": p, "macaulayDuration": mac, "modifiedDuration": mod,
            "convexity": conv, "dv01": mod * p * 0.0001,
            "currentYieldPct": face * coupon_pct / p}


def price_change(modified_duration, convexity, current_price, bp):
    """Duration-plus-convexity estimate for a yield move of `bp` basis points."""
    dy = bp / 10000.0
    pct = -modified_duration * dy + 0.5 * convexity * dy * dy
    return {"pct": pct * 100, "price": current_price * (1 + pct)}


def accrued_interest(face, coupon_pct, freq, last_coupon, next_coupon, settle):
    """Actual/actual (ICMA): the coupon earned so far in the current period."""
    if not last_coupon <= settle <= next_coupon or last_coupon == next_coupon:
        raise ValueError("settlement must fall between the two coupon dates")
    frac = (settle - last_coupon).days / float((next_coupon - last_coupon).days)
    return face * coupon_pct / 100.0 / freq * frac


# ------------------------------------------------------------------ bills
def bill_price(yield_pct, days, basis=365):
    """Price per 100 for a bill quoted on a money-market yield."""
    return 100.0 / (1 + yield_pct / 100.0 * days / basis)


def bill_yield(bill_px, days, basis=365):
    return (100.0 / bill_px - 1) * basis / days * 100


def discount_price(discount_pct, days, basis=365):
    """Price per 100 for a bill quoted on a discount rate."""
    return 100.0 * (1 - discount_pct / 100.0 * days / basis)


def discount_to_yield(discount_pct, days, basis=365):
    d = discount_pct / 100.0
    return d / (1 - d * days / basis) * 100


def yield_to_discount(yield_pct, days, basis=365):
    y = yield_pct / 100.0
    return y / (1 + y * days / basis) * 100


def after_tax(yield_pct, withholding_pct):
    return yield_pct * (1 - withholding_pct / 100.0)


def real_yield(nominal_pct, inflation_pct):
    """Fisher: (1 + nominal) / (1 + inflation) - 1."""
    return ((1 + nominal_pct / 100.0) / (1 + inflation_pct / 100.0) - 1) * 100


# ------------------------------------------------------------------ curve
def tenor_years(inst, today=None):
    """(years, exact?) from a tenor like '91d' / '10y', else a maturity year."""
    today = today or dt.date.today()
    tenor = str(inst.get("tenor") or "").strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([dmy])", tenor)
    if m:
        n = float(m.group(1))
        return {"d": n / 365.0, "m": n / 12.0, "y": n}[m.group(2)], True
    # "R2048" and "FGN 2033 bond" both carry the maturity year; digits either
    # side would make it part of a longer number.
    yr = re.search(r"(?<!\d)(20\d\d)(?!\d)", str(inst.get("name") or ""))
    if yr:
        # Only the maturity year is published, so the tenor is approximate:
        # mid-year, or year end once mid-year has passed.
        mature = dt.date(int(yr.group(1)), 6, 30)
        if mature <= today:
            mature = dt.date(mature.year, 12, 31)
        return max(0.0, (mature - today).days / 365.0), False
    return None, False


def load_bonds():
    try:
        with open(BONDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def curve(today=None):
    data = load_bonds()
    if not data:
        return []
    out = []
    for ctry in data.get("countries") or []:
        pts = []
        for inst in ctry.get("instruments") or []:
            if not isinstance(inst.get("yield"), (int, float)):
                continue
            yrs, exact = tenor_years(inst, today)
            if yrs is None:
                continue
            pts.append({"name": inst.get("name"), "years": yrs, "tenorExact": exact,
                        "yieldPct": inst["yield"], "asOf": inst.get("as_of"),
                        "stale": bool(inst.get("stale"))})
        pts.sort(key=lambda p: p["years"])
        row = {"iso": ctry.get("iso"), "country": ctry.get("country"), "points": pts}
        if len(pts) >= 2:
            row["termSpreadPp"] = pts[-1]["yieldPct"] - pts[0]["yieldPct"]
            row["spreadBetween"] = [pts[0]["name"], pts[-1]["name"]]
            row["shape"] = ("upward" if row["termSpreadPp"] > 0.25 else
                            "inverted" if row["termSpreadPp"] < -0.25 else "flat")
            if any(p["stale"] for p in pts):
                row["caution"] = "one or more points are stale, so the shape may be out of date"
        out.append(row)
    return out


def risk_free(ex):
    """The shortest-dated government yield on file for an exchange's country."""
    iso = COUNTRY.get((ex or "").upper())
    for row in curve():
        if row["iso"] == iso and row["points"]:
            p = row["points"][0]
            return {"yieldPct": p["yieldPct"], "instrument": p["name"],
                    "asOf": p["asOf"], "stale": p["stale"]}
    return None
