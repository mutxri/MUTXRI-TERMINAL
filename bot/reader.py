#!/usr/bin/env python3
"""bot/reader.py - reading a set of accounts the way an analyst does.

`analyse` produces the numbers. This puts them in the order a professional
reads financial statements and says what each one means for this company:

   1. can the numbers be trusted
   2. income statement - growth, margins, where the revenue goes
   3. balance sheet - liquidity, leverage, capital strength
   4. cash flow - whether profit arrives as cash, and how the company is funded
   5. returns - whether it earns more than its capital costs, and why (DuPont)
   6. efficiency - how hard assets and working capital are used
   7. earnings quality - accruals and manipulation screens
   8. distress and strength - Altman, Piotroski
   9. valuation - what the market pays, against the government yield

Every judgement here is a rule of thumb applied to a computed number, and each
states its evidence. The thresholds are conventions, not laws: a supermarket runs
a current ratio below 1 on purpose, and a bank has no current ratio at all. So
the company is classified first (general, bank, insurer, property, other
financial) and ratios that mean nothing for that kind of business are not
judged.

Returns are compared with the shortest government yield on file for that market
(bonds.json). It is a floor, not the cost of equity: a company earning less than
a treasury bill on its equity is not paying shareholders for any risk at all.
"""
from . import fixed_income as FI, models as M, statements as S, universe as U

GUIDE = [
    ("Check the numbers can be trusted",
     "Start with whether the statements agree with themselves: assets equal liabilities "
     "plus equity, gross profit is revenue less cost of sales, the three cash flow sections "
     "sum to the change in cash. Note missing statements, gaps between years, restatements "
     "and the units the figures are in. Every later ratio inherits these problems."),
    ("Know what kind of business it is",
     "A bank's revenue is interest, its raw material is deposits, and its balance sheet is "
     "mostly loans; an insurer earns premiums and pays claims. Current ratios, gross "
     "margins and Z-scores were built for companies that make and sell things and mislead "
     "when applied to financials. Pick the ratios that fit the model."),
    ("Income statement: is it growing, and what does it keep",
     "Revenue growth first, and in high-inflation currencies compare it with inflation "
     "before calling it growth. Then walk down the margins: gross (pricing power over direct "
     "costs), operating (cost discipline), pre-tax (the burden of debt), net (what "
     "shareholders keep). Express each cost as a share of revenue to see where the money "
     "goes, and watch the direction over several years more than any single level. An "
     "unusual tax rate is a question to answer."),
    ("Balance sheet: what it owns, what it owes",
     "Liquidity (current, quick and cash ratios) says whether the next twelve months of "
     "obligations are covered. Solvency (debt to equity, net debt to EBITDA, interest cover) "
     "says whether the debt can be carried and refinanced. The equity ratio shows how much "
     "of the asset base shareholders actually fund. Negative equity means liabilities "
     "exceed assets."),
    ("Cash flow: is the profit real",
     "Operating cash flow should broadly match or exceed net profit over time; a persistent "
     "shortfall means profit is sitting in receivables, inventory or accounting estimates. "
     "Free cash flow is what is left after investment. Capex below depreciation for long "
     "means the asset base is being run down. The signs of operating, investing and financing "
     "flows show the life-cycle stage. A dividend larger than free cash flow is being "
     "borrowed or drawn from reserves."),
    ("Returns: does it create value",
     "ROE, ROA, ROCE and ROIC say how much profit each unit of capital earns. Compare them "
     "with the cost of that capital; the government bill yield is the floor. DuPont splits ROE "
     "into tax burden, interest burden, operating margin, asset turnover and leverage, which "
     "shows whether a return comes from running the business well or from borrowing."),
    ("Efficiency: how hard the assets work",
     "Asset turnover and the working-capital days (inventory, receivables, payables and the "
     "cash conversion cycle) show how much capital the business ties up to produce its "
     "revenue. Rising receivable days mean customers are paying more slowly."),
    ("Earnings quality",
     "Accruals (profit less operating cash, over assets) and the Beneish M-score look for the "
     "patterns that precede earnings disappointments and manipulation. They are screens that "
     "tell you which notes to read, not verdicts."),
    ("Distress and strength",
     "The Altman Z-score family estimates distress risk from working capital, retained "
     "earnings, operating profit and leverage; the Piotroski F-Score counts improving "
     "fundamentals. Use the variant built for the company: emerging-market, listed "
     "manufacturer, or private firm."),
    ("Valuation",
     "Price to earnings, to book, to sales and EV to EBIT(DA) say what the market pays. The "
     "earnings yield (the inverse of P/E) set beside the government bond yield shows how much "
     "growth the price already assumes."),
    ("Compare",
     "No ratio means much alone. Set it against the company's own history and its sector "
     "peers (`peers`), and read the notes behind any figure that moves sharply."),
]

BANK_WORDS = ("bank", "banking", "microfinance", "mortgage finance")
INSURER_WORDS = ("insur", "assurance", "reinsur", "takaful")
PROPERTY_WORDS = ("real estate", "property", "properties", "reit")
FINANCIAL_WORDS = ("financial services", "finance", "investment", "asset management",
                   "capital markets", "brokerage")
HIGH_INFLATION = {"NGN", "EGP"}

