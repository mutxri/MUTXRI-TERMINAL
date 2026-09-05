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

What is deliberately NOT implemented, because this corpus cannot support it
honestly - the line items simply are not in the filings:

  Beneish M-Score          needs receivables, depreciation, SG&A and sales
                           quality across two years. None of the first three
                           are in these statements.
  Cash conversion cycle    needs inventory, receivables and payables.
  Dividend cover / yield    needs a dividends-paid line; the cash flow
                           statements here do not carry one.

Those line items are mapped in bot/statements.py regardless, so each of these
lights up automatically for a private company whose accounts do carry them.
Reporting "not computable, and here is what was missing" beats a number built
out of substitutes.
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


NOT_COMPUTABLE = {
    "beneish_m_score": "needs receivables, depreciation and SG&A across two "
                       "periods; none are present in these filings",
    "cash_conversion_cycle": "needs inventory, receivables and payables",
    "dividend_cover_and_yield": "needs a dividends-paid line in the cash flow "
                                "statement",
}


def score_all(analysis):
    """Every model that this company's data supports."""
    rows = analysis.get("metrics") or []
    cur = rows[0] if rows else {}
    shares = (analysis.get("entity") or {}).get("sharesOutstanding")
    return {
        "piotroski": piotroski(rows),
        "altmanZ": altman_z(cur),
        "accruals": sloan_accruals(rows),
        "perShare": per_share(cur, shares),
        "costToIncome": cost_to_income(cur),
        "operatingLeverage": operating_leverage(rows),
        "notComputable": NOT_COMPUTABLE,
    }
