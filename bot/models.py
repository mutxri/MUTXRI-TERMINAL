#!/usr/bin/env python3
"""bot/models.py - the named models an analyst reaches for.

Ratios describe a company. These score it, using published methods with cited
thresholds rather than house rules invented here. Each one states what it needs,
computes only when it has it, and says which inputs were missing when it cannot.

What is implemented, and why:

  Piotroski F-Score   nine binary tests of profitability, leverage and
                      efficiency. Built for exactly this situation - cheap
                      statements, no forecasts - and the individual signals are
                      readable, so a 3/8 tells you *which* three.
  Altman Z''-score    distress prediction, in the emerging-market variant
                      (Altman 1995/2005), which drops the sales/assets term and
                      adds a constant precisely so it works outside US
                      manufacturing. The right variant for these four boards.
  Sloan accruals      the gap between reported profit and cash, scaled by
                      assets. High accruals predict weaker subsequent earnings.
  Graham number       a floor-value benchmark from EPS and book value.
  Cost-to-income      the efficiency measure banks are actually judged on, and
                      a large share of these markets by value is banks.
  Operating leverage  how hard profit moves when revenue moves.

  Altman Z and Z'     the original listed-manufacturer model (needs market
                      capitalisation) and the private-firm variant (book
                      equity), alongside Z''.
  Beneish M-Score     eight indices of receivables, margins, asset quality,
                      growth, depreciation, overheads, accruals and leverage.
  Bank and insurer    loan-to-deposit, cost of risk, loss, expense and
  ratios              combined ratios.

Most of the parsed public filings lack the lines Beneish, the cash conversion
cycle and dividend cover need (receivables, property, depreciation, payables,
dividends paid). Each model says exactly which inputs were missing rather than
substituting, and lights up for any accounts that do carry them.
"""


def _get(row, key):
    v = row.get(key) if row else None
    return v if isinstance(v, (int, float)) else None


def _bands(value, cuts, labels):
    """Map a score onto its published bands."""
    if value is None:
        return None
    for cut, label in zip(cuts, labels):
        if value < cut:
            return label
    return labels[-1]


# ------------------------------------------------------------- Piotroski
# (signal key, description, which of the three groups it belongs to)
PIOTROSKI_SIGNALS = [
    ("roa_positive", "ROA positive", "profitability"),
    ("cfo_positive", "operating cash flow positive", "profitability"),
    ("roa_improving", "ROA higher than last year", "profitability"),
    ("accruals_ok", "operating cash flow exceeds net profit", "profitability"),
    ("leverage_falling", "long-term liabilities lighter against assets", "leverage"),
    ("liquidity_improving", "current ratio higher than last year", "leverage"),
    ("no_dilution", "no new shares issued", "leverage"),
    ("margin_improving", "gross margin higher than last year", "efficiency"),
    ("turnover_improving", "asset turnover higher than last year", "efficiency"),
]