QUESTIONS = {
    "integrity": "Which figures disagree with each other, and has the filing been restated?",
    "revenue_growth": "Is the decline in volume, price or customers, and in which segments?",
    "margin": "Which costs grew faster than revenue, and are they one-off or structural?",
    "effective_tax_rate": "What explains the tax rate: disallowed costs, losses in some "
                          "entities, incentives or prior-year adjustments?",
    "current_ratio": "How will short-term obligations be met, and are facilities in place?",
    "quick_ratio": "How much of current assets is stock that may not sell quickly?",
    "working_capital": "Is negative working capital deliberate (suppliers funding stock) "
                       "or a sign of strain?",
    "debt_to_equity": "When does the debt mature, at what rates, and in which currency?",
    "net_debt_to_ebitda": "Can earnings carry this debt if rates stay where they are?",
    "interest_cover": "Can operating profit carry the finance costs if rates stay high?",
    "equity_ratio": "Is there enough capital to absorb losses?",
    "ocf_to_net_profit": "What is absorbing the cash: receivables, inventory, or revenue "
                         "booked before it is collected?",
    "fcf": "How is the cash shortfall funded, and for how long can it be?",
    "capex_to_depreciation": "Is the asset base being maintained, or investment deferred "
                             "to protect cash?",
    "dividend": "Why does the dividend exceed what the business generates, and how is the "
                "gap funded?",
    "lifecycle": "Which assets are being sold, and what replaces the cash they produced?",
    "roe": "What would lift returns above the cost of capital: margin, asset use or leverage?",
    "roce": "Which parts of the business earn below the cost of capital?",
    "sustainable_growth": "How will growth beyond the self-funding rate be financed?",
    "receivable_days": "Why are customers taking longer to pay?",
    "inventory_days": "Is stock building because sales slowed?",
    "accruals": "Which estimates or working-capital movements explain profit exceeding cash?",
    "beneish": "What do the notes say about receivables, depreciation policy and accruals?",
    "altman": "What is the refinancing plan, and do lenders' covenants still hold?",
    "piotroski": "Which of the deteriorating fundamentals is management addressing?",
    "loan_to_deposit": "How is lending beyond the deposit base funded, and at what cost?",
    "cost_of_risk": "Which loan books are driving impairments?",
    "combined_ratio": "Which lines are losing money on underwriting?",
    "loss_making": "What is the path back to profit, and how long does the cash last?",
    "negative_equity": "Who is supporting the company while liabilities exceed assets?",
    "earnings_yield": "What growth is the market pricing in, and is it plausible?",
}

_UNI = {}


def _big(v):
    if not isinstance(v, (int, float)):
        return "-"
    a = abs(v)
    for cut, suf in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if a >= cut:
            return "%.2f%s" % (v / cut, suf)
    return "%.2f" % v


def _fmt(v, unit):
    if not isinstance(v, (int, float)):
        return "-"
    return {"%": "%.2f%%", "x": "%.2fx", "d": "%.1f days", "pp": "%+.2f pp",
            "": "%.2f"}.get(unit, "%.2f") % v if unit != "n" else _big(v)


def _find(metric, label, value, reading, verdict="neutral", unit="", question=None):
    return {"metric": metric, "label": label, "value": value, "display": _fmt(value, unit),
            "verdict": verdict, "reading": reading, "question": question}


def _listing(entity):
    """Sector and exchange from the listing, when the statement does not carry them."""
    if entity.get("kind") != "public" or not entity.get("ticker"):
        return entity.get("sector"), entity.get("exchange")
    if not _UNI:
        try:
            _UNI.update(U.load())
        except Exception:
            pass
    t = str(entity["ticker"]).upper()
    base = t[:-3] if t.endswith((".JO", ".CA")) else t
    for ex, rows in _UNI.items():
        if entity.get("exchange") and ex != entity["exchange"]:
            continue
        for r in rows:
            rt = str(r.get("ticker") or "").upper()
            if (rt[:-3] if rt.endswith((".JO", ".CA")) else rt) == base:
                return entity.get("sector") or r.get("sector"), entity.get("exchange") or ex
    return entity.get("sector"), entity.get("exchange")


def classify(entity, sector):
    text = ("%s %s" % (sector or "", entity.get("name") or "")).lower()
    for kind, words in (("bank", BANK_WORDS), ("insurer", INSURER_WORDS),
                        ("property", PROPERTY_WORDS), ("financial", FINANCIAL_WORDS)):
        hit = next((w for w in words if w in text), None)
        if hit:
            return kind, "'%s' in the sector or name" % hit
    return "general", "no financial, insurance or property marker in the sector or name"


def _is_fin(kind):
    return kind in ("bank", "insurer", "financial")


def _prior(rows):
    if len(rows) > 1 and rows[0].get("priorIsAdjacentYear"):
        return rows[1]
    return None


def _num(v):
    return isinstance(v, (int, float))


