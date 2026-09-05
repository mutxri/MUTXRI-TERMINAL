#!/usr/bin/env python3
"""bot/statements.py - reading financial statements into something reasoned about.

Two jobs, both deterministic:

  1. NORMALISE  Any statement - a parsed public filing from static_data/financials,
                or a private company's PDF/CSV/XLSX run through bot/ingest.py -
                becomes one canonical shape, so downstream code never cares where
                the numbers came from.
  2. COMPUTE    Margins, growth, returns, leverage, liquidity, cash conversion and
                earnings-quality flags, calculated in Python.

Nothing in this module calls a language model, and that is deliberate: an LLM must
never be the thing that does arithmetic on a balance sheet. bot/analyst.py explains
what these numbers mean; this module decides what they are.

Periods are newest-first and may have gaps (FY2026, FY2025, FY2022...). Growth is
only computed between genuinely adjacent fiscal years, and a gap is reported rather
than silently treated as a one-year change.
"""
import json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(BASE, "static_data")
FIN_DIR = os.path.join(SD, "financials")

# Canonical line items -> the label spellings actually seen in the corpus.
# Matching is case-insensitive and punctuation-insensitive; first hit wins, so
# the more specific spellings come first.
INCOME_MAP = [
    ("revenue", ["net revenue", "revenue", "turnover", "total revenue", "net sales",
                 "sales", "gross revenue", "interest income", "total income",
                 "gross sales including indirect taxes", "gross sales"]),
    ("cost_of_sales", ["cost of sales", "cost of goods sold", "cogs",
                       "cost of revenue"]),
    ("gross_profit", ["gross profit", "gross income"]),
    ("operating_expenses", ["operating expenses", "opex", "total operating expenses",
                            "administrative expenses"]),
    ("ebit", ["operating profit (ebit)", "operating profit", "ebit",
              "operating income", "results from operating activities"]),
    ("net_finance_costs", ["net finance costs", "finance costs", "interest expense",
                           "net interest expense", "finance cost"]),
    ("pbt", ["profit before tax", "pbt", "profit before taxation",
             "earnings before tax", "profit/(loss) before tax"]),
    ("tax", ["income tax", "tax", "taxation", "income tax expense", "tax expense"]),
    ("net_profit", ["net profit", "profit for the year", "profit after tax",
                    "net income", "pat", "profit/(loss) for the year",
                    "profit attributable to owners"]),
    ("eps", ["eps", "earnings per share", "basic eps", "basic earnings per share"]),
]

BALANCE_MAP = [
    ("total_assets", ["total assets"]),
    ("non_current_assets", ["non-current assets", "non current assets",
                            "noncurrent assets"]),
    ("current_assets", ["current assets", "total current assets"]),
    ("cash", ["cash & equivalents", "cash and equivalents", "cash",
              "cash and cash equivalents", "cash & cash equivalents"]),
    ("total_liabilities", ["total liabilities"]),
    ("non_current_liabilities", ["non-current liabilities", "non current liabilities",
                                 "noncurrent liabilities"]),
    ("current_liabilities", ["current liabilities", "total current liabilities"]),
    ("total_equity", ["total equity", "shareholders equity", "total shareholders equity",
                      "shareholders funds", "total shareholders funds",
                      "capital and reserves", "equity", "net assets"]),
    ("borrowings", ["borrowings", "total borrowings", "debt", "total debt",
                    "interest-bearing debt", "loans and borrowings"]),
    ("inventory", ["inventory", "inventories", "stock"]),
    ("receivables", ["receivables", "trade receivables", "trade and other receivables"]),
]