def piotroski(rows):
    """Piotroski (2000) F-Score, scored only over the signals the data supports.

    The share-issuance signal needs a share count for both years and these
    filings carry only a current one, so it is reported as unavailable rather
    than assumed clean - assuming it would inflate every score by a point.
    """
    if not rows or len(rows) < 2:
        return {"available": False, "reason": "needs two comparable periods"}
    cur, prv = rows[0], rows[1]
    if cur.get("priorIsAdjacentYear") is False:
        return {"available": False,
                "reason": "prior period is not the preceding fiscal year"}

    res, missing = {}, []

    def sig(key, value):
        if value is None:
            missing.append(key)
        res[key] = value

    roa, roa_p = _get(cur, "roa"), _get(prv, "roa")
    ocf, np_ = _get(cur, "ocf"), _get(cur, "net_profit")
    sig("roa_positive", None if roa is None else roa > 0)
    sig("cfo_positive", None if ocf is None else ocf > 0)
    sig("roa_improving", None if (roa is None or roa_p is None) else roa > roa_p)
    sig("accruals_ok", None if (ocf is None or np_ is None) else ocf > np_)

    # Leverage: long-term liabilities against assets, lower is the good signal.
    def lt_ratio(r):
        ncl, ta = _get(r, "total_liabilities"), _get(r, "total_assets")
        nc = r.get("non_current_liabilities")
        nc = nc if isinstance(nc, (int, float)) else ncl
        return (abs(nc) / ta) if (nc is not None and ta) else None
    l_now, l_prv = lt_ratio(cur), lt_ratio(prv)
    sig("leverage_falling", None if (l_now is None or l_prv is None) else l_now < l_prv)

    cr, cr_p = _get(cur, "current_ratio"), _get(prv, "current_ratio")
    sig("liquidity_improving", None if (cr is None or cr_p is None) else cr > cr_p)
    sig("no_dilution", None)   # no share-count history in this corpus

    gm, gm_p = _get(cur, "gross_margin"), _get(prv, "gross_margin")
    sig("margin_improving", None if (gm is None or gm_p is None) else gm > gm_p)
    at, at_p = _get(cur, "asset_turnover"), _get(prv, "asset_turnover")
    sig("turnover_improving", None if (at is None or at_p is None) else at > at_p)

    scored = [k for k, v in res.items() if v is not None]
    score = sum(1 for k in scored if res[k])
    out = {
        "available": bool(scored),
        "score": score, "outOf": len(scored),
        "signals": [{"key": k, "label": d, "group": g, "passed": res[k]}
                    for k, d, g in PIOTROSKI_SIGNALS],
        "unavailableSignals": missing,
    }
    if scored:
        # Piotroski's own reading of the 0-9 scale, rescaled to what was scored.
        pct = score / float(len(scored))
        out["reading"] = ("strong" if pct >= 0.78 else
                          "middling" if pct >= 0.44 else "weak")
    return out


# ---------------------------------------------------------------- Altman
def altman_z(row):
    """Altman Z''-score, emerging-market variant.

    Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 + 3.25, where X1 is working
    capital / assets, X2 retained earnings / assets, X3 EBIT / assets and X4
    book equity / total liabilities. The sales/assets term of the original
    Z-score is dropped here precisely because it made the model sensitive to
    industry, and the +3.25 constant recentres it for emerging markets.

    Retained earnings is the term this corpus usually lacks, and it carries real
    weight - a company's accumulated history of profit or loss. Without it the
    score is not computed, because dropping a term silently would produce a
    number that looks like a Z-score and is not one.
    """
    ta = _get(row, "total_assets")
    if not ta:
        return {"available": False, "missing": ["total_assets"]}
    wc = _get(row, "working_capital")
    re_ = _get(row, "retained_earnings")
    ebit = _get(row, "ebit")
    te = _get(row, "total_equity")
    tl = _get(row, "total_liabilities")

    missing = [n for n, v in (("working_capital", wc), ("retained_earnings", re_),
                              ("ebit", ebit), ("total_equity", te),
                              ("total_liabilities", tl)) if v is None]
    if missing:
        return {"available": False, "missing": missing,
                "note": "Z'' needs all four terms; a partial score is not a Z-score"}
    if not tl:
        return {"available": False, "missing": ["total_liabilities (zero)"]}

    x1, x2, x3, x4 = wc / ta, re_ / ta, ebit / ta, te / abs(tl)
    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4 + 3.25
    return {
        "available": True, "score": round(z, 2),
        "band": _bands(z, [1.1, 2.6], ["distress", "grey", "safe"]),
        "terms": {"X1_working_capital_to_assets": round(x1, 4),
                  "X2_retained_earnings_to_assets": round(x2, 4),
                  "X3_ebit_to_assets": round(x3, 4),
                  "X4_equity_to_liabilities": round(x4, 4)},
        "variant": "Z'' emerging-market (Altman), bands 1.1 / 2.6",
    }