# ----------------------------------------------------------------- sections
def _integrity(a, rows):
    out = []
    v = a.get("verification") or {}
    if v.get("total"):
        failed = v.get("failed") or []
        noted = len(v.get("noted") or [])
        strict = v["total"] - noted
        out.append(_find("integrity", "accounting identities", v["passed"],
                         "%d of %d identities hold%s%s." % (
                             v["passed"], strict,
                             "" if not failed else "; failing: " + "; ".join(
                                 "%s in %s" % (c["check"], c["period"]) for c in failed[:3]),
                             "" if not noted else "; %d further difference%s of a kind that is "
                             "normal, noted below" % (noted, "" if noted == 1 else "s")),
                         "concern" if failed else "strength", "",
                         QUESTIONS["integrity"] if failed else None))
        out[-1]["display"] = "%d/%d" % (v["passed"], strict)
        for c in (v.get("noted") or [])[:2]:
            out.append(_find("integrity", "identity note", None,
                             "%s in %s: %s." % (c["check"], c["period"], c.get("note") or
                                                "difference unexplained"), "info"))
    cov = a.get("coverage") or {}
    for sec in cov.get("missingSections") or []:
        out.append(_find("coverage", "missing statement", None,
                         "No %s statement: everything that depends on it is not assessed." % sec,
                         "concern"))
    if cov.get("nonContiguousAfter"):
        out.append(_find("coverage", "gaps between years", None,
                         "Periods are not consecutive after %s, so growth across the gap is "
                         "not computed." % ", ".join(cov["nonContiguousAfter"]), "info"))
    cur = rows[0] if rows else {}
    if cur.get("ebit_derived"):
        out.append(_find("coverage", "EBIT rebuilt", None,
                         "Operating profit was not reported; it is rebuilt as profit before "
                         "tax plus net finance costs.", "info"))
    if cur.get("current_split_derived"):
        out.append(_find("coverage", "current split derived", None,
                         "Current assets or liabilities were derived as the total less the "
                         "non-current portion.", "info"))
    if len(rows) < 2:
        out.append(_find("coverage", "single period", None,
                         "Only one period is on file, so no trend can be read.", "info"))
    return out


def _income(a, rows, kind, currency):
    out = []
    cur, prv = rows[0], _prior(rows)
    g = cur.get("revenue_growth")
    grow = a.get("growth") or {}
    if _num(cur.get("revenue")):
        txt = "Revenue of %s in %s" % (_big(cur["revenue"]), cur["period"])
        verdict = "neutral"
        if _num(g):
            txt += ", %+.1f%% on %s" % (g, prv["period"] if prv else "the prior year")
            verdict = "strength" if g > 10 else ("concern" if g < 0 else "neutral")
        if _num(grow.get("revenue_cagr")) and (grow.get("revenue_cagr_years") or 0) >= 2:
            txt += "; %.1f%% a year compounded over %d years" % (
                grow["revenue_cagr"], grow.get("revenue_cagr_years") or 0)
        txt += "."
        if (currency or "").upper() in HIGH_INFLATION:
            txt += (" This is nominal growth in %s, where inflation has been high; compare "
                    "it with inflation before reading it as real growth." % currency)
            if verdict == "strength":
                verdict = "neutral"
        out.append(_find("revenue_growth", "revenue", g, txt, verdict, "%" if _num(g) else "",
                         QUESTIONS["revenue_growth"] if verdict == "concern" else None))
    npg = cur.get("net_profit_growth")
    if _num(npg):
        out.append(_find("net_profit_growth", "net profit growth", npg,
                         "Net profit %+.1f%% year on year%s." % (
                             npg, " while revenue moved %+.1f%%" % g if _num(g) else ""),
                         "strength" if npg > 10 else ("concern" if npg < -10 else "neutral"), "%"))
    elif cur.get("net_profit_growth_note"):
        out.append(_find("net_profit_growth", "net profit growth", None,
                         "Not a meaningful percentage: net profit was %s." %
                         cur["net_profit_growth_note"], "info"))

    margins = [("gross_margin", "gross margin", "after direct costs of sales")] if kind == "general" else []
    margins += [("ebit_margin", "operating margin", "after all operating costs"),
                ("pretax_margin", "pre-tax margin", "after finance costs"),
                ("net_margin", "net margin", "for shareholders after finance costs and tax")]
    for key, label, what in margins:
        m = cur.get(key)
        if not _num(m):
            continue
        hist = [r.get(key) for r in rows[:4] if _num(r.get(key))]
        txt = "%s of %.1f%%: each 100 of revenue leaves %.1f %s." % (
            label.capitalize(), m, m, what)
        verdict = "concern" if m < 0 else "neutral"
        if prv and _num(prv.get(key)):
            d = m - prv[key]
            txt += " %+.1f percentage points on %s." % (d, prv["period"])
            if d >= 1 and m > 0:
                verdict = "strength"
            elif d <= -2:
                verdict = "concern"
        if len(hist) >= 3:
            txt += " Trend, newest first: %s." % ", ".join("%.1f%%" % h for h in hist)
        out.append(_find(key, label, m, txt, verdict, "%",
                         QUESTIONS["margin"] if verdict == "concern" else None))

    rev = cur.get("revenue")
    if _num(rev) and rev > 0:
        parts = [(n, cur.get(k)) for n, k in (("cost of sales", "cost_of_sales"),
                                              ("operating expenses", "operating_expenses"),
                                              ("finance costs", "net_finance_costs"),
                                              ("tax", "tax"))]
        parts = [(n, abs(v) / rev * 100) for n, v in parts if _num(v)]
        if parts:
            out.append(_find("common_size", "where revenue goes", None,
                             "As a share of revenue: " + ", ".join("%s %.1f%%" % p for p in parts)
                             + ".", "info"))
    etr = cur.get("effective_tax_rate")
    if _num(etr):
        if etr < 10:
            v, t = "info", ("unusually low: tax losses brought forward, incentives or exempt "
                            "income")
        elif etr > 40:
            v, t = "concern", ("high: costs the tax authority does not allow, or losses in "
                               "some entities that cannot be offset")
        else:
            v, t = "neutral", "within the normal range for corporate tax"
        out.append(_find("effective_tax_rate", "effective tax rate", etr,
                         "Tax of %.1f%% of pre-tax profit is %s." % (etr, t), v, "%",
                         QUESTIONS["effective_tax_rate"] if v == "concern" else None))
    return out