CASHFLOW_MAP = [
    ("ocf", ["operating cash flow", "net cash generated from operating activities",
             "net cash from operating activities",
             "cash from operations", "net cash generated from operations",
             "net cash provided by operating activities"]),
    ("icf", ["investing cash flow", "net cash from investing activities",
             "net cash used in investing activities"]),
    ("fcf_financing", ["financing cash flow", "net cash from financing activities",
                       "net cash used in financing activities"]),
    ("capex", ["capital expenditure", "capex", "purchase of property plant and equipment",
               "additions to property plant and equipment"]),
    ("fcf", ["free cash flow", "fcf"]),
    ("net_change_cash", ["net change in cash", "net increase in cash",
                         "net increase/(decrease) in cash"]),
    ("dividends_paid", ["dividends paid", "dividend paid", "dividends to shareholders"]),
]

SECTION_MAPS = {"income": INCOME_MAP, "balance": BALANCE_MAP, "cashflow": CASHFLOW_MAP}

# Ceiling on a rebuilt EBIT, as a share of revenue. See the derivation in
# compute(): above this the finance line is operating cost, not financing.
MAX_DERIVED_EBIT_MARGIN = 0.60


def _norm_label(s):
    return re.sub(r"[^a-z0-9 &]+", " ", (s or "").lower()).strip()


def _canon(label, mapping):
    """Map a raw statement label to a canonical key, or None if unrecognised."""
    n = _norm_label(label)
    n_compact = re.sub(r"\s+", " ", n)
    for key, spellings in mapping:
        for sp in spellings:
            if n_compact == _norm_label(sp):
                return key
    # Fall back to a contained-phrase match, longest spelling first so
    # "profit before tax" wins over "profit".
    for key, spellings in mapping:
        for sp in sorted(spellings, key=len, reverse=True):
            spn = _norm_label(sp)
            if len(spn) >= 8 and spn in n_compact:
                return key
    return None


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("−", "-")
    if not s or s in ("-", "--", "n/a", "na", "nil"):
        return None
    neg = s.startswith("(") and s.endswith(")")   # accounting negatives
    if neg:
        s = s[1:-1]
    s = re.sub(r"[^\d.\-eE]", "", s)
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def normalise_section(raw, section):
    """Turn {rows:[{label,values}], periods:[...]} into {canonical_key: [values]}."""
    mapping = SECTION_MAPS[section]
    out, unmapped = {}, []
    for row in raw.get("rows", []) or []:
        key = _canon(row.get("label"), mapping)
        vals = [_num(v) for v in (row.get("values") or [])]
        if key is None:
            unmapped.append(row.get("label"))
            continue
        # First mapped occurrence wins; statements often repeat a concept in
        # subtotals further down, and the headline line comes first.
        if key not in out:
            out[key] = vals
    return out, unmapped


# ------------------------------------------------------------------- loading
def load_public(ticker):
    """Load the three statements for a listed security from static_data/financials."""
    got, periods, meta = {}, None, {}
    for section in ("income", "balance", "cashflow"):
        p = os.path.join(FIN_DIR, "%s__%s.json" % (ticker, section))
        if not os.path.exists(p):
            continue
        raw = json.load(open(p, encoding="utf-8"))
        if not raw.get("available", True):
            continue
        vals, _unmapped = normalise_section(raw, section)
        got[section] = vals
        periods = periods or raw.get("periods")
        meta = meta or {
            "name": raw.get("name"), "currency": raw.get("currency"),
            "source": raw.get("source"), "asOf": raw.get("asOf"),
            "marketCap": raw.get("marketCap"),
            "sharesOutstanding": raw.get("sharesOutstanding"),
        }
    if not got:
        return None
    return {
        "entity": {
            "id": ticker, "kind": "public", "ticker": ticker,
            "name": meta.get("name") or ticker,
            "currency": meta.get("currency"),
            "marketCap": meta.get("marketCap"),
            "sharesOutstanding": meta.get("sharesOutstanding"),
        },
        "periods": periods or [],
        "sections": got,
        "source": {"kind": "parsed-filing", "detail": meta.get("source"),
                   "asOf": meta.get("asOf")},
    }


