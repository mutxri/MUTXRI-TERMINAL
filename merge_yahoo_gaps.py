#!/usr/bin/env python3
"""merge_yahoo_gaps.py - fill blank CELLS in the shipped statements from Yahoo.

merge_yahoo_balance.py fills a balance ROW only when the whole row is absent or
every value null. The dominant remaining gap is different: a row that carries
figures for the recent years and a blank for an older period (the 5th period in
most JSE files), which that script cannot touch.

This fills individual null cells, and only null cells:

  - a figure already present is NEVER overwritten, so a value read from an
    exchange filing keeps its provenance;
  - every filled cell is listed in the row's "filled" map with the source and
    the periods it was applied to;
  - the two printed identities are checked before anything is written,
    Revenue - Cost of Sales = Gross Profit and Profit Before Tax - Income Tax =
    Net Profit (0.5% tolerance). A period whose identity does not tie after the
    fill has all of its candidate cells dropped rather than written.

Usage: python3 merge_yahoo_gaps.py [--dry]
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "static_data", "yahoo_financials.json")
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv

MAP = {
    "income": [
        ("Revenue",               ["Total Revenue", "Operating Revenue"]),
        ("Cost of Sales",         ["Cost Of Revenue", "Reconciled Cost Of Revenue"]),
        ("Gross Profit",          ["Gross Profit"]),
        ("Operating Expenses",    ["Operating Expense"]),
        ("Operating Profit (EBIT)", ["Operating Income", "EBIT"]),
        ("Net Finance Costs",     ["Interest Expense"]),
        ("Profit Before Tax",     ["Pretax Income"]),
        ("Income Tax",            ["Tax Provision"]),
        ("Net Profit",            ["Net Income Common Stockholders", "Net Income"]),
        ("EPS",                   ["Diluted EPS"]),
    ],
    "balance": [
        ("Non-current Assets",      ["Total Non Current Assets"]),
        ("Current Assets",          ["Current Assets"]),
        ("Cash & Equivalents",      ["Cash And Cash Equivalents",
                                     "Cash Cash Equivalents And Short Term Investments"]),
        ("Total Assets",            ["Total Assets"]),
        ("Non-current Liabilities", ["Total Non Current Liabilities Net Minority Interest"]),
        ("Current Liabilities",     ["Current Liabilities"]),
        ("Total Liabilities",       ["Total Liabilities Net Minority Interest"]),
        ("Total Equity",            ["Total Equity Gross Minority Interest", "Stockholders Equity"]),
    ],
    "cashflow": [
        ("Operating Cash Flow", ["Operating Cash Flow"]),
        ("Capital Expenditure", ["Capital Expenditure"]),
        ("Free Cash Flow",      ["Free Cash Flow"]),
        ("Investing Cash Flow", ["Investing Cash Flow"]),
        ("Financing Cash Flow", ["Financing Cash Flow"]),
        ("Net Change in Cash",  ["Changes In Cash"]),
    ],
}


def year_of(p):
    m = re.search(r"(19|20)\d{2}", str(p))
    return m.group(0) if m else None


def ties(vals, periods, a, b, c):
    """True when a - b = c within 0.5% at every period where all three exist."""
    for p in periods:
        x, y, z = vals.get((a, p)), vals.get((b, p)), vals.get((c, p))
        if x is None or y is None or z is None:
            continue
        if abs(x - y - z) > 0.005 * max(abs(x), abs(z), 1.0):
            return False
    return True


def main():
    with open(SRC, encoding="utf-8") as fh:
        src = json.load(fh)
    files = sorted(f for f in os.listdir(FIN) if f.endswith(("__income.json", "__balance.json", "__cashflow.json")))
    per_label = {}
    files_touched = 0
    no_source = 0
    for f in files:
        st = f[:-5].rsplit("__", 1)[1]
        sym = f[: -(len(st) + 7)]
        rec = src.get(sym)
        if not rec or not rec.get(st):
            no_source += 1
            continue
        path = os.path.join(FIN, f)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        periods = doc.get("periods") or []
        if not periods:
            continue
        yd = rec[st]
        rows = doc.setdefault("rows", [])
        by_label = {}
        for r in rows:
            by_label.setdefault(str(r.get("label", "")).strip().lower(), r)
        cand = {}
        for label, alts in MAP[st]:
            row = by_label.get(label.lower())
            if row is None:
                continue
            vals = list(row.get("values") or [])
            vals += [None] * max(0, len(periods) - len(vals))
            for i, p in enumerate(periods):
                if i < len(vals) and vals[i] is not None:
                    continue
                yr = year_of(p)
                fields = yd.get(yr) or {}
                for k in alts:
                    v = fields.get(k)
                    if v is not None:
                        cand[(label, p)] = v
                        break
        if not cand:
            continue
        # identity guards
        def ok(label, p, v):
            return v
        for (a, b, c, st_check) in (("Revenue", "Cost of Sales", "Gross Profit", st),
                                    ("Profit Before Tax", "Income Tax", "Net Profit", st)):
            if st != "income":
                continue
            for p in periods:
                triple = {}
                for lab in (a, b, c):
                    row = by_label.get(lab.lower())
                    if row is None:
                        triple[lab] = None
                        continue
                    vals = list(row.get("values") or [])
                    vals += [None] * max(0, len(periods) - len(vals))
                    idx = periods.index(p)
                    triple[lab] = cand.get((lab, p), vals[idx] if idx < len(vals) else None)
                if all(v is not None for v in triple.values()):
                    x, y, z = triple[a], triple[b], triple[c]
                    if abs(x - y - z) > 0.005 * max(abs(x), abs(z), 1.0):
                        for lab in (a, b, c):
                            cand.pop((lab, p), None)
        if not cand:
            continue
        applied = {}
        for (label, p), v in cand.items():
            row = by_label.get(label.lower())
            vals = list(row.get("values") or [])
            vals += [None] * max(0, len(periods) - len(vals))
            idx = periods.index(p)
            if vals[idx] is None:
                vals[idx] = v
                row["values"] = vals[: len(periods)]
                applied.setdefault(label, []).append(p)
                per_label[label] = per_label.get(label, 0) + 1
        if not applied:
            continue
        files_touched += 1
        if not DRY:
            row_src = json.loads(json.dumps(doc))
            row_src.setdefault("filled", {})
            for label, pl in applied.items():
                row_src["filled"][label] = {"source": "Yahoo Finance", "periods": pl}
            doc["filled"] = row_src["filled"]
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"statement files: {len(files)} | no Yahoo record: {no_source}")
    print(f"files gained cells: {files_touched}")
    for k in sorted(per_label, key=lambda x: -per_label[x]):
        print(f"   {per_label[k]:6} cells  {k}")
    print(f"  TOTAL cells filled: {sum(per_label.values())}")
    print("  (dry run)" if DRY else "  written")


if __name__ == "__main__":
    main()