def _balance(a, rows, kind, models):
    out = []
    cur = rows[0]
    if kind in ("general", "property"):
        cr = cur.get("current_ratio")
        if _num(cr):
            if cr < 1:
                v, t = "concern", "short-term obligations exceed short-term assets"
            elif cr < 1.5:
                v, t = "neutral", "short-term assets cover obligations, without much room"
            elif cr <= 3:
                v, t = "strength", "comfortable cover for the next twelve months"
            else:
                v, t = "neutral", "high enough that cash or stock may be sitting idle"
            out.append(_find("current_ratio", "current ratio", cr,
                             "Current ratio %.2f: %s." % (cr, t), v, "",
                             QUESTIONS["current_ratio"] if v == "concern" else None))
        qr = cur.get("quick_ratio")
        if _num(qr):
            out.append(_find("quick_ratio", "quick ratio", qr,
                             "Excluding stock, liquid assets cover %.2fx current liabilities." % qr,
                             "concern" if qr < 0.8 else ("strength" if qr >= 1 else "neutral"), "",
                             QUESTIONS["quick_ratio"] if qr < 0.8 else None))
        cash_r = cur.get("cash_ratio")
        if _num(cash_r):
            out.append(_find("cash_ratio", "cash ratio", cash_r,
                             "Cash alone covers %.2fx current liabilities." % cash_r, "info"))
        wc = cur.get("working_capital")
        if _num(wc) and wc < 0:
            out.append(_find("working_capital", "working capital", wc,
                             "Negative working capital of %s. Retailers run this deliberately, "
                             "with suppliers funding stock; elsewhere it signals strain." % _big(wc),
                             "concern" if kind == "general" and (cur.get("current_ratio") or 1) < 0.8
                             else "neutral", "n", QUESTIONS["working_capital"]))
    else:
        out.append(_find("liquidity", "liquidity ratios", None,
                         "Current and quick ratios are not judged for a %s: its balance sheet "
                         "is mostly financial assets and liabilities without a current split "
                         "that means the same thing." % kind, "info"))

    if kind not in ("bank", "insurer"):
        de = cur.get("debt_to_equity")
        if _num(de):
            v = "concern" if de > 2 else ("strength" if de < 0.5 else "neutral")
            out.append(_find("debt_to_equity", "debt to equity", de,
                             "Borrowings are %.2fx shareholders' equity." % de, v, "x",
                             QUESTIONS["debt_to_equity"] if v == "concern" else None))
        nde = cur.get("net_debt_to_ebitda")
        nd = cur.get("net_debt")
        if _num(nd) and nd < 0:
            out.append(_find("net_debt", "net cash", nd,
                             "Cash exceeds borrowings by %s: a net cash position." % _big(-nd),
                             "strength", "n"))
        elif _num(nde):
            v = "strength" if nde < 1 else ("neutral" if nde <= 3 else "concern")
            out.append(_find("net_debt_to_ebitda", "net debt to EBITDA", nde,
                             "Net debt is %.2f years of EBITDA%s." % (
                                 nde, "; above 3 lenders start to worry" if nde > 3 else ""),
                             v, "x", QUESTIONS["net_debt_to_ebitda"] if v == "concern" else None))
        ic = cur.get("interest_cover")
        if _num(ic):
            if ic < 2:
                v, t = "concern", "most operating profit goes to lenders"
            elif ic <= 5:
                v, t = "neutral", "adequate, with limited room if profit falls or rates rise"
            else:
                v, t = "strength", "finance costs are comfortably covered"
            out.append(_find("interest_cover", "interest cover", ic,
                             "Operating profit covers finance costs %.2fx: %s." % (ic, t), v, "x",
                             QUESTIONS["interest_cover"] if v == "concern" else None))
    eq = cur.get("equity_ratio")
    if _num(eq):
        if kind == "bank":
            v = "concern" if eq < 8 else ("strength" if eq > 15 else "neutral")
            t = ("Equity funds %.1f%% of assets. Banks run on 8-15%%; below 8%% there is little "
                 "to absorb loan losses." % eq)
        elif kind == "insurer":
            v, t = "info", "Equity funds %.1f%% of assets." % eq
        else:
            v = "concern" if eq < 25 else ("strength" if eq > 50 else "neutral")
            t = "Shareholders fund %.1f%% of the asset base; lenders and creditors the rest." % eq
        out.append(_find("equity_ratio", "equity ratio", eq, t, v, "%",
                         QUESTIONS["equity_ratio"] if v == "concern" else None))
    if kind == "bank":
        ldr = cur.get("loan_to_deposit")
        if _num(ldr):
            v = "concern" if ldr > 100 else ("info" if ldr < 50 else "neutral")
            out.append(_find("loan_to_deposit", "loan to deposit", ldr,
                             "Loans are %.1f%% of customer deposits%s." % (
                                 ldr, ": lending beyond deposits relies on wholesale funding"
                                 if ldr > 100 else (": much of the deposit base is not lent out"
                                                    if ldr < 50 else "")), v, "%",
                             QUESTIONS["loan_to_deposit"] if v == "concern" else None))
        cor = cur.get("cost_of_risk")
        if _num(cor):
            out.append(_find("cost_of_risk", "cost of risk", cor,
                             "Impairments are %.2f%% of loans." % cor,
                             "concern" if cor > 3 else "neutral", "%",
                             QUESTIONS["cost_of_risk"] if cor > 3 else None))
        cti = (models.get("costToIncome") or {})
        if cti.get("available"):
            out.append(_find("cost_to_income", "cost to income", cti["ratio"],
                             "Operating costs take %.1f%% of income (%s)." % (
                                 cti["ratio"], cti["reading"]),
                             {"strong": "strength", "heavy": "concern"}.get(cti["reading"],
                                                                            "neutral"), "%"))
    if kind == "insurer":
        comb = cur.get("combined_ratio")
        if _num(comb):
            v = "concern" if comb > 100 else ("strength" if comb < 95 else "neutral")
            out.append(_find("combined_ratio", "combined ratio", comb,
                             "Claims and expenses are %.1f%% of earned premium%s." % (
                                 comb, ": an underwriting loss, so profit depends on investment "
                                 "income" if comb > 100 else ""), v, "%",
                             QUESTIONS["combined_ratio"] if v == "concern" else None))
    return out


