#!/usr/bin/env python3
"""Blank derived cells that are arithmetically impossible, so the derivation
pipeline can recompute them from the CURRENT filed inputs.

Stale derived figures are the bug: a row is derived once, then a later merge or
re-parse updates the filed inputs it was computed from, and the derived value
stays behind. The panel then prints a negative operating expense or a net
change in cash that does not equal the three cash-flow sections it names.

Blanks (never a filed value):
  - derived Operating Expenses / Cost of Sales / Revenue  < 0  (magnitudes)
  - derived Operating Profit (EBIT) > Gross Profit            (EBIT = GP - OpEx)
  - derived Net Change in Cash that contradicts OCF+ICF+FCF
  - derived ratios beyond the ceiling the ratio script applies
Usage: python3 cleanup_derived.py [--apply]
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
APPLY = "--apply" in sys.argv

CEILING = {"ROE (%)": 200.0, "ROA (%)": 100.0, "Net Margin (%)": 100.0,
           "Gross Margin (%)": 100.0, "Operating Margin (%)": 100.0,
           "Debt to Equity": 100.0}
MAGNITUDES = ("operating expenses", "cost of sales", "revenue")
TOL = 0.02

blanked = {}
files_touched = 0

for f in sorted(os.listdir(FIN)):
    if "__" not in f or not f.endswith(".json"):
        continue
    p = os.path.join(FIN, f)
    d = json.load(open(p, encoding="utf-8"))
    m = {str(r.get("label", "")).strip().lower(): r for r in d.get("rows", [])}
    periods = d.get("periods") or []
    hits = []

    def gv(*alts):
        for a in alts:
            if a in m:
                v = m[a].get("values") or []
                if any(x is not None for x in v):
                    return v
        return None

    # magnitude rows that are derived and negative
    for lab in MAGNITUDES:
        r = m.get(lab)
        if not r or not r.get("derived"):
            continue
        for i, v in enumerate(r.get("values") or []):
            if isinstance(v, (int, float)) and v < 0:
                hits.append((lab, i, "negative derived magnitude"))

    # derived EBIT above gross profit
    ebit = m.get("operating profit (ebit)")
    gp = gv("gross profit", "gross profit (loss)", "gross income")
    if ebit and ebit.get("derived") and gp:
        for i, v in enumerate(ebit.get("values") or []):
            if isinstance(v, (int, float)) and i < len(gp) and isinstance(gp[i], (int, float)):
                if v > gp[i] * 1.02 + 1.0:
                    hits.append(("operating profit (ebit)", i, "derived EBIT exceeds gross profit"))

    # derived Net Change in Cash contradicting the three sections
    ncc = m.get("net change in cash") or m.get("net increase in cash")
    if ncc and ncc.get("derived"):
        ocf = gv("operating cash flow", "net cash from operating activities")
        icf = gv("investing cash flow", "net cash used in investing activities")
        fcf = gv("financing cash flow", "net cash from financing activities")
        if ocf and icf and fcf:
            for i, v in enumerate(ncc.get("values") or []):
                if not isinstance(v, (int, float)):
                    continue
                if i < len(ocf) and i < len(icf) and i < len(fcf):
                    if all(isinstance(x, (int, float)) for x in (ocf[i], icf[i], fcf[i])):
                        expect = ocf[i] + icf[i] + fcf[i]
                        if abs(v - expect) > max(abs(v) * TOL, 1.0):
                            hits.append((ncc["label"], i, "derived NCC != OCF+ICF+FCF"))

    # derived ratios beyond the ceiling
    for lab, cap in CEILING.items():
        r = m.get(lab.lower())
        if not r or not r.get("derived"):
            continue
        for i, v in enumerate(r.get("values") or []):
            if isinstance(v, (int, float)) and abs(v) > cap:
                hits.append((r["label"], i, "derived ratio beyond ceiling"))

    if not hits:
        continue
    for lab, i, reason in hits:
        r = m.get(lab.lower())
        if r and i < len(r.get("values") or []):
            r["values"][i] = None
        blanked.setdefault(reason, 0)
        blanked[reason] += 1
    files_touched += 1
    if APPLY:
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("files touched: %d" % files_touched)
for k, v in sorted(blanked.items(), key=lambda x: -x[1]):
    print("   %5d  %s" % (v, k))
print("dry run" if not APPLY else "APPLIED")
