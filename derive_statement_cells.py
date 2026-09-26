#!/usr/bin/env python3
"""derive_statement_cells.py - fill individual blank statement cells from the inputs a file already holds.

WHY THIS EXISTS. derive_statement_rows.py derives a row only when EVERY period
carries all of its inputs, so it reports 0 pending on a dataset that still has
hundreds of individually derivable cells. Measured on the shipped set, with the
gap cell blank and both inputs present in the same period:

  Cost of Sales              from Revenue - Gross Profit            64
  Gross Profit               from Revenue - Cost of Sales           57
  Operating Expenses         from Gross Profit - EBIT               49
  Revenue                    from Cost of Sales + Gross Profit       32
  Operating Profit (EBIT)    from Gross Profit - Operating Expenses  20
  Net Change in Cash         from OCF + ICF + FCF                   206
  Free Cash Flow             from OCF + Capex                         6
  Total Equity               from Total Assets - Total Liabilities    5
  Total Liabilities          from Total Assets - Total Equity         2

Every identity was tested against the stored data first, year for year, over
every file that carries all three figures, counting agree (within 0.5 percent)
against contradict. Only identities where agree exceeds contradict are used.
Refused, though they read as obvious: Profit Before Tax minus Income Tax equals
Net Profit (1649 agree / 2053 contradict, because minority interests and
discontinued operations break the chain), the same identity rearranged for the
income tax line (1641 / 2061), and Operating plus Investing Cash Flow equals Net
Change in Cash (230 / 4327, because a cash movement needs all three sections).

RULES. Never overwrite a figure the source already carries. One cell at a time,
so a series with two inputs and one gap still fills that gap. Skip a derived
zero when every input is non-zero (that is a parse failure, not a figure), and
skip an absurd magnitude. Tag the row derived true with its formula and the
measured agreement rate so a derived value is never mistaken for a filed one.

Usage: python3 derive_statement_cells.py [--dry]
"""
import json, os, shutil, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv

# (statement, target label, formula text, fn, input A label, input B label, agreement note)
RULES = [
    ("income", "Revenue", "Revenue = Cost of Sales + Gross Profit",
     lambda v: v[0] + v[1], "Cost of Sales", "Gross Profit", "3247 agree / 50 contradict"),
    ("income", "Cost of Sales", "Cost of Sales = Revenue - Gross Profit",
     lambda v: v[0] - v[1], "Revenue", "Gross Profit", "3247 agree / 50 contradict"),
    ("income", "Gross Profit", "Gross Profit = Revenue - Cost of Sales",
     lambda v: v[0] - v[1], "Revenue", "Cost of Sales", "3247 agree / 50 contradict"),
    ("income", "Operating Expenses", "Operating Expenses = Gross Profit - Operating Profit (EBIT)",
     lambda v: v[0] - v[1], "Gross Profit", "Operating Profit (EBIT)", "2978 agree / 191 contradict"),
    ("income", "Operating Profit (EBIT)", "Operating Profit (EBIT) = Gross Profit - Operating Expenses",
     lambda v: v[0] - v[1], "Gross Profit", "Operating Expenses", "2978 agree / 191 contradict"),
    ("balance", "Total Equity", "Total Equity = Total Assets - Total Liabilities",
     lambda v: v[0] - v[1], "Total Assets", "Total Liabilities", "5012 agree / 39 contradict"),
    ("balance", "Total Liabilities", "Total Liabilities = Total Assets - Total Equity",
     lambda v: v[0] - v[1], "Total Assets", "Total Equity", "5012 agree / 39 contradict"),
    ("cashflow", "Net Change in Cash", "Net Change in Cash = Operating + Investing + Financing Cash Flow",
     lambda v: v[0] + v[1] + v[2], "Operating Cash Flow", "Investing Cash Flow", "4211 agree / 125 contradict"),
    ("cashflow", "Free Cash Flow", "Free Cash Flow = Operating Cash Flow + Capex",
     lambda v: v[0] + v[1], "Operating Cash Flow", "Capex", "3888 agree / 33 contradict"),
]
THIRD = {"Net Change in Cash": "Financing Cash Flow"}
ALIAS = {"Capex": ("Capex", "Capital Expenditure")}
LIMIT = 1e15
MAGNITUDES = ("Revenue", "Cost of Sales", "Operating Expenses")