LIFECYCLE = {
    (False, False, True): ("introduction", "info",
                           "operations and investment are both funded by raising capital"),
    (True, False, True): ("growth", "neutral",
                          "operating cash plus new funding pays for investment"),
    (True, False, False): ("mature", "strength",
                           "operations fund investment and payments to lenders and shareholders"),
    (False, True, True): ("decline", "concern",
                          "asset sales and new funding are covering an operating cash outflow"),
    (False, True, False): ("decline", "concern",
                           "asset sales are covering an operating cash outflow and repayments"),
}


def lifecycle(ocf, icf, financing):
    """Dickinson (2011) life-cycle stage from the signs of the three cash flows."""
    if not all(_num(x) for x in (ocf, icf, financing)):
        return None
    key = (ocf > 0, icf > 0, financing > 0)
    stage, verdict, why = LIFECYCLE.get(key, ("shake-out", "neutral",
                                              "the pattern of a business in transition"))
    return {"stage": stage, "verdict": verdict, "why": why,
            "signs": "operating %s, investing %s, financing %s" % tuple(
                "+" if s else "-" for s in key)}


def _cash(a, rows, kind):
    out = []
    cur = rows[0]
    np_, ocf = cur.get("net_profit"), cur.get("ocf")
    conv = cur.get("ocf_to_net_profit")
    if _num(np_) and np_ > 0 and _num(conv):
        v = "strength" if conv >= 1 else ("neutral" if conv >= 0.8 else "concern")
        out.append(_find("ocf_to_net_profit", "cash conversion", conv,
                         "Operating cash flow is %.2fx net profit%s." % (
                             conv, ": profit is arriving as cash" if conv >= 1 else
                             ": part of the profit has not turned into cash"), v, "x",
                         QUESTIONS["ocf_to_net_profit"] if v == "concern" else None))
    elif _num(np_) and np_ <= 0 and _num(ocf) and ocf > 0:
        out.append(_find("ocf_to_net_profit", "cash conversion", None,
                         "A loss, but operating cash flow of %s: non-cash charges such as "
                         "depreciation or impairments explain the gap." % _big(ocf), "info"))
    fcf = cur.get("fcf")
    if _num(fcf) and not _is_fin(kind):
        v = "strength" if fcf > 0 else "concern"
        out.append(_find("fcf", "free cash flow", fcf,
                         "Free cash flow of %s%s." % (_big(fcf), " (%.1f%% of revenue)" %
                                                      cur["fcf_margin"] if _num(cur.get("fcf_margin"))
                                                      else ""), v, "n",
                         QUESTIONS["fcf"] if v == "concern" else None))
    cd = cur.get("capex_to_depreciation")
    if _num(cd):
        v = "concern" if cd < 0.8 else "neutral"
        out.append(_find("capex_to_depreciation", "capex to depreciation", cd,
                         "Investment is %.2fx depreciation%s." % (
                             cd, ": less than the assets wear out" if cd < 1 else
                             (": expanding the asset base" if cd > 1.5 else "")), v, "x",
                         QUESTIONS["capex_to_depreciation"] if v == "concern" else None))
    ci = cur.get("capex_to_revenue")
    if _num(ci):
        out.append(_find("capex_to_revenue", "capital intensity", ci,
                         "Capital expenditure is %.1f%% of revenue." % ci, "info", "%"))
    life = lifecycle(ocf, cur.get("icf"), cur.get("financing_cf"))
    if life:
        if _is_fin(kind):
            out.append(_find("lifecycle", "cash flow pattern", None,
                             "%s. For a %s, deposits, loans and investments run through the "
                             "operating and investing lines, so the life-cycle reading does not "
                             "apply." % (life["signs"].capitalize(), kind), "info"))
        else:
            out.append(_find("lifecycle", "life-cycle stage", None,
                             "%s: a %s pattern - %s." % (life["signs"].capitalize(),
                                                          life["stage"], life["why"]),
                             life["verdict"], "",
                             QUESTIONS["lifecycle"] if life["verdict"] == "concern" else None))
            out[-1]["display"] = life["stage"]
    payout = cur.get("dividend_payout")
    div = cur.get("dividends_paid")
    if _num(payout):
        v = "concern" if payout > 100 else "neutral"
        out.append(_find("dividend_payout", "dividend payout", payout,
                         "Dividends paid are %.1f%% of net profit%s." % (
                             payout, ": more than the year earned" if payout > 100 else ""),
                         v, "%", QUESTIONS["dividend"] if v == "concern" else None))
    if _num(div) and _num(fcf) and fcf > 0 and abs(div) > fcf:
        out.append(_find("dividend_vs_fcf", "dividend vs free cash flow", abs(div) / fcf,
                         "Dividends of %s exceed free cash flow of %s, so part is funded by "
                         "borrowing or reserves." % (_big(abs(div)), _big(fcf)), "concern", "x",
                         QUESTIONS["dividend"]))
    return out


