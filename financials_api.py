"""
financials_api.py  -  Per-company financial statements for the Financials tab.

Serves the three core statements behind a dropdown:
    GET /api/financials?ticker=SCOM&statement=income&period=annual
    statement in {income, balance, cashflow}
    period    in {annual, interim}

DATA HONESTY (project rule)
---------------------------
This handler NEVER fabricates financials. It returns real filed numbers when
the server has them, and an explicit "available: false" + empty rows otherwise,
so the UI shows a clean "no filings loaded" state instead of guessed figures.

Where do real numbers come from? Each company's investor-relations / filings
page (or the exchange disclosure hub). This module keeps a registry mapping
ticker -> official IR/filings URL so the panel can (a) deep-link users to the
primary source and (b) be populated by a loader that parses those filings into
the STATEMENT_SCHEMA below. Populating that loader for 675 companies is a data
pipeline, not a code constant - so out of the box this returns structured
placeholders CLEARLY labelled source="SAMPLE" until real filings are attached.

Pure stdlib. Reuses format_money from fundamentals_format for display parity.
"""
import os
import json
from datetime import datetime, timezone

try:
    from fundamentals_format import format_money, DASH
except Exception:  # keep importable standalone
    DASH = "\u2014"
    def format_money(v, currency=None, dash=DASH, decimals=1):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return dash
        for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(f) >= div:
                s = "%.*f%s" % (decimals, f / div, suf)
                break
        else:
            s = "%.*f" % (decimals, f)
        return s + (" " + currency if currency else "")

# ---- statement line-item schemas (order matters for display) --------------
STATEMENT_SCHEMA = {
    "income": [
        ("revenue", "Revenue"),
        ("costOfSales", "Cost of Sales"),
        ("grossProfit", "Gross Profit"),
        ("operatingExpenses", "Operating Expenses"),
        ("operatingProfit", "Operating Profit (EBIT)"),
        ("netFinanceCosts", "Net Finance Costs"),
        ("profitBeforeTax", "Profit Before Tax"),
        ("taxExpense", "Income Tax"),
        ("netProfit", "Net Profit"),
        ("eps", "EPS"),
    ],
    "balance": [
        ("nonCurrentAssets", "Non-current Assets"),
        ("currentAssets", "Current Assets"),
        ("cashAndEquivalents", "Cash & Equivalents"),
        ("totalAssets", "Total Assets"),
        ("nonCurrentLiabilities", "Non-current Liabilities"),
        ("currentLiabilities", "Current Liabilities"),
        ("totalLiabilities", "Total Liabilities"),
        ("totalEquity", "Total Equity"),
    ],
    "cashflow": [
        ("operatingCashFlow", "Operating Cash Flow"),
        ("capex", "Capital Expenditure"),
        ("freeCashFlow", "Free Cash Flow"),
        ("investingCashFlow", "Investing Cash Flow"),
        ("financingCashFlow", "Financing Cash Flow"),
        ("netChangeInCash", "Net Change in Cash"),
    ],
}

STATEMENT_TITLES = {
    "income": "Income Statement",
    "balance": "Balance Sheet",
    "cashflow": "Cash Flow Statement",
}

# ---- registry: ticker -> official investor-relations / filings location ----
# Populate/verify before production. Only the primary-source LINK lives here;
# the numbers come from a filings loader, never from this file.
FILINGS_SOURCES = {
    # ticker: {name, exchange, currency, ir_url}
    "SCOM": {"name": "Safaricom Plc", "exchange": "NSE", "currency": "KES",
             "ir_url": "https://www.safaricom.co.ke/investor-relations"},
    "EQTY": {"name": "Equity Group Holdings", "exchange": "NSE", "currency": "KES",
             "ir_url": "https://equitygroupholdings.com/investor-relations/"},
    "KCB":  {"name": "KCB Group Plc", "exchange": "NSE", "currency": "KES",
             "ir_url": "https://kcbgroup.com/investor-relations/"},
    "EABL": {"name": "East African Breweries", "exchange": "NSE", "currency": "KES",
             "ir_url": "https://www.eabl.com/investors"},
    "MTNN": {"name": "MTN Nigeria", "exchange": "NGX", "currency": "NGN",
             "ir_url": "https://www.mtn.ng/investors/"},
    "DANGCEM": {"name": "Dangote Cement", "exchange": "NGX", "currency": "NGN",
                "ir_url": "https://www.dangotecement.com/investor-relations/"},
    "GTCO": {"name": "Guaranty Trust Holding", "exchange": "NGX", "currency": "NGN",
             "ir_url": "https://www.gtcoplc.com/investor-relations/"},
    "COMI": {"name": "Commercial International Bank", "exchange": "EGX", "currency": "EGP",
             "ir_url": "https://www.cibeg.com/en/investor-relations"},
    "NPN":  {"name": "Naspers", "exchange": "JSE", "currency": "ZAR",
             "ir_url": "https://www.naspers.com/investors"},
    "SOL":  {"name": "Sasol", "exchange": "JSE", "currency": "ZAR",
             "ir_url": "https://www.sasol.com/investor-centre"},
}