def available_public():
    """Tickers that have at least one parsed statement on disk."""
    if not os.path.isdir(FIN_DIR):
        return []
    return sorted({f.split("__")[0] for f in os.listdir(FIN_DIR) if "__" in f})


# ------------------------------------------------------------------- metrics
def _at(series, i):
    """Value at period index i, or None."""
    if not series or i >= len(series):
        return None
    return series[i]


def _safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def _pct(a, b):
    r = _safe_div(a, b)
    return None if r is None else round(r * 100, 2)


def _fy(period):
    """Extract a fiscal year integer from 'FY2026', '2026', 'Dec 2026'."""
    m = re.search(r"(19|20)\d{2}", str(period or ""))
    return int(m.group(0)) if m else None


def compute(doc):
    """Compute the metric set for a normalised statement document.

    Returns per-period metrics newest-first, aligned to doc['periods'].
    Every value is either a real number or None - never a guess or a zero
    standing in for missing data.
    """
    inc = doc["sections"].get("income", {})
    bal = doc["sections"].get("balance", {})
    cfs = doc["sections"].get("cashflow", {})
    periods = doc.get("periods") or []
    n = len(periods)

    rows = []
    for i in range(n):
        rev = _at(inc.get("revenue"), i)
        gp = _at(inc.get("gross_profit"), i)
        ebit = _at(inc.get("ebit"), i)
        pbt = _at(inc.get("pbt"), i)
        np_ = _at(inc.get("net_profit"), i)
        fin = _at(inc.get("net_finance_costs"), i)
        ta = _at(bal.get("total_assets"), i)
        tl = _at(bal.get("total_liabilities"), i)
        te = _at(bal.get("total_equity"), i)
        cash = _at(bal.get("cash"), i)
        debt = _at(bal.get("borrowings"), i)
        ca = _at(bal.get("current_assets"), i)
        cl = _at(bal.get("current_liabilities"), i)
        inv = _at(bal.get("inventory"), i)
        recv = _at(bal.get("receivables"), i)
        cos = _at(inc.get("cost_of_sales"), i)
        tax = _at(inc.get("tax"), i)
        ocf = _at(cfs.get("ocf"), i)
        capex = _at(cfs.get("capex"), i)
        fcf = _at(cfs.get("fcf"), i)
        if fcf is None and ocf is not None and capex is not None:
            # capex is reported as an outflow in some sources and a positive
            # magnitude in others; subtract its magnitude either way.
            fcf = ocf - abs(capex)

        # Net debt needs a real borrowings line. Total liabilities is not debt -
        # it includes payables, provisions and deferred tax - so when borrowings
        # are absent the figure stays unavailable rather than being approximated.
        net_debt = ((abs(debt) - cash) if (debt is not None and cash is not None)
                    else None)

        # Capital employed, two ways. The textbook form is total assets less
        # current liabilities, but most filings in this corpus never print a
        # current-liabilities line, which left ROCE and ROIC null for almost
        # every company. Equity plus debt measures the same capital from the
        # funding side and is available far more often; the basis is recorded
        # so the two are never silently compared as if identical.
        # EBIT is often absent from a condensed filing. It can be rebuilt as PBT
        # plus net finance costs - but not for a bank, where interest expense is
        # a cost of revenue rather than a financing item, and the sum exceeds
        # revenue itself. Absa's rebuild comes to 121.6bn against 115.2bn of
        # revenue, which is the tell. Accept a derived EBIT only when it lands
        # inside revenue, and record that it was derived.
        ebit_derived = False
        if ebit is None and pbt is not None and fin is not None and rev:
            cand = pbt + abs(fin)
            # A derived EBIT worth more than this share of revenue means the
            # finance line is not a financing cost - it is a bank's interest
            # expense, which belongs above the operating line. An operating
            # margin above 60% is vanishingly rare outside financials, so it is
            # a safe ceiling; allowing the full 100% let a bank through, since
            # EBIT equal to revenue implies a company with no costs at all.
            if 0 < cand <= abs(rev) * MAX_DERIVED_EBIT_MARGIN:
                ebit, ebit_derived = cand, True

        cap_emp, cap_basis = None, None
        if ta is not None and cl is not None:
            cap_emp, cap_basis = ta - abs(cl), "assets less current liabilities"
        elif te is not None and debt is not None:
            cap_emp, cap_basis = te + abs(debt), "equity plus debt"
        elif te is not None:
            cap_emp, cap_basis = te, "equity only (no debt line reported)"

        rows.append({
            "period": periods[i],
            "fy": _fy(periods[i]),
            # scale
            "revenue": rev, "net_profit": np_, "ebit": ebit, "pbt": pbt,
            "total_assets": ta, "total_equity": te, "total_liabilities": tl,
            "cash": cash, "borrowings": debt, "net_debt": net_debt,
            "ocf": ocf, "capex": capex, "fcf": fcf,
            # margins
            "gross_margin": _pct(gp, rev),
            "ebit_margin": _pct(ebit, rev),
            "net_margin": _pct(np_, rev),
            # Returns. A ratio over negative equity is arithmetic without
            # meaning: ArcelorMittal SA's -2.9bn loss over -317m of equity
            # computes to ROE +915%, which reads as spectacular performance and
            # is the opposite of the truth. Equity-based ratios are withheld
            # when the denominator is not positive; `negative_equity` says why.
            "roe": _pct(np_, te) if (te or 0) > 0 else None,
            "roa": _pct(np_, ta) if (ta or 0) > 0 else None,
            # leverage & liquidity
            "debt_to_equity": (round(_safe_div(abs(debt), te), 3)
                               if (te or 0) > 0 and debt is not None else None),
            "liabilities_to_equity": (round(_safe_div(abs(tl), te), 3)
                                      if (te or 0) > 0 and tl is not None else None),
            "net_debt_to_equity": (round(_safe_div(net_debt, te), 3)
                                   if (te or 0) > 0 and _safe_div(net_debt, te) is not None else None),
            # Liabilities are a magnitude. Filings that present a net-assets
            # layout show them bracketed as deductions - BAT Kenya reports
            # "Current liabilities (6,198)" - and dividing by the signed value
            # returns a current ratio of -2.24 for a company that is comfortably
            # liquid at 2.24. A negative liability is a presentation convention,
            # never an economic fact.
            "current_ratio": (round(_safe_div(ca, abs(cl)), 3)
                              if cl not in (None, 0) and ca is not None else None),
            "interest_cover": (round(_safe_div(ebit, abs(fin)), 2)
                               if fin not in (None, 0) and ebit is not None else None),
            # Return on capital - the "ROI" of a business, and a better one than
            # ROE because it is not flattered by leverage. Capital employed is
            # total assets less current liabilities; ROIC taxes EBIT first, using
            # the effective rate the company actually paid rather than a statutory
            # guess, so it is only computed when both PBT and tax are present.
            "ebit_derived": ebit_derived,
            "capital_employed": cap_emp,
            "capital_employed_basis": cap_basis,
            "roce": _pct(ebit, cap_emp) if (
                ebit is not None and (cap_emp or 0) > 0) else None,
            "effective_tax_rate": _pct(abs(tax), pbt) if (
                tax is not None and (pbt or 0) > 0) else None,
            "roic": _pct(ebit * (1 - min(max(abs(tax) / pbt, 0.0), 1.0)), cap_emp) if (
                ebit is not None and tax is not None and (pbt or 0) > 0
                and (cap_emp or 0) > 0) else None,
            # DuPont: ROE = net margin x asset turnover x equity multiplier.
            # Splitting it says whether a return comes from trading well, using
            # assets hard, or simply borrowing - three very different companies
            # can print the same ROE.
            "asset_turnover": (round(_safe_div(rev, ta), 3)
                               if (ta or 0) > 0 and rev is not None else None),
            "equity_multiplier": (round(_safe_div(ta, te), 3)
                                  if (te or 0) > 0 and ta is not None else None),
            # efficiency and liquidity depth
            "working_capital": (ca - abs(cl)) if (ca is not None and cl is not None) else None,
            "quick_ratio": (round(_safe_div(ca - abs(inv), abs(cl)), 3)
                            if (ca is not None and inv is not None
                                and cl not in (None, 0)) else None),
            "inventory_days": (round(_safe_div(abs(inv) * 365.0, abs(cos)), 1)
                               if (inv is not None and cos not in (None, 0)) else None),
            "receivable_days": (round(_safe_div(abs(recv) * 365.0, rev), 1)
                                if (recv is not None and (rev or 0) > 0) else None),
            # cash quality
            "ocf_to_net_profit": (round(_safe_div(ocf, np_), 3)
                                  if _safe_div(ocf, np_) is not None else None),
            "fcf_margin": _pct(fcf, rev),
            "eps": _at(inc.get("eps"), i),
        })

    # Growth, only between adjacent fiscal years.
    for i in range(len(rows) - 1):
        cur, prv = rows[i], rows[i + 1]
        gap = None
        if cur["fy"] and prv["fy"]:
            gap = cur["fy"] - prv["fy"]
        cur["yearsSincePrior"] = gap
        contiguous = gap == 1
        cur["priorIsAdjacentYear"] = contiguous
        for field, out in (("revenue", "revenue_growth"),
                           ("net_profit", "net_profit_growth"),
                           ("ebit", "ebit_growth"),
                           ("ocf", "ocf_growth")):
            a, b = cur.get(field), prv.get(field)
            # Percentage change off a negative base is not growth: a loss
            # narrowing from -5.8bn to -2.9bn computes to "+50%", which reads as
            # profit rising when the company lost money in both years. Report the
            # direction of travel separately instead of a misleading percentage.
            if contiguous and a is not None and b not in (None, 0) and b > 0:
                cur[out] = round((a - b) / abs(b) * 100, 2)
            else:
                cur[out] = None
            if contiguous and a is not None and b is not None and (b <= 0 or a <= 0):
                cur[out + "_note"] = ("negative in %s%s - percentage change is not "
                                      "meaningful" % (prv["period"] if b <= 0 else cur["period"],
                                                      " and " + cur["period"] if (b <= 0 and a <= 0) else ""))
    if rows:
        rows[-1]["yearsSincePrior"] = None
        rows[-1]["priorIsAdjacentYear"] = None
    return rows