def _returns(a, rows, kind, rf):
    out = []
    cur, prv = rows[0], _prior(rows)
    rf_txt = None
    if rf:
        rf_txt = "the %s yield of %.2f%% (%s%s)" % (rf["instrument"], rf["yieldPct"], rf["asOf"],
                                                   ", stale" if rf.get("stale") else "")
    for key, label, what in (("roe", "return on equity", "shareholders' equity"),
                             ("roce", "return on capital employed", "capital employed"),
                             ("roic", "return on invested capital", "invested capital, after tax")):
        v_ = cur.get(key)
        if not _num(v_):
            continue
        if key != "roe" and _is_fin(kind):
            continue
        txt = "%s of %.2f%%" % (label.capitalize(), v_)
        if rf:
            if v_ < rf["yieldPct"]:
                verdict = "concern"
                txt += ", below %s: capital earns less than government paper carrying no " \
                       "equity risk" % rf_txt
            elif v_ >= rf["yieldPct"] + 5:
                verdict = "strength"
                txt += ", more than 5 points above %s" % rf_txt
            else:
                verdict = "neutral"
                txt += ", above %s but by less than a typical equity risk premium" % rf_txt
        else:
            verdict = "concern" if v_ < 5 else ("strength" if v_ >= 15 else "neutral")
        basis = cur.get("capital_employed_basis") or ""
        if key in ("roce", "roic") and basis.startswith("equity only"):
            txt += ("; measured on equity alone because no borrowings line is reported, so it "
                    "overstates the return on all capital")
            verdict = "info"
        elif key == "roce" and basis:
            txt += " (capital employed: %s)" % basis
        out.append(_find(key, label, v_, txt + ".", verdict, "%",
                         QUESTIONS[key if key in QUESTIONS else "roce"]
                         if verdict == "concern" else None))
    roa = cur.get("roa")
    if _num(roa):
        if kind == "bank":
            v = "strength" if roa >= 1.5 else ("concern" if roa < 0.5 else "neutral")
        else:
            v = "strength" if roa >= 8 else ("concern" if roa < 2 else "neutral")
        out.append(_find("roa", "return on assets", roa,
                         "Net profit is %.2f%% of total assets%s." % (
                             roa, "; banks are judged against about 1%" if kind == "bank" else ""),
                         v, "%"))

    factors = [("tax_burden", "tax burden", ""), ("interest_burden", "interest burden", ""),
               ("ebit_margin", "operating margin", "%"), ("asset_turnover", "asset turnover", "x"),
               ("equity_multiplier", "leverage", "x")]
    if all(_num(cur.get(k)) for k, _, _ in factors) and _num(cur.get("roe")):
        disp = " x ".join(_fmt(cur[k], u) for k, _, u in factors)
        txt = "ROE %.2f%% = tax burden x interest burden x operating margin x asset turnover x " \
              "leverage = %s." % (cur["roe"], disp)
        if prv and all(_num(prv.get(k)) and prv.get(k) for k, _, _ in factors) and _num(prv.get("roe")):
            import math
            moves = []
            for k, name, u in factors:
                if cur[k] > 0 and prv[k] > 0:
                    moves.append((abs(math.log(cur[k] / prv[k])), name, prv[k], cur[k], u))
            if moves:
                moves.sort(reverse=True)
                _, name, p, c_, u = moves[0]
                txt += " Against %s (ROE %.2f%%), the biggest change was %s, from %s to %s." % (
                    prv["period"], prv["roe"], name, _fmt(p, u), _fmt(c_, u))
        out.append(_find("dupont", "DuPont (five-step)", cur["roe"], txt, "info", "%"))
    elif all(_num(cur.get(k)) for k in ("net_margin", "asset_turnover", "equity_multiplier", "roe")):
        out.append(_find("dupont", "DuPont (three-step)", cur["roe"],
                         "ROE %.2f%% = net margin %.2f%% x asset turnover %.2fx x leverage %.2fx."
                         % (cur["roe"], cur["net_margin"], cur["asset_turnover"],
                            cur["equity_multiplier"]), "info", "%"))
    sgr = cur.get("sustainable_growth")
    if _num(sgr):
        g = cur.get("revenue_growth")
        over = _num(g) and g > sgr + 5
        out.append(_find("sustainable_growth", "sustainable growth", sgr,
                         "Retaining %.0f%% of profit at this ROE funds about %.1f%% growth a year "
                         "without new equity or more leverage%s." % (
                             cur.get("retention_ratio") or 0, sgr,
                             "; revenue is growing faster (%+.1f%%)" % g if over else ""),
                         "concern" if over else "info", "%",
                         QUESTIONS["sustainable_growth"] if over else None))
    return out


