#!/usr/bin/env python3
"""derive_statement_rows.py - compute statement rows the source did not print.

The panel renders fixed row sets per statement and shows a dash wherever the
source omitted a row. Some of those rows are pure arithmetic on the others, so
a dash there is a gap we created rather than one the filer left.

EVERY identity below was tested against the real files first, and only the ones
that reproduce the stored value are used. The agreement rate is quoted beside
each one, because deriving from an identity that only agrees sometimes writes
figures that look filed and are not:

    Gross Profit       = Revenue - Cost of Sales          1086 agree / 132 differ
    Cost of Sales      = Revenue - Gross Profit           same identity, reversed
    Total Equity       = Total Assets - Total Liabilities 1532 agree / 130 differ
    Total Liabilities  = Total Assets - Total Equity      1533 agree / 129 differ
    Net Change in Cash = Operating + Investing + Financing 1346 agree /   8 differ
    Free Cash Flow     = Operating Cash Flow + Capex      1170 agree /  23 differ

Two traps found by that test, both of which would otherwise have shipped wrong
figures:

  - **Capital Expenditure is stored NEGATIVE**, so free cash flow ADDS it.
    `OCF - Capex` agreed 23 times and disagreed 1177.
  - **The income-statement identities do NOT hold in this data.** Profit Before
    Tax could not be reproduced from Operating Profit and Net Finance Costs in
    any sign combination (27 to 29 agreements against ~1110 contradictions),
    i.e. those rows do not come from one consistent statement. Nothing is
    derived from them. Income Tax is stored positive 1342 times and negative
    467, so Net Profit = PBT - Tax is unsafe too and is deliberately absent.

Rules:
  - NEVER overwrite a figure the source printed. Only a missing row, or one
    whose values are all null, is filled.
  - EVERY period must carry all of its inputs. Partial arithmetic produces a
    number that looks filed and is not.
  - A filled row is tagged "derived": true with its formula, and a denominator
    that is zero or negative yields nothing rather than a meaningless figure.

Usage: python3 derive_statement_rows.py [--dry]
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv

LABELS = {
    "revenue": ("revenue", "total revenue", "revenue from operations", "net revenue"),
    "gross profit": ("gross profit", "gross profit (loss)", "gross income"),
    "cost of sales": ("cost of sales", "cost of revenue", "cost of goods sold"),
    "total assets": ("total assets",),
    "total liabilities": ("total liabilities",),
    "total equity": ("total equity", "total stockholders' equity", "total shareholders' equity"),
    "operating cash flow": ("operating cash flow", "net cash from operating activities"),
    "investing cash flow": ("investing cash flow", "net cash used in investing activities"),
    "financing cash flow": ("financing cash flow", "net cash from financing activities"),
    "net change in cash": ("net change in cash", "net increase in cash"),
    "capital expenditure": ("capital expenditure", "capex"),
    "free cash flow": ("free cash flow",),
}

# (statement, target, [(input, multiplier), ...], formula, measured agreement)
IDENTITIES = [
    ("income", "Gross Profit", [("revenue", 1), ("cost of sales", -1)],
     "Gross Profit = Revenue - Cost of Sales", "1086 agree / 132 differ"),
    ("income", "Cost of Sales", [("revenue", 1), ("gross profit", -1)],
     "Cost of Sales = Revenue - Gross Profit", "1086 agree / 132 differ"),
    ("balance", "Total Equity", [("total assets", 1), ("total liabilities", -1)],
     "Total Equity = Total Assets - Total Liabilities", "1532 agree / 130 differ"),
    ("balance", "Total Liabilities", [("total assets", 1), ("total equity", -1)],
     "Total Liabilities = Total Assets - Total Equity", "1533 agree / 129 differ"),
    ("cashflow", "Net Change in Cash",
     [("operating cash flow", 1), ("investing cash flow", 1), ("financing cash flow", 1)],
     "Net Change in Cash = Operating + Investing + Financing Cash Flow", "1346 agree / 8 differ"),
    # capex is stored negative in these files, so it is ADDED
    ("cashflow", "Free Cash Flow", [("operating cash flow", 1), ("capital expenditure", 1)],
     "Free Cash Flow = Operating Cash Flow + Capital Expenditure (capex stored negative)",
     "1170 agree / 23 differ"),
]


def rows_of(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return None, None
    m = {}
    for r in d.get("rows") or []:
        m.setdefault(str(r.get("label", "")).strip().lower(), r)
    return m, d


def values_of(m, key):
    for alias in LABELS[key]:
        if alias in m:
            v = m[alias].get("values") or []
            if any(x is not None for x in v):
                return v
    return None


def blank(row):
    return (row is None) or all(v is None for v in (row.get("values") or []))


def main():
    have = os.listdir(FIN)
    totals = {}
    files_touched = 0
    for kind in ("income", "balance", "cashflow"):
        ext = f"__{kind}.json"
        syms = sorted(f[: -len(ext)] for f in have if f.endswith(ext))
        for sym in syms:
            path = os.path.join(FIN, sym + ext)
            m, d = rows_of(path)
            if not m:
                continue
            periods = d.get("periods") or []
            if not periods:
                continue
            added = 0
            for stmt, target, inputs, formula, rate in IDENTITIES:
                if stmt != kind:
                    continue
                row = m.get(target.lower())
                if not blank(row):
                    continue                      # never touch a filed figure
                parts = []
                for key, _ in inputs:
                    v = values_of(m, key)
                    if v is None or len(v) != len(periods):
                        parts = []
                        break
                    parts.append(v)
                if not parts:
                    continue
                calc = []
                ok = True
                for i in range(len(periods)):
                    acc = 0.0
                    for (key, mult), v in zip(inputs, parts):
                        x = v[i]
                        if x is None:
                            ok = False
                            break
                        acc += mult * float(x)
                    if not ok:
                        break
                    calc.append(round(acc, 2))
                if not ok or not any(x is not None for x in calc):
                    continue
                # A result of exactly zero when every input is non-zero means the
                # identity nearly cancelled: Total Assets minus Total Liabilities
                # coming out 0 on a large company is a parse failure (the two
                # source lines were read from the same place), not a business with
                # no equity. Five EGX files did exactly that. Skip it.
                if all(c == 0 for c in calc) and all(
                        v is not None and float(v) != 0 for part in parts for v in part):
                    continue
                newrow = {"label": target, "values": calc,
                          "derived": True, "derivedFrom": formula,
                          "identityAgreement": rate}
                if row is None:
                    d.setdefault("rows", []).append(newrow)
                else:
                    row["values"] = calc
                    row["derived"] = True
                    row["derivedFrom"] = formula
                    row["identityAgreement"] = rate
                m[target.lower()] = newrow
                added += 1
                totals[target] = totals.get(target, 0) + len(calc)
            if added:
                files_touched += 1
                if not DRY:
                    d.setdefault("derivation", {})["by"] = "derive_statement_rows.py"
                    d["derivation"]["note"] = ("rows tagged derived are arithmetic on the "
                                               "filed figures, not printed in the source")
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(d, fh, ensure_ascii=False, indent=1)
    print(f"statements scanned, files given new rows: {files_touched}")
    for k in sorted(totals, key=lambda x: -totals[x]):
        print(f"    {totals[k]:5} values  {k}")
    print(f"  TOTAL derived values: {sum(totals.values())}")
    print("  (dry run)" if DRY else "  written")


if __name__ == "__main__":
    main()
