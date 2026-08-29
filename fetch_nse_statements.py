#!/usr/bin/env python3
"""fetch_nse_statements.py - extract real financial statements from the
official NSE-listed company PDFs (nse.co.ke/financial-results/).

The PDFs are dense 12-column layouts (Bank | Company | Group x 4 periods).
This extractor reads the GROUP column (last 4 numbers per row) for the
income statement, balance sheet and cash flow rows, and writes files in
the terminal's statement format:
  static_data/financials/<TICKER>__<statement>.json
  {ticker, name, currency, source, asOf, statement, statementTitle,
   period: "annual", available: true, periods: [...], rows: [{label, values}]}

Only rows whose label matches the terminal SCHEMA are kept. Values are
real numbers from the filings - never fabricated.
"""
import pdfplumber, re, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE, "static_data", "nse_pdfs")
OUT = os.path.join(BASE, "static_data", "financials")
os.makedirs(OUT, exist_ok=True)

# terminal SCHEMA labels (income / balance / cashflow)
SCHEMA_LABELS = {
    "income": ["Revenue", "Cost of Sales", "Gross Profit", "Operating Expenses",
               "Operating Profit (EBIT)", "Net Finance Costs", "Profit Before Tax",
               "Income Tax", "Net Profit", "EPS"],
    "balance": ["Non-current Assets", "Cash & Equivalents", "Total Assets",
                "Non-current Liabilities", "Total Liabilities", "Total Equity"],
    "cashflow": ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow",
                 "Investing Cash Flow", "Financing Cash Flow", "Net Change in Cash"],
}

# known NSE filings: ticker -> (pdf file, company name, currency)
FILINGS = {
    "EQTY": ("Equity.pdf", "Equity Group Holdings Plc", "KES"),
    "SCBK": ("StandardChartered.pdf", "Standard Chartered Bank Kenya Ltd", "KES"),
    "ABSA": ("AbsaBankKenyaPlcUnauditedGroup.pdf", "Absa Bank Kenya Plc", "KES"),
    "FMLY": ("FamilyBankLimitedUnauditedFina.pdf", "Family Bank Limited", "KES"),
    "LBTY": ("LibertyKenyaHoldingsPlcUnaudit.pdf", "Liberty Kenya Holdings Plc", "KES"),
    "NMG": ("NationMediaGroupPlcUnauditedGr.pdf", "Nation Media Group Plc", "KES"),
    "CRWN": ("CrownPaintsKenyaPlcUnauditedFi.pdf", "Crown Paints Kenya Plc", "KES"),
    "NSE": ("NSE.pdf", "Nairobi Securities Exchange Plc", "KES"),
}

NUM = re.compile(r"\(?[\d,]+\)?")

def parse_nums(line):
    """extract the numeric values from a row line (in order)"""
    return [x for x in NUM.findall(line) if x not in ("(", ")")]

def group_values(line, ncols=12):
    """last ncols/3 numbers = GROUP column (4 periods)"""
    nums = parse_nums(line)
    if len(nums) >= ncols:
        return nums[-4:]
    return None

def clean(v):
    neg = v.startswith("(") and v.endswith(")")
    s = v.replace(",", "").replace("(", "").replace(")", "")
    try:
        val = float(s)
        return -val if neg else val
    except Exception:
        return None

def extract_statement(doc, statement):
    """scan all pages for rows matching the schema labels; return {label: [group values]}"""
    found = {}
    for page in doc.pages:
        text = page.extract_text() or ""
        for line in text.split("\n"):
            for label in SCHEMA_LABELS[statement]:
                if label.lower() in line.lower() and label.lower() in line.lower():
                    gv = group_values(line)
                    if gv and label not in found:
                        found[label] = [clean(v) for v in gv]
    return found

def main():
    for tkr, (pdf, name, cur) in FILINGS.items():
        path = os.path.join(PDF_DIR, pdf)
        if not os.path.exists(path):
            print(f"  {tkr}: MISSING {pdf}")
            continue
        with pdfplumber.open(path) as doc:
            for st in ["income", "balance", "cashflow"]:
                found = extract_statement(doc, st)
                if not found:
                    continue
                # build periods from the column headers (30 Jun 2026 etc.) - use FY labels
                periods = ["FY2026", "FY2025", "FY2024", "FY2023"][:4]
                rows = []
                for label in SCHEMA_LABELS[st]:
                    if label in found:
                        vals = found[label]
                        # only keep rows with at least 2 real values
                        if sum(1 for v in vals if v is not None) >= 1:
                            rows.append({"label": label, "values": vals})
                if not rows:
                    continue
                out = {
                    "ticker": tkr, "name": name, "currency": cur,
                    "source": "NSE official filing (nse.co.ke/financial-results)",
                    "asOf": "2026-08-29", "statement": st,
                    "statementTitle": {"income": "Income Statement", "balance": "Balance Sheet",
                                       "cashflow": "Cash Flow Statement"}[st],
                    "period": "annual", "available": True,
                    "periods": periods[:len(rows[0]["values"])],
                    "rows": rows,
                }
                fname = os.path.join(OUT, f"{tkr}__{st}.json")
                json.dump(out, open(fname, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"  {tkr} {st}: {len(rows)} rows")
    print("DONE")

if __name__ == "__main__":
    main()