def _efficiency(a, rows, kind):
    if _is_fin(kind):
        return []
    out = []
    cur, prv = rows[0], _prior(rows)
    for key, label, unit, txt in (
            ("asset_turnover", "asset turnover", "x", "Each unit of assets produces %.2f of revenue."),
            ("non_current_asset_turnover", "non-current asset turnover", "x",
             "Each unit of long-term assets produces %.2f of revenue.")):
        v_ = cur.get(key)
        if _num(v_):
            extra = ""
            if prv and _num(prv.get(key)):
                extra = " (%s: %.2f)" % (prv["period"], prv[key])
            out.append(_find(key, label, v_, (txt % v_) + extra, "info", unit))
    for key, label, bad_up in (("inventory_days", "inventory days", True),
                               ("receivable_days", "receivable days", True),
                               ("payable_days", "payable days", False)):
        v_ = cur.get(key)
        if not _num(v_):
            continue
        verdict, extra = "neutral", ""
        if prv and _num(prv.get(key)) and prv[key] > 0:
            ch = (v_ / prv[key] - 1) * 100
            extra = ", %+.0f%% on %s" % (ch, prv["period"])
            if bad_up and ch > 10:
                verdict = "concern"
        out.append(_find(key, label, v_, "%s of %.0f%s." % (label.capitalize(), v_, extra),
                         verdict, "d", QUESTIONS.get(key) if verdict == "concern" else None))
    ccc = cur.get("cash_conversion_cycle")
    if _num(ccc):
        out.append(_find("cash_conversion_cycle", "cash conversion cycle", ccc,
                         "Cash is tied up for %.0f days between paying suppliers and collecting "
                         "from customers%s." % (ccc, " (suppliers fund the cycle)" if ccc < 0 else ""),
                         "info", "d"))
    return out


def _quality(a, rows, models, kind):
    out = []
    acc = models.get("accruals") or {}
    if acc.get("available"):
        rd = acc["reading"]
        v = "concern" if rd.startswith("high") else ("strength" if rd == "cash-backed" else "neutral")
        out.append(_find("accruals", "accruals (Sloan)", acc["ratio"],
                         "Profit less operating cash is %.2f%% of %s: %s." % (
                             acc["ratio"], acc["basis"], rd), v, "%",
                         QUESTIONS["accruals"] if v == "concern" else None))
    ben = models.get("beneish") or {}
    if ben.get("available"):
        v = "concern" if ben["likelyManipulator"] else "strength"
        out.append(_find("beneish", "Beneish M-score", ben["score"],
                         "M-score %.2f, %s the -1.78 threshold%s." % (
                             ben["score"], "above" if ben["likelyManipulator"] else "below",
                             ": the pattern associated with earnings manipulation, which is a "
                             "reason to read the notes, not proof" if ben["likelyManipulator"]
                             else ""), v, "", QUESTIONS["beneish"] if v == "concern" else None))
    for f in a.get("flags") or []:
        if f["id"] in ("earnings_cash_divergence", "growth_without_cash"):
            out.append(_find(f["id"], f["label"].lower(), None, f["detail"], "concern", "",
                             QUESTIONS["ocf_to_net_profit"]))
    return out


def _distress(a, rows, models, kind):
    out = []
    if _is_fin(kind):
        out.append(_find("altman", "Z-scores", None,
                         "Not applied: the Altman models were built on non-financial companies, "
                         "and a %s's leverage would read as distress by design." % kind, "info"))
    else:
        for key, label in (("altmanZ", "Altman Z'' (emerging markets)"),
                           ("altmanZOriginal", "Altman Z (listed)"),
                           ("altmanZPrivate", "Altman Z' (private)")):
            z = models.get(key) or {}
            if not z.get("available"):
                continue
            v = {"safe": "strength", "distress": "concern"}.get(z["band"], "neutral")
            out.append(_find("altman", label, z["score"],
                             "%s of %.2f, in the %s zone." % (label, z["score"], z["band"]), v, "",
                             QUESTIONS["altman"] if v == "concern" else None))
    pio = models.get("piotroski") or {}
    if pio.get("available"):
        v = {"strong": "strength", "weak": "concern"}.get(pio.get("reading"), "neutral")
        failed = [s["label"] for s in pio["signals"] if s["passed"] is False]
        out.append(_find("piotroski", "Piotroski F-Score", pio["score"],
                         "%d of %d measurable signals pass (%s)%s." % (
                             pio["score"], pio["outOf"], pio.get("reading"),
                             "; failing: " + "; ".join(failed) if failed else ""), v, "",
                         QUESTIONS["piotroski"] if v == "concern" else None))
        out[-1]["display"] = "%d/%d" % (pio["score"], pio["outOf"])
    for f in a.get("flags") or []:
        if f["id"] in ("loss_making", "negative_equity"):
            out.append(_find(f["id"], f["label"].lower(), None, f["detail"], "concern", "",
                             QUESTIONS[f["id"]]))
    return out


