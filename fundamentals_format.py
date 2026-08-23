"""
fundamentals_format.py  -  Consistent money formatting + sanity validation.

THE BUG THIS FIXES
------------------
On the SCOM panel the right rail showed:
    Total Assets          508,600,000,000     (raw absolute)
    Operating Cash Flow    64,700,000,000     (raw absolute)
    Revenue                          11.1     (already scaled -> looks broken)

Two different code paths formatted the same kind of field two different ways:
one printed the raw absolute integer, the other printed a pre-scaled number
("11.1", presumably 11.1 billion) with no unit. Side by side, "Revenue 11.1"
next to "Total Assets 508,600,000,000" reads as a broken/fake figure.

FIX (two parts)
---------------
1. format_money(value, ...) - ONE formatter used for every monetary field so
   the whole panel is consistent: 508.6B, 64.7B, 11.1B, 950.0M, etc. If a
   value is missing it returns the honest dash "-", never 0 or a guess.

2. validate_fundamentals(record) - flags records whose fields have
   implausible magnitude relationships (e.g. a revenue that is billions of
   times smaller than total assets => almost certainly a unit mismatch in the
   source data). The UI can then show a "data suspect" marker instead of a
   misleading number. This is the terminal's core rule applied to fundamentals:
   surface bad data honestly rather than render it as fact.

Pure stdlib. No network. Deterministic. Unit-tested.
"""

DASH = "\u2014"  # em dash used as the honest "no data" marker in the UI


def _to_float(v):
    if v is None or v is True or v is False:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def format_money(value, currency=None, dash=DASH, decimals=1):
    """Format a monetary amount consistently with a magnitude suffix.

    12_345_678_901 -> '12.3B'      950_000_000 -> '950.0M'
    11_100_000_000 -> '11.1B'      1_250        -> '1.3K'
    None / bad     -> dash (honest, never 0)
    Negative values keep their sign. `currency` if given is appended: '12.3B KES'.
    """
    f = _to_float(value)
    if f is None:
        return dash
    sign = "-" if f < 0 else ""
    a = abs(f)
    if a >= 1e12:
        s = "%.*fT" % (decimals, a / 1e12)
    elif a >= 1e9:
        s = "%.*fB" % (decimals, a / 1e9)
    elif a >= 1e6:
        s = "%.*fM" % (decimals, a / 1e6)
    elif a >= 1e3:
        s = "%.*fK" % (decimals, a / 1e3)
    else:
        s = "%.*f" % (decimals, a)
    out = sign + s
    return out + (" " + currency if currency else "")


# fields we treat as absolute monetary amounts on the fundamentals panel
MONEY_FIELDS = ("revenue", "totalAssets", "operatingCashFlow", "netIncome",
                "grossProfit", "ebitda", "totalLiabilities", "totalEquity",
                "marketCap", "cash", "totalDebt")

# ratio: if two present money fields differ by more than this factor it's almost
# certainly a unit mismatch (one raw, one pre-scaled). 1e6 = a millionfold gap.
SUSPECT_FACTOR = 1e6


def validate_fundamentals(record):
    """Check a fundamentals record for unit-mismatch / magnitude problems.

    Returns {"ok":bool, "suspect":[field,...], "reason":str|None}.
    Does NOT mutate the record. The UI shows a warning + dashes for suspect
    fields rather than printing a misleading number.
    """
    vals = {}
    for k in MONEY_FIELDS:
        f = _to_float(record.get(k))
        if f is not None and f != 0:
            vals[k] = abs(f)
    if len(vals) < 2:
        return {"ok": True, "suspect": [], "reason": None}

    lo = min(vals.values())
    hi = max(vals.values())
    if lo > 0 and hi / lo > SUSPECT_FACTOR:
        # identify the outliers: the ones far from the median magnitude
        import statistics
        med = statistics.median(vals.values())
        suspect = [k for k, v in vals.items()
                   if v > 0 and (v / med > SUSPECT_FACTOR or med / v > SUSPECT_FACTOR)]
        return {"ok": False, "suspect": sorted(suspect),
                "reason": ("monetary fields span >%gx in magnitude - likely a "
                           "unit mismatch (some values raw, some pre-scaled)"
                           % SUSPECT_FACTOR)}
    return {"ok": True, "suspect": [], "reason": None}


def render_fundamentals(record, currency=None):
    """Produce display-ready strings for a fundamentals record, applying the
    validator so suspect fields show the honest dash instead of a bad number.

    Returns {"fields": {name: display_str}, "warning": str|None}.
    """
    v = validate_fundamentals(record)
    suspect = set(v["suspect"])
    out = {}
    for k in MONEY_FIELDS:
        if k in record:
            out[k] = DASH if k in suspect else format_money(record.get(k), currency)
    warning = None if v["ok"] else v["reason"]
    return {"fields": out, "warning": warning}