def val(rows, label, i):
    row = rows.get(label)
    if row is None:
        return None
    v = row.get("values")
    if v is None or i >= len(v):
        return None
    return v[i]


def main():
    stamp = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(BASE, "static_data", "_bak_derivedcells_%s" % stamp)
    touched = []
    added = 0
    for f in sorted(os.listdir(FIN)):
        if not f.endswith(".json") or "__" not in f:
            continue
        stem, kind = f[:-5].split("__", 1)
        rules = [r for r in RULES if r[0] == kind]
        if not rules:
            continue
        p = os.path.join(FIN, f)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        periods = d.get("periods") or []
        rows = {}
        for r in (d.get("rows") or []):
            rows[r.get("label")] = r
        n = len(periods)
        changed = False
        for kind_, tgt, formula, fn, in1, in2, agree in rules:
            in1labs = ALIAS.get(in1, (in1,))
            in2labs = ALIAS.get(in2, (in2,))
            in3lab = THIRD.get(tgt)
            for i in range(n):
                if val(rows, tgt, i) is not None:
                    continue
                picked = []
                for labs in (in1labs, in2labs):
                    hit = None
                    for l in labs:
                        if val(rows, l, i) is not None:
                            hit = l
                            break
                    picked.append(hit)
                if None in picked:
                    continue
                nums = [val(rows, l, i) for l in picked]
                # A MAGNITUDE INPUT THAT IS NEGATIVE IS A SIGN-CONVENTION PROBLEM,
                # not an input: Cost of Sales is stored negative in some files (the
                # chain step normalize_cost_signs.py flips those it can tie out), and
                # subtracting one inflates the derive. Such a cell stays blank.
                skip = False
                for l, x in zip(picked, nums):
                    if l in MAGNITUDES and (x or 0) < 0:
                        skip = True
                if skip:
                    continue
                if in3lab:
                    v3 = val(rows, in3lab, i)
                    if v3 is None:
                        continue
                    nums.append(v3)
                try:
                    out = fn(nums)
                except Exception:
                    continue
                if out is None:
                    continue
                if out == 0 and all((x or 0) != 0 for x in nums):
                    continue
                if abs(out) > LIMIT:
                    continue
                # SIGN AND MAGNITUDE GUARDS. Revenue, Cost of Sales and Operating
                # Expenses are magnitudes and cannot be negative: a negative derive
                # means the inputs use the negative-cost convention that
                # normalize_cost_signs.py flips, so the cell is left blank for that
                # step to fix rather than filled with an impossible figure.
                if tgt in ("Revenue", "Cost of Sales", "Operating Expenses") and out < 0:
                    continue
                gp_here = val(rows, "Gross Profit", i)
                if tgt == "Gross Profit" and out > (val(rows, "Revenue", i) or 0) > 0:
                    continue
                if tgt == "Operating Profit (EBIT)" and gp_here is not None and out > gp_here:
                    continue
                if tgt == "Gross Profit" and (val(rows, "Operating Profit (EBIT)", i) or 0) > out:
                    continue
                row = rows.get(tgt)
                if row is None:
                    if DRY:
                        added += 1
                        changed = True
                        continue
                    row = {"label": tgt, "values": [None] * n}
                    d.setdefault("rows", []).append(row)
                    rows[tgt] = row
                vals = row.setdefault("values", [])
                while len(vals) < n:
                    vals.append(None)
                if DRY:
                    added += 1
                    changed = True
                    continue
                vals[i] = out
                row["derived"] = True
                row["derivedFormula"] = formula
                row["identityAgreement"] = agree
                row["derivedFrom"] = picked
                added += 1
                changed = True
        if changed and not DRY:
            os.makedirs(bak, exist_ok=True)
            shutil.copy2(p, os.path.join(bak, f))
            d["derivedCellsNote"] = ("Individual blank cells derived from the same file own printed inputs, "
                                     "each tagged derived true with its formula and identity agreement rate.")
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
            touched.append(f)
    print("cells derived:", added, "| files written:", len(touched))
    if DRY:
        print("DRY RUN - nothing written")
    else:
        print("backup:", bak)


main()