# --------------------------------------------------------------------- flags
def flags(rows):
    """Earnings-quality and balance-sheet warnings, with the numbers behind them.

    Each flag states the evidence so a reader can check it. These are prompts for
    scrutiny, not verdicts - a single year of weak cash conversion can be working
    capital timing, not a problem.
    """
    out = []
    if not rows:
        return out
    cur = rows[0]

    if cur.get("total_equity") is not None and cur["total_equity"] < 0:
        out.append({"id": "negative_equity", "severity": "high",
                    "label": "Negative shareholders' equity",
                    "detail": "Total equity is %.0f - liabilities exceed assets."
                              % cur["total_equity"]})

    npg, ocfg = cur.get("net_profit_growth"), cur.get("ocf_growth")
    profitable = (cur.get("net_profit") or 0) > 0
    if profitable and npg is not None and ocfg is not None and npg > 5 and ocfg < -5:
        out.append({"id": "earnings_cash_divergence", "severity": "high",
                    "label": "Profit rising while operating cash falls",
                    "detail": "Net profit %+.1f%% but operating cash flow %+.1f%% - "
                              "check receivables and revenue recognition."
                              % (npg, ocfg)})

    revg = cur.get("revenue_growth")
    if revg is not None and ocfg is not None and revg > 5 and ocfg < -15:
        out.append({"id": "growth_without_cash", "severity": "high",
                    "label": "Revenue growing while operating cash falls",
                    "detail": "Revenue %+.1f%% but operating cash flow %+.1f%% - "
                              "growth is consuming working capital rather than "
                              "generating it." % (revg, ocfg)})

    conv = [r["ocf_to_net_profit"] for r in rows[:3]
            if r.get("ocf_to_net_profit") is not None and (r.get("net_profit") or 0) > 0]
    if len(conv) >= 2 and all(c < 0.8 for c in conv):
        out.append({"id": "weak_cash_conversion", "severity": "medium",
                    "label": "Persistently weak cash conversion",
                    "detail": "Operating cash flow has been under 80%% of net profit "
                              "for %d straight periods (latest %.2fx)."
                              % (len(conv), conv[0])})

    ic = cur.get("interest_cover")
    if ic is not None and ic < 2:
        out.append({"id": "thin_interest_cover", "severity": "high",
                    "label": "Thin interest cover",
                    "detail": "EBIT covers finance costs only %.2fx." % ic})

    de = cur.get("debt_to_equity")
    if de is not None and de > 2:
        out.append({"id": "high_leverage", "severity": "medium",
                    "label": "High leverage",
                    "detail": "Debt/equity of %.2fx." % de})

    cr = cur.get("current_ratio")
    if cr is not None and cr < 1:
        out.append({"id": "liquidity_pressure", "severity": "medium",
                    "label": "Current liabilities exceed current assets",
                    "detail": "Current ratio %.2f." % cr})

    margins = [r["net_margin"] for r in rows[:3] if r.get("net_margin") is not None]
    if len(margins) >= 3 and margins[0] < margins[1] < margins[2]:
        out.append({"id": "margin_compression", "severity": "low",
                    "label": "Net margin compressing",
                    "detail": "Net margin %.1f%% -> %.1f%% -> %.1f%% (newest first)."
                              % (margins[0], margins[1], margins[2])})

    if cur.get("net_profit") is not None and cur["net_profit"] < 0:
        out.append({"id": "loss_making", "severity": "high",
                    "label": "Loss-making in the latest period",
                    "detail": "Net result of %.0f." % cur["net_profit"]})

    fcfs = [r["fcf"] for r in rows[:3] if r.get("fcf") is not None]
    if len(fcfs) >= 2 and all(f < 0 for f in fcfs):
        out.append({"id": "cash_burn", "severity": "medium",
                    "label": "Sustained negative free cash flow",
                    "detail": "Free cash flow negative in the last %d periods "
                              "(latest %.0f)." % (len(fcfs), fcfs[0])})
    return out