def _valuation(a, models, rf):
    out = []
    val = a.get("valuation") or {}
    if not val.get("marketCap"):
        return out
    parts = [("P/E", val.get("pe")), ("P/B", val.get("pb")), ("P/S", val.get("ps")),
             ("EV/EBIT", val.get("ev_ebit"))]
    shown = ", ".join("%s %.2f" % (k, v) for k, v in parts if _num(v))
    if shown:
        out.append(_find("multiples", "multiples", None,
                         "%s against %s results." % (shown, val.get("asOfPeriod")), "info"))
    ey = val.get("earnings_yield")
    if _num(ey) and rf:
        low = ey < rf["yieldPct"]
        out.append(_find("earnings_yield", "earnings yield", ey,
                         "Earnings are %.2f%% of the market value, %s the %s yield of %.2f%%%s." % (
                             ey, "below" if low else "above", rf["instrument"], rf["yieldPct"],
                             ": the price assumes profits will grow" if low else ""),
                         "info" if low else "neutral", "%",
                         QUESTIONS["earnings_yield"] if low else None))
    pb = val.get("pb")
    if _num(pb) and pb < 1:
        out.append(_find("pb", "price to book", pb,
                         "The market values the company below its book equity: it doubts the "
                         "assets are worth their carrying value or can earn their cost of capital.",
                         "info", "x"))
    if val.get("peCrossCheck") and val["peCrossCheck"] != "agree":
        out.append(_find("pe_check", "P/E cross-check", None,
                         "The two P/E routes %s, so a share count or unit upstream is wrong and "
                         "the multiples are unreliable." % val["peCrossCheck"], "concern"))
    return out


# --------------------------------------------------------------------- read
def read(doc):
    a = S.analyse(doc)
    rows = a.get("metrics") or []
    entity = dict(a.get("entity") or {})
    sector, exchange = _listing(entity)
    kind, why = classify(entity, sector)
    rf = FI.risk_free(exchange) if exchange else None
    models = M.score_all(a)
    report = {"entity": entity, "sector": sector, "exchange": exchange, "kind": kind,
              "kindReason": why, "period": rows[0]["period"] if rows else None,
              "riskFree": rf, "sections": [], "notAssessed": []}
    if not rows:
        report["notAssessed"].append("no periods with figures")
        return report
    currency = entity.get("currency")
    sections = [
        ("integrity", "1. Can the numbers be trusted", _integrity(a, rows)),
        ("income", "2. Income statement", _income(a, rows, kind, currency)),
        ("balance", "3. Balance sheet", _balance(a, rows, kind, models)),
        ("cash", "4. Cash flow", _cash(a, rows, kind)),
        ("returns", "5. Returns", _returns(a, rows, kind, rf)),
        ("efficiency", "6. Efficiency", _efficiency(a, rows, kind)),
        ("quality", "7. Earnings quality", _quality(a, rows, models, kind)),
        ("distress", "8. Distress and strength", _distress(a, rows, models, kind)),
        ("valuation", "9. Valuation", _valuation(a, models, rf)),
    ]
    for sid, title, findings in sections:
        report["sections"].append({"id": sid, "title": title, "findings": findings})

    cur = rows[0]
    if not rf:
        report["notAssessed"].append("returns against the government yield: no yield on file "
                                     "for this market")
    for key, why_ in (("ocf", "cash conversion and free cash flow: no operating cash flow"),
                      ("current_ratio", "liquidity: no current assets and liabilities split"),
                      ("interest_cover", "interest cover: no finance cost or operating profit line"),
                      ("inventory_days", "working-capital days: no inventory, receivables or "
                                         "payables lines")):
        if cur.get(key) is None and not (key in ("current_ratio", "inventory_days", "interest_cover")
                                         and _is_fin(kind)):
            report["notAssessed"].append(why_)
    ben = models.get("beneish") or {}
    if not ben.get("available") and ben.get("missing"):
        report["notAssessed"].append("Beneish M-score: missing %s" % ", ".join(ben["missing"][:5]))
    if not (a.get("valuation") or {}).get("marketCap"):
        report["notAssessed"].append("valuation: no market capitalisation on file")

    allf = [f for s in report["sections"] for f in s["findings"]]
    report["strengths"] = [f for f in allf if f["verdict"] == "strength"]
    report["concerns"] = [f for f in allf if f["verdict"] == "concern"]
    seen, qs = set(), []
    for f in report["concerns"]:
        q = f.get("question")
        if q and q not in seen:
            seen.add(q)
            qs.append(q)
    report["questions"] = qs
    return report