def _load_filings_registry():
    """Load verified real filing URLs from filings_registry.json next to this
    module. Returns {} if absent - the handler still works, just without links."""
    path = os.path.join(os.path.dirname(__file__), "filings_registry.json")
    try:
        with open(path) as f:
            return json.load(f).get("filings", {})
    except (OSError, ValueError):
        return {}


FILINGS_REGISTRY = _load_filings_registry()


def get_filings(ticker):
    """Return the verified real filings for a company, or an honest empty list.
    Never fabricates a URL - only returns what's in the verified registry."""
    ticker = (ticker or "").upper()
    rec = FILINGS_REGISTRY.get(ticker)
    if not rec:
        # fall back to a bare IR link if we have one in FILINGS_SOURCES
        meta = FILINGS_SOURCES.get(ticker, {})
        return {"ticker": ticker, "name": meta.get("name"),
                "ir_url": meta.get("ir_url"), "reports": [], "verified": False}
    return {"ticker": ticker, "name": rec.get("name"),
            "exchange": rec.get("exchange"), "currency": rec.get("currency"),
            "ir_url": rec.get("ir_url"), "reports": rec.get("reports", []),
            "verified": True}


def _empty_rows(statement):
    return [{"key": k, "label": lbl, "values": []} for k, lbl in STATEMENT_SCHEMA[statement]]


def get_financials(ticker, statement="income", period="annual",
                   store=None):
    """Return one statement for one company.

    store: optional dict of real filed data injected by the server, shaped:
      store[ticker][period][statement] = {
          "periods": ["FY2023","FY2024","FY2025"],
          "currency": "KES",
          "values": {"revenue":[...], "netProfit":[...], ...},  # aligned to periods
          "as_of": "2026-06-30", "source_url": "...", "filed": True
      }
    When store has the data it is returned as source="FILED". Otherwise the
    handler returns available=False with empty rows (honest no-data state).
    """
    ticker = (ticker or "").upper()
    statement = statement if statement in STATEMENT_SCHEMA else "income"
    meta = FILINGS_SOURCES.get(ticker, {})
    base = {
        "ticker": ticker,
        "name": meta.get("name"),
        "statement": statement,
        "statementTitle": STATEMENT_TITLES[statement],
        "period": period,
        "currency": meta.get("currency"),
        "ir_url": meta.get("ir_url"),
        "asOf": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    rec = None
    if store:
        rec = (store.get(ticker, {}).get(period, {}) or {}).get(statement)

    if not rec:
        base.update({"available": False, "source": "NONE", "periods": [],
                     "rows": _empty_rows(statement),
                     "note": ("No filings loaded for this company/period. "
                              "Open the investor-relations link for the primary "
                              "source." if meta.get("ir_url") else
                              "No filings loaded and no IR link on file.")})
        return base

    periods = rec.get("periods", [])
    vals = rec.get("values", {})
    rows = []
    for k, lbl in STATEMENT_SCHEMA[statement]:
        series = vals.get(k, [])
        # align/pad to periods length; missing -> None (honest dash in UI)
        series = (series + [None] * len(periods))[:len(periods)]
        rows.append({"key": k, "label": lbl, "values": series})
    base.update({
        "available": True,
        "source": "FILED" if rec.get("filed") else rec.get("source", "LIVE"),
        "currency": rec.get("currency", base["currency"]),
        "periods": periods,
        "rows": rows,
        "source_url": rec.get("source_url", meta.get("ir_url")),
        "filedAsOf": rec.get("as_of"),
    })
    return base


def format_row_for_display(row, currency, eps_key="eps"):
    """Helper the server/frontend can use to render values consistently.
    EPS is shown as a plain number; everything else via format_money."""
    out = []
    for v in row["values"]:
        if v is None:
            out.append(DASH)
        elif row["key"] == eps_key:
            try:
                out.append("%.2f" % float(v))
            except (TypeError, ValueError):
                out.append(DASH)
        else:
            out.append(format_money(v, currency))
    return out