# ------------------------------------------------------------ earnings quality
def sloan_accruals(rows):
    """Sloan (1996) balance-sheet accruals: (net profit - operating cash flow)
    over average total assets. High accruals mean profit is arriving as
    something other than cash, and predict weaker earnings next period."""
    if not rows:
        return {"available": False, "reason": "no periods"}
    cur = rows[0]
    np_, ocf = _get(cur, "net_profit"), _get(cur, "ocf")
    ta = _get(cur, "total_assets")
    ta_prev = _get(rows[1], "total_assets") if len(rows) > 1 else None
    if np_ is None or ocf is None or not ta:
        return {"available": False,
                "missing": [n for n, v in (("net_profit", np_), ("ocf", ocf),
                                           ("total_assets", ta)) if v is None]}
    avg_ta = (ta + ta_prev) / 2.0 if ta_prev else ta
    ratio = (np_ - ocf) / avg_ta
    return {"available": True, "ratio": round(ratio * 100, 2),
            "basis": "average total assets" if ta_prev else "closing total assets",
            "reading": ("high - profit is not arriving as cash" if ratio > 0.10 else
                        "elevated" if ratio > 0.05 else
                        "cash-backed" if ratio <= 0 else "normal")}


# ------------------------------------------------------------------- value
def per_share(row, shares):
    """Book value per share and the Graham number floor benchmark."""
    if not shares:
        return {"available": False, "reason": "no share count"}
    te, eps = _get(row, "total_equity"), _get(row, "eps")
    out = {"available": True, "shares": shares}
    out["bookValuePerShare"] = round(te / shares, 4) if te is not None else None
    bvps = out["bookValuePerShare"]
    # Graham's rule of thumb: fair value near sqrt(22.5 x EPS x book per share),
    # defined only when both are positive - it is a floor for a profitable
    # company with positive net worth, not a general valuation.
    if eps and bvps and eps > 0 and bvps > 0:
        out["grahamNumber"] = round((22.5 * eps * bvps) ** 0.5, 4)
    else:
        out["grahamNumber"] = None
        out["grahamNote"] = "needs positive EPS and positive book value"
    return out


def cost_to_income(row):
    """Operating expenses over revenue - the efficiency ratio banks are judged
    on, and banks are a large share of these markets by value. Lower is better;
    below 50% is strong for a bank, above 70% is heavy."""
    opex, rev = _get(row, "operating_expenses"), _get(row, "revenue")
    if opex is None or not rev:
        return {"available": False}
    r = abs(opex) / abs(rev) * 100
    return {"available": True, "ratio": round(r, 2),
            "reading": _bands(r, [50, 70], ["strong", "moderate", "heavy"])}


def operating_leverage(rows):
    """Degree of operating leverage: percentage change in EBIT over percentage
    change in revenue. Above 1 means profit amplifies sales, in both
    directions - the number is a warning as much as a virtue."""
    if not rows or len(rows) < 2:
        return {"available": False, "reason": "needs two periods"}
    cur = rows[0]
    if cur.get("priorIsAdjacentYear") is False:
        return {"available": False, "reason": "prior period is not the preceding year"}
    rg, eg = _get(cur, "revenue_growth"), _get(cur, "ebit_growth")
    if rg is None or eg is None or abs(rg) < 0.5:
        # A near-flat revenue line makes the ratio explode on noise.
        return {"available": False,
                "reason": "revenue barely moved, so the ratio is not meaningful"
                          if rg is not None and abs(rg) < 0.5 else "missing growth figures"}
    return {"available": True, "dol": round(eg / rg, 2),
            "revenueGrowth": rg, "ebitGrowth": eg}


# ------------------------------------------------------- Altman variants
def _altman_inputs(row, keys):
    vals = {k: _get(row, k) for k in keys}
    missing = [k for k, v in vals.items() if v is None]
    if not vals.get("total_assets"):
        missing = sorted(set(missing) | {"total_assets"})
    if not missing and not vals.get("total_liabilities"):
        missing = ["total_liabilities (zero)"]
    return vals, missing