def coverage(doc, rows):
    """How much of the statement we actually have - stated, never papered over."""
    have = {}
    for section in ("income", "balance", "cashflow"):
        keys = doc["sections"].get(section) or {}
        have[section] = sorted(k for k, v in keys.items() if any(x is not None for x in v))
    gaps = [r["period"] for r in rows
            if r.get("yearsSincePrior") not in (None, 1)]
    return {
        "sections": have,
        "periods": doc.get("periods", []),
        "nonContiguousAfter": gaps,
        "missingSections": [s for s in ("income", "balance", "cashflow")
                            if not have.get(s)],
    }


def verify(doc, tolerance=0.02):
    """Internal-consistency checks on the statements themselves.

    Independent of where the numbers came from, and the audit that makes
    model-assisted extraction safe to rely on: if a figure was misread off a
    page, the accounting identities stop holding. A failure means the numbers
    disagree with each other - investigate before trusting any ratio built on them.
    """
    inc = doc["sections"].get("income", {})
    bal = doc["sections"].get("balance", {})
    periods = doc.get("periods") or []
    checks = []

    def _close(a, b):
        if a is None or b is None:
            return None
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) / scale <= tolerance

    for i, p in enumerate(periods):
        ta, tl, te = (_at(bal.get("total_assets"), i), _at(bal.get("total_liabilities"), i),
                      _at(bal.get("total_equity"), i))
        if ta is not None and tl is not None and te is not None:
            ok = _close(ta, tl + te)
            checks.append({"period": p, "check": "assets = liabilities + equity",
                           "ok": ok, "lhs": ta, "rhs": tl + te})
        rev, cos, gp = (_at(inc.get("revenue"), i), _at(inc.get("cost_of_sales"), i),
                        _at(inc.get("gross_profit"), i))
        if rev is not None and cos is not None and gp is not None:
            ok = _close(gp, rev - abs(cos))
            checks.append({"period": p, "check": "gross profit = revenue - cost of sales",
                           "ok": ok, "lhs": gp, "rhs": rev - abs(cos)})
        pbt, tax, np_ = (_at(inc.get("pbt"), i), _at(inc.get("tax"), i),
                         _at(inc.get("net_profit"), i))
        if pbt is not None and tax is not None and np_ is not None:
            expected = pbt - abs(tax)
            ok = _close(np_, expected)
            # This identity legitimately breaks on group accounts: the reported
            # figure is often profit *attributable to owners*, after non-
            # controlling interests, and discontinued operations sit below the
            # line too. A shortfall is therefore normal and only noteworthy;
            # net profit exceeding PBT less tax is the anomaly worth chasing.
            benign = (not ok) and np_ < expected
            checks.append({"period": p, "check": "net profit = PBT - tax",
                           "ok": ok, "lhs": np_, "rhs": expected,
                           "severity": "informational" if benign else "strict",
                           "note": ("shortfall is consistent with non-controlling "
                                    "interests or discontinued operations")
                                   if benign else None})

    # Only strict breaks count as failures; the informational ones are surfaced
    # separately so they prompt a look without crying wolf on every group.
    failed = [c for c in checks
              if c["ok"] is False and c.get("severity") != "informational"]
    noted = [c for c in checks
             if c["ok"] is False and c.get("severity") == "informational"]
    return {"checks": checks, "failed": failed, "noted": noted,
            "passed": len([c for c in checks if c["ok"]]), "total": len(checks)}


