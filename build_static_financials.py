#!/usr/bin/env python3
"""build_static_financials.py - convert Yahoo financial statements into the
financials_api response schema and write per-security static JSON files so
the FINANCIALS panel works on GitHub Pages (no backend needed).

Output: static_data/financials/<TICKER>.json shaped exactly like
financials_api.get_financials() response:
  {ticker, name, statement, statementTitle, period, currency, ir_url,
   available: true, source: "YAHOO FINANCE", periods: [...],
   rows: [{label, values: [...]}], source_url}

Also writes static_data/financials_index.json: {TICKER: {name, exchange,
currency}} for lookup.
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
YF = os.path.join(BASE, "static_data", "yahoo_financials.json")
OUT_DIR = os.path.join(BASE, "static_data", "financials")
INDEX = os.path.join(BASE, "static_data", "financials_index.json")

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

# Yahoo row name -> our schema key
YF_MAP = {
    "income": {
        "Total Revenue": "revenue",
        "Cost Of Revenue": "costOfSales",
        "Gross Profit": "grossProfit",
        "Operating Expense": "operatingExpenses",
        "Operating Income": "operatingProfit",
        "Interest Expense": "netFinanceCosts",
        "Pretax Income": "profitBeforeTax",
        "Tax Provision": "taxExpense",
        "Net Income Common Stockholders": "netProfit",
        "Diluted EPS": "eps",
    },
    "balance": {
        "Total Non Current Assets": "nonCurrentAssets",
        "Total Current Assets": "currentAssets",
        "Cash Cash Equivalents And Short Term Investments": "cashAndEquivalents",
        "Total Assets": "totalAssets",
        "Total Non Current Liabilities Net Minority Interest": "nonCurrentLiabilities",
        "Total Current Liabilities": "currentLiabilities",
        "Total Liabilities Net Minority Interest": "totalLiabilities",
        "Total Equity Gross Minority Interest": "totalEquity",
    },
    "cashflow": {
        "Operating Cash Flow": "operatingCashFlow",
        "Capital Expenditure": "capex",
        "Free Cash Flow": "freeCashFlow",
        "Investing Cash Flow": "investingCashFlow",
        "Financing Cash Flow": "financingCashFlow",
        "Changes In Cash": "netChangeInCash",
    },
}

def yf_to_rows(statement, data):
    """data: {year: {yahoo_row: val}} -> {field: [values aligned to years]}"""
    years = sorted(data.keys(), reverse=True)
    fields = {}
    for field, label in STATEMENT_SCHEMA[statement]:
        vals = []
        for y in years:
            ydata = data[y]
            v = None
            for src, dst in YF_MAP[statement].items():
                if dst == field and src in ydata:
                    v = ydata[src]
                    break
            vals.append(v)
        if any(v is not None for v in vals):
            fields[field] = vals
    return years, fields

def build():
    if not os.path.exists(YF):
        print("yahoo_financials.json not found - run fetch_yahoo_financials.py first")
        return
    yf = json.load(open(YF, encoding="utf-8"))
    os.makedirs(OUT_DIR, exist_ok=True)
    index = {}
    n = 0
    for sym, rec in yf.items():
        if not rec.get("income") and not rec.get("balance") and not rec.get("cashflow"):
            continue
        base = {
            "ticker": sym, "name": rec.get("name"), "currency": rec.get("currency"),
            "source": "Yahoo Finance", "asOf": "2026",
            "marketCap": rec.get("marketCap"), "sharesOutstanding": rec.get("sharesOutstanding"),
        }
        for statement in ["income", "balance", "cashflow"]:
            data = rec.get(statement, {})
            if not data:
                continue
            years, fields = yf_to_rows(statement, data)
            if not fields:
                continue
            out = dict(base)
            out["statement"] = statement
            out["statementTitle"] = {"income": "Income Statement", "balance": "Balance Sheet",
                                     "cashflow": "Cash Flow"}[statement]
            out["period"] = "annual"
            out["available"] = True
            out["periods"] = ["FY" + y for y in years]
            # rows in schema order
            rows = []
            for field, label in STATEMENT_SCHEMA[statement]:
                if field in fields:
                    rows.append({"label": label, "values": fields[field]})
            out["rows"] = rows
            with open(os.path.join(OUT_DIR, sym.replace("/", "_") + "__" + statement + ".json"), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False)
        index[sym] = {"name": rec.get("name"), "currency": rec.get("currency"),
                      "marketCap": rec.get("marketCap")}
        n += 1
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    print(f"DONE: {n} securities -> static_data/financials/")

if __name__ == "__main__":
    build()