def altman_z_original(row, market_cap):
    """Altman (1968) Z for listed manufacturers:
    Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5, X4 = market value of equity /
    total liabilities, X5 = sales / total assets. Bands 1.81 and 2.99."""
    v, missing = _altman_inputs(row, ("working_capital", "retained_earnings", "ebit", "revenue",
                                      "total_liabilities", "total_assets"))
    if not market_cap:
        missing = missing + ["market_cap"]
    if missing:
        return {"available": False, "missing": missing}
    ta = v["total_assets"]
    x = [v["working_capital"] / ta, v["retained_earnings"] / ta, v["ebit"] / ta,
         market_cap / abs(v["total_liabilities"]), v["revenue"] / ta]
    z = 1.2 * x[0] + 1.4 * x[1] + 3.3 * x[2] + 0.6 * x[3] + 1.0 * x[4]
    return {"available": True, "score": round(z, 2),
            "band": _bands(z, [1.81, 2.99], ["distress", "grey", "safe"]),
            "terms": dict(zip(("X1", "X2", "X3", "X4", "X5"), [round(t, 4) for t in x])),
            "variant": "Z (Altman 1968), listed manufacturers, bands 1.81 / 2.99"}


def altman_z_private(row):
    """Altman Z' for private firms: book equity replaces market value.
    Z' = 0.717 X1 + 0.847 X2 + 3.107 X3 + 0.420 X4 + 0.998 X5. Bands 1.23 and 2.90."""
    v, missing = _altman_inputs(row, ("working_capital", "retained_earnings", "ebit", "revenue",
                                      "total_equity", "total_liabilities", "total_assets"))
    if missing:
        return {"available": False, "missing": missing}
    ta = v["total_assets"]
    x = [v["working_capital"] / ta, v["retained_earnings"] / ta, v["ebit"] / ta,
         v["total_equity"] / abs(v["total_liabilities"]), v["revenue"] / ta]
    z = 0.717 * x[0] + 0.847 * x[1] + 3.107 * x[2] + 0.420 * x[3] + 0.998 * x[4]
    return {"available": True, "score": round(z, 2),
            "band": _bands(z, [1.23, 2.90], ["distress", "grey", "safe"]),
            "terms": dict(zip(("X1", "X2", "X3", "X4", "X5"), [round(t, 4) for t in x])),
            "variant": "Z' (Altman), private firms, bands 1.23 / 2.90"}


# ------------------------------------------------------------- Beneish
BENEISH_THRESHOLD = -1.78


def beneish_from_indices(dsri, gmi, aqi, sgi, depi, sgai, tata, lvgi):
    """Beneish (1999) eight-variable M-score."""
    return (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
            + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)