def valuation(doc, rows):
    """Market-based ratios for the latest period only.

    Market capitalisation is a snapshot of today. Earnings are a historical
    period. Pairing today's price with FY2023 profit and calling it that year's
    P/E invents a ratio that was never true, so valuation is attached to the
    latest period alone and labelled with the period it was earned against.

    P/E is computed two independent ways when the data allows - market cap over
    net profit, and price over EPS - and the pair is reported. They should agree;
    where they do not, something upstream (a share count, a currency unit, a
    stale market cap) is wrong, and a reader can see that rather than trust one.
    """
    if not rows:
        return None
    e = doc.get("entity", {})
    mcap = _num(e.get("marketCap"))
    shares = _num(e.get("sharesOutstanding"))
    cur = rows[0]
    np_, rev, te = cur.get("net_profit"), cur.get("revenue"), cur.get("total_equity")
    eps = cur.get("eps")
    nd = cur.get("net_debt")

    out = {"asOfPeriod": cur.get("period"), "marketCap": mcap,
           "sharesOutstanding": shares, "basis": "current market cap vs latest reported period"}
    if not mcap:
        out["unavailable"] = "no market capitalisation on file"
        return out

    out["pe"] = round(mcap / np_, 2) if (np_ or 0) > 0 else None
    out["pb"] = round(mcap / te, 2) if (te or 0) > 0 else None
    out["ps"] = round(mcap / rev, 2) if (rev or 0) > 0 else None
    out["earnings_yield"] = round(100.0 * np_ / mcap, 2) if (np_ or 0) > 0 else None
    if shares:
        price = mcap / shares
        out["impliedPrice"] = round(price, 4)
        out["pe_from_eps"] = round(price / eps, 2) if (eps or 0) > 0 else None
        if out["pe"] and out["pe_from_eps"]:
            spread = abs(out["pe"] - out["pe_from_eps"]) / out["pe"]
            out["peCrossCheck"] = ("agree" if spread <= 0.05
                                   else "differ by %.0f%%" % (spread * 100))
    if nd is not None:
        out["enterpriseValue"] = round(mcap + nd, 2)
        ebit = cur.get("ebit")
        out["ev_ebit"] = (round((mcap + nd) / ebit, 2)) if (ebit or 0) > 0 else None
    if (np_ or 0) <= 0:
        out["note"] = "loss-making in the latest period, so P/E is not meaningful"
    return out


