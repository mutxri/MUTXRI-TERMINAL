#!/usr/bin/env python3
"""
derive_opex_ebit.py - fill the panel's Operating Expenses and Operating Profit (EBIT)
rows from the other one plus Gross Profit, but ONLY where the identity is proven
inside the SAME file.

Measured across every income file before this was written:
  Operating Expenses      = Gross Profit - EBIT      2826 agree / 234 contradict
  Operating Profit (EBIT) = Gross Profit - OpEx      2821 agree / 239 contradict
  Net Finance Costs       = EBIT - Profit Before Tax   59 agree / 2656 contradict  REJECTED
  Profit Before Tax       = EBIT - Net Finance Costs   99 agree / 2616 contradict  REJECTED
  Net Profit              = Profit Before Tax - Tax   1439 agree / 2219 contradict  REJECTED
  Income Tax              = Profit Before Tax - NP    1226 agree / 2432 contradict  REJECTED
An identity where the contradictions outnumber the agreements is false and is never used,
however obvious it reads, so only the first two are applied.

A cell is written only when all three of Gross Profit, the target and the other input exist
for that period, and at least two OTHER periods of the same file reproduce the identity
exactly with zero contradictions. A negative Operating Expenses is refused as impossible.

Every fill is computed from the file's ORIGINAL values, never from a value this run has
just written, so a derived row can never feed another derivation in the same pass.

Usage: python3 derive_opex_ebit.py [--dry]
"""
import json, os, sys, glob

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv
TOL = 0.005

FORMULAS = ("Operating Expenses = Gross Profit - Operating Profit (EBIT)",
            "Operating Profit (EBIT) = Gross Profit - Operating Expenses")

ROWS = [
    ("Operating Expenses", "operating expenses", [("gross profit", 1), ("operating profit (ebit)", -1)],
     "Operating Expenses = Gross Profit - Operating Profit (EBIT)"),
    ("Operating Profit (EBIT)", "operating profit (ebit)", [("gross profit", 1), ("operating expenses", -1)],
     "Operating Profit (EBIT) = Gross Profit - Operating Expenses"),
]

total = 0
files = 0
refused_total = 0
report = []
for p in sorted(glob.glob(os.path.join(FIN, "*__income.json"))):
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        continue
    periods = d.get("periods") or []
    if not periods:
        continue
    n = len(periods)
    by = {}
    for r in d.get("rows") or []:
        by.setdefault(str(r.get("label", "")).strip().lower(), r)

    # a previous run of an older version of this script stamped derived=true without
    # writing anything. Clear only OUR OWN stamp so the run stays idempotent.
    for r in d.get("rows") or []:
        if r.get("derivedFrom") in FORMULAS:
            r.pop("derived", None)
            r.pop("derivedFrom", None)
            r.pop("derivedBasis", None)

    # ORIGINAL values, padded; reads never see this run's writes
    orig = {}
    for lab in ("gross profit", "operating expenses", "operating profit (ebit)"):
        r = by.get(lab)
        v = list(r.get("values") or []) if r is not None else None
        if v is not None:
            v += [None] * max(0, n - len(v))
            v = v[:n]
        orig[lab] = v

    def live(lab, create_label=None):
        """The row's OWN list, so a write persists."""
        r = by.get(lab)
        if r is None:
            if create_label is None:
                return None
            r = {"label": create_label, "values": [None] * n}
            d.setdefault("rows", []).append(r)
            by[lab] = r
        v = r.get("values")
        if not isinstance(v, list):
            v = []
            r["values"] = v
        while len(v) < n:
            v.append(None)
        return v

    touched = []
    refused = 0
    for target, tlab, ins, formula in ROWS:
        vt = orig.get(tlab)
        vs = [(orig.get(k), s) for k, s in ins]
        if vt is None or any(v is None for v, _ in vs):
            continue
        agree = contra = 0
        for i in range(n):
            if vt[i] in (None, ""):
                continue
            if not all(v[i] not in (None, "") for v, _ in vs):
                continue
            pred = sum(v[i] * s for v, s in vs)
            if abs(vt[i] - pred) <= max(abs(vt[i]) * TOL, 1):
                agree += 1
            else:
                contra += 1
        if agree < 2 or contra > 0:
            continue
        for i in range(n):
            if vt[i] not in (None, ""):
                continue
            if not all(v[i] not in (None, "") for v, _ in vs):
                continue
            new = sum(v[i] * s for v, s in vs)
            if new == 0:
                continue
            if target == "Operating Expenses" and new < 0:
                refused += 1
                continue
            row = by.get(tlab)
            if row is None:
                row = {"label": target, "values": [None] * n}
                d.setdefault("rows", []).append(row)
                by[tlab] = row
            lv = live(tlab, target)
            lv[i] = new
            row["derived"] = True
            row["derivedFrom"] = formula
            row["derivedBasis"] = "identity holds in every other period of this same file"
            touched.append({"label": target, "period": periods[i], "value": new,
                            "formula": formula, "provenPeriods": agree})
            total += 1
    refused_total += refused
    if touched:
        files += 1
        if not DRY:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=1)
        report.append({"file": os.path.basename(p), "fills": touched})

print("files written: %d   cells filled: %d   cells refused as impossible: %d%s"
      % (files, total, refused_total, "   (dry run)" if DRY else ""))
by_label = {}
for r in report:
    for t in r["fills"]:
        by_label[t["label"]] = by_label.get(t["label"], 0) + 1
print("by row:", by_label)
if not DRY:
    with open(os.path.join(BASE, "_opex_ebit_fills.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