def beneish(rows):
    """Beneish M-score from two adjacent years of statements.

    DSRI receivables/sales, GMI gross margin (prior over current), AQI the share
    of assets that are neither current nor property, SGI sales growth, DEPI
    depreciation rate (prior over current), SGAI overheads/sales, TATA accruals
    over assets, LVGI leverage. Above -1.78 matches the profile of companies
    later found to have manipulated earnings; it is a screen, not a finding.
    """
    if not rows or len(rows) < 2:
        return {"available": False, "reason": "needs two periods"}
    cur, prv = rows[0], rows[1]
    if cur.get("priorIsAdjacentYear") is False:
        return {"available": False, "reason": "prior period is not the preceding year"}

    def gp(r):
        g = _get(r, "gross_profit")
        rev, cos = _get(r, "revenue"), _get(r, "cost_of_sales")
        return g if g is not None else (rev - abs(cos) if rev is not None and cos is not None else None)

    both = ("receivables", "revenue", "current_assets", "ppe", "depreciation",
            "operating_expenses", "total_liabilities", "total_assets")
    missing = sorted({k for r in (cur, prv) for k in both if _get(r, k) is None}
                     | {k for k in ("net_profit", "ocf") if _get(cur, k) is None}
                     | ({"gross_profit"} if gp(cur) is None or gp(prv) is None else set()))
    if missing:
        return {"available": False, "missing": missing}
    g = lambda r, k: abs(_get(r, k))
    try:
        rev_c, rev_p = _get(cur, "revenue"), _get(prv, "revenue")
        idx = {
            "dsri": (g(cur, "receivables") / rev_c) / (g(prv, "receivables") / rev_p),
            "gmi": (gp(prv) / rev_p) / (gp(cur) / rev_c),
            "aqi": ((1 - (_get(cur, "current_assets") + g(cur, "ppe")) / _get(cur, "total_assets"))
                    / (1 - (_get(prv, "current_assets") + g(prv, "ppe")) / _get(prv, "total_assets"))),
            "sgi": rev_c / rev_p,
            "depi": ((g(prv, "depreciation") / (g(prv, "depreciation") + g(prv, "ppe")))
                     / (g(cur, "depreciation") / (g(cur, "depreciation") + g(cur, "ppe")))),
            "sgai": (g(cur, "operating_expenses") / rev_c) / (g(prv, "operating_expenses") / rev_p),
            "tata": (_get(cur, "net_profit") - _get(cur, "ocf")) / _get(cur, "total_assets"),
            "lvgi": ((g(cur, "total_liabilities") / _get(cur, "total_assets"))
                     / (g(prv, "total_liabilities") / _get(prv, "total_assets"))),
        }
    except ZeroDivisionError:
        return {"available": False, "reason": "a component has a zero denominator"}
    m = beneish_from_indices(**idx)
    return {"available": True, "score": round(m, 2), "threshold": BENEISH_THRESHOLD,
            "likelyManipulator": m > BENEISH_THRESHOLD,
            "indices": {k: round(v, 4) for k, v in idx.items()},
            "note": "LVGI uses total liabilities over assets; operating expenses stand in for SG&A"}


# --------------------------------------------------- banks and insurers
def bank_ratios(row):
    vals = {"loanToDeposit": _get(row, "loan_to_deposit"),
            "niiToAssets": _get(row, "nii_to_assets"),
            "costOfRisk": _get(row, "cost_of_risk"),
            "equityToAssets": _get(row, "equity_ratio")}
    return dict(vals, available=any(v is not None for k, v in vals.items() if k != "equityToAssets"))


def insurance_ratios(row):
    vals = {"lossRatio": _get(row, "loss_ratio"), "expenseRatio": _get(row, "expense_ratio"),
            "combinedRatio": _get(row, "combined_ratio")}
    return dict(vals, available=any(v is not None for v in vals.values()))


NOT_COMPUTABLE = {
    "beneish_m_score": "computed when a statement carries receivables, property plant and "
                       "equipment, depreciation and operating expenses for two adjacent "
                       "years; the parsed public filings carry none of the first three",
    "cash_conversion_cycle": "computed when inventory, receivables and payables are present",
    "dividend_cover_and_yield": "computed when the cash flow statement carries dividends paid",
}


def score_all(analysis):
    """Every model that this company's data supports."""
    rows = analysis.get("metrics") or []
    cur = rows[0] if rows else {}
    entity = analysis.get("entity") or {}
    shares = entity.get("sharesOutstanding")
    listed = entity.get("kind", "public") == "public"
    return {
        "piotroski": piotroski(rows),
        "altmanZ": altman_z(cur),
        "altmanZOriginal": altman_z_original(cur, entity.get("marketCap")),
        "altmanZPrivate": (altman_z_private(cur) if not listed else
                           {"available": False, "reason": "listed company: Z or Z'' apply"}),
        "beneish": beneish(rows),
        "accruals": sloan_accruals(rows),
        "perShare": per_share(cur, shares),
        "costToIncome": cost_to_income(cur),
        "operatingLeverage": operating_leverage(rows),
        "bank": bank_ratios(cur),
        "insurance": insurance_ratios(cur),
        "notComputable": NOT_COMPUTABLE,
    }