def growth(rows):
    """Compound growth across the longest run of consecutive fiscal years."""
    out = {}
    if len(rows) < 2:
        return out
    # rows are newest-first; walk back while the years stay adjacent.
    span = [rows[0]]
    for prev in rows[1:]:
        if prev.get("fy") and span[-1].get("fy") and span[-1]["fy"] - prev["fy"] == 1:
            span.append(prev)
        else:
            break
    years = len(span) - 1
    out["contiguousYears"] = years
    out["from"], out["to"] = (span[-1].get("period"), span[0].get("period")) if years else (None, None)
    if years < 1:
        return out
    for field in ("revenue", "net_profit", "ebit", "ocf"):
        # The oldest contiguous year is often an empty row - the corpus carries
        # period labels it has no figures for - so anchor each field on the
        # oldest year that actually reports it, and record the span used.
        newest = span[0].get(field)
        oldest, back = None, 0
        for k in range(len(span) - 1, 0, -1):
            if span[k].get(field) is not None:
                oldest, back = span[k].get(field), k
                break
        # A CAGR needs both endpoints positive; from a loss to a profit there is
        # no meaningful compound rate, only a change of sign.
        if newest is not None and oldest is not None and newest > 0 and oldest > 0 and back:
            out[field + "_cagr"] = round(((newest / oldest) ** (1.0 / back) - 1) * 100, 2)
            out[field + "_cagr_years"] = back
        else:
            out[field + "_cagr"] = None
    return out


