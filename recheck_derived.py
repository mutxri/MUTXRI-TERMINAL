#!/usr/bin/env python3
"""Re-check pipeline-derived cells against current inputs and blank stale ones.

Balance-sheet inputs are joined by PERIOD LABEL (never array position), because
the balance and income files can carry different period lists. Income inputs are
positional within the income file. Cash-flow inputs are positional.

Only identities the derivation pipeline ships are checked; custom one-off
derivations (bank income sums, etc.) are left alone.
Usage: python3 recheck_derived.py [--apply]
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
APPLY = "--apply" in sys.argv

I_ALIAS = {
    "np": ("net profit", "net income", "profit after tax", "profit for the year"),
    "rev": ("revenue", "total revenue", "revenue from operations", "net revenue"),
    "gp": ("gross profit", "gross profit (loss)", "gross income"),
    "ebit": ("operating profit (ebit)", "operating profit", "operating income", "ebit"),
    "cos": ("cost of sales", "cost of revenue", "cost of goods sold"),
    "opex": ("operating expenses",),
}
B_ALIAS = {
    "eq": ("total equity", "total stockholders' equity", "total shareholders' equity"),
    "ta": ("total assets",),
    "tl": ("total liabilities",),
}
C_ALIAS = {
    "ocf": ("operating cash flow", "net cash from operating activities"),
    "icf": ("investing cash flow", "net cash used in investing activities"),
    "fcf": ("financing cash flow", "net cash from financing activities"),
    "ncc": ("net change in cash", "net increase in cash"),
    "capex": ("capital expenditure", "capex"),
    "fcff": ("free cash flow",),
}

def rowmap(d):
    m = {}
    for r in (d or {}).get("rows") or []:
        m.setdefault(str(r.get("label", "")).strip().lower(), r)
    return m

def vals(m, alts):
    for a in alts:
        if a in m:
            v = m[a].get("values") or []
            if any(x is not None for x in v):
                return v
    return None

def num(x):
    return x if isinstance(x, (int, float)) else None

blanked = {}
files_touched = 0

for f in sorted(os.listdir(FIN)):
    if not f.endswith("__income.json"):
        continue
    sym = f[:-len("__income.json")]
    di = json.load(open(os.path.join(FIN, f), encoding="utf-8"))
    mi = rowmap(di)
    periods = di.get("periods") or []
    if not periods:
        continue
    bp_ = os.path.join(FIN, sym + "__balance.json")
    cp_ = os.path.join(FIN, sym + "__cashflow.json")
    db = json.load(open(bp_, encoding="utf-8")) if os.path.exists(bp_) else None
    dc = json.load(open(cp_, encoding="utf-8")) if os.path.exists(cp_) else None
    mb = rowmap(db) if db else {}
    mc = rowmap(dc) if dc else {}
    bperiods = (db or {}).get("periods") or []

    def bindex(lbl):
        k = str(lbl).strip().upper().replace("FY", "").strip()
        for j, bp in enumerate(bperiods):
            if str(bp).strip().upper().replace("FY", "").strip() == k:
                return j
        return None

    # value arrays (income positional, balance positional-in-its-own-file)
    rev = vals(mi, I_ALIAS["rev"]); gp = vals(mi, I_ALIAS["gp"]); cos = vals(mi, I_ALIAS["cos"])
    ebit = vals(mi, I_ALIAS["ebit"]); opex = vals(mi, I_ALIAS["opex"]); np_ = vals(mi, I_ALIAS["np"])
    ta = vals(mb, B_ALIAS["ta"]) if mb else None
    eq = vals(mb, B_ALIAS["eq"]) if mb else None
    tl = vals(mb, B_ALIAS["tl"]) if mb else None
    ocf = vals(mc, C_ALIAS["ocf"]) if mc else None
    icf = vals(mc, C_ALIAS["icf"]) if mc else None
    fcf = vals(mc, C_ALIAS["fcf"]) if mc else None
    capex = vals(mc, C_ALIAS["capex"]) if mc else None

    hits = []

    def gv(arr, i, kind):
        """value at income-period index i; kind 'i' positional, 'b' balance-by-label."""
        if arr is None:
            return None
        if kind == "i":
            return arr[i] if i < len(arr) else None
        j = bindex(periods[i])
        return arr[j] if j is not None and j < len(arr) else None

    def chk(lab, ka, kb, fn, mult=1.0, b_denom=False):
        row = mi.get(lab)
        if not row or not row.get("derived"):
            return
        sv = row.get("values") or []
        for i in range(len(periods)):
            if i >= len(sv) or sv[i] is None:
                continue
            a = gv(ka[0], i, ka[1]); b = gv(kb[0], i, kb[1])
            if num(a) is None or num(b) is None:
                continue
            if b_denom and float(b) <= 0:
                continue
            expect = round(fn(float(a), float(b)) * mult, 2)
            if abs(sv[i] - expect) > max(abs(expect) * 0.011, 0.011):
                hits.append((row["label"], i, sv[i], expect))

    # ratios (balance denominator joined by label)
    chk("roe (%)", (np_, "i"), (eq, "b"), lambda x, y: x / y * 100.0, b_denom=True)
    chk("roa (%)", (np_, "i"), (ta, "b"), lambda x, y: x / y * 100.0, b_denom=True)
    chk("net margin (%)", (np_, "i"), (rev, "i"), lambda x, y: x / y * 100.0, b_denom=True)
    chk("gross margin (%)", (gp, "i"), (rev, "i"), lambda x, y: x / y * 100.0, b_denom=True)
    chk("operating margin (%)", (ebit, "i"), (rev, "i"), lambda x, y: x / y * 100.0, b_denom=True)
    chk("debt to equity", (tl, "b"), (eq, "b"), lambda x, y: x / y, b_denom=True)
    # income rows (positional)
    chk("gross profit", (rev, "i"), (cos, "i"), lambda x, y: x - y)
    chk("cost of sales", (rev, "i"), (gp, "i"), lambda x, y: x - y)
    chk("operating expenses", (gp, "i"), (ebit, "i"), lambda x, y: x - y)
    chk("operating profit (ebit)", (gp, "i"), (opex, "i"), lambda x, y: x - y)

    if not hits:
        continue
    for lab, i, s, e in hits:
        r = mi.get(lab.lower())
        if r and i < len(r.get("values") or []):
            r["values"][i] = None
        blanked.setdefault(lab, []).append((sym, periods[i] if i < len(periods) else i, s, e))
    files_touched += 1
    if APPLY:
        json.dump(di, open(os.path.join(FIN, f), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("files touched: %d" % files_touched)
tot = 0
for lab, arr in sorted(blanked.items(), key=lambda x: -len(x[1])):
    print("   %4d  %s" % (len(arr), lab))
    tot += len(arr)
print("TOTAL blanked: %d" % tot)
print("dry run" if not APPLY else "APPLIED")