def analyse(doc):
    """Full deterministic read of one entity's statements."""
    rows = compute(doc)
    return {
        "entity": doc["entity"],
        "source": doc.get("source", {}),
        "periods": doc.get("periods", []),
        "metrics": rows,
        "valuation": valuation(doc, rows),
        "growth": growth(rows),
        "flags": flags(rows),
        "coverage": coverage(doc, rows),
        "verification": verify(doc),
    }


if __name__ == "__main__":
    import sys
    tick = sys.argv[1] if len(sys.argv) > 1 else "ABG.JO"
    d = load_public(tick)
    if not d:
        print("no statements for", tick)
        print("try:", ", ".join(available_public()[:12]))
        raise SystemExit(1)
    a = analyse(d)
    e = a["entity"]
    print("%s - %s (%s)" % (e["ticker"], e["name"], e.get("currency")))
    print("periods:", ", ".join(a["periods"]))
    for r in a["metrics"]:
        print("  %-8s rev %14s  net %13s  margin %7s  roe %7s  ocf/np %6s  rev g %8s"
              % (r["period"],
                 "%.0f" % r["revenue"] if r["revenue"] is not None else "-",
                 "%.0f" % r["net_profit"] if r["net_profit"] is not None else "-",
                 "%.1f%%" % r["net_margin"] if r["net_margin"] is not None else "-",
                 "%.1f%%" % r["roe"] if r["roe"] is not None else "-",
                 "%.2f" % r["ocf_to_net_profit"] if r["ocf_to_net_profit"] is not None else "-",
                 "%+.1f%%" % r["revenue_growth"] if r.get("revenue_growth") is not None else "-"))
    for f in a["flags"]:
        print("  [%s] %s - %s" % (f["severity"].upper(), f["label"], f["detail"]))
    print("  coverage:", a["coverage"]["sections"])
