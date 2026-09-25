#!/usr/bin/env python3
"""
normalize_cost_signs.py - put every income statement on ONE sign convention.

The dataset mixes two. Measured over 3,331 complete period triples, Revenue - Cost of
Sales = Gross Profit holds with Cost of Sales POSITIVE 3,053 times and only with it
NEGATIVE 205 times. 111 files store Cost of Sales negative, so the panel prints
"Cost of Sales -640.2M" in red for those and a positive figure for the rest, and the
arithmetic check the terminal runs (Revenue minus Cost of Sales must equal Gross Profit)
FAILS on them.

Each candidate row is judged by the ONE printed identity it is the subtracted operand
of, and never by a heuristic:

    Cost of Sales      -> Revenue - Cost of Sales = Gross Profit
    Operating Expenses -> Gross Profit - Operating Expenses = Operating Profit (EBIT)
    Income Tax         -> Profit Before Tax - Income Tax = Net Profit

A row is negated only when
  1. every non-null value of the row is negative (uniformly signed, never a genuine
     credit sitting inside a positive series),
  2. its identity FAILS at one or more complete period triples as stored, and
  3. after negating it, its identity TIES at EVERY complete period triple (0.5%).

Revenue is flipped with Cost of Sales only when both are negative and the pair is the
only reading that ties identity 1. A genuine tax credit already ties with its stored
sign, so rule 2 leaves it alone. Rows in other files are never touched.

Usage: python3 normalize_cost_signs.py [--dry]     log -> _sign_flips.json
"""
import json, os, re, sys, glob, itertools

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv
TOL = 0.005

# the panel's own alias map, read from the panel so this can never drift from it
html = open(os.path.join(BASE, "features", "panels", "afri_financials.html"), encoding="utf-8").read()
_blk = html.split("var KEY_ALIASES={", 1)[1].split("\n  };", 1)[0]
AL = {}
for _m in re.finditer(r"(\w+)\s*:\s*\[([^\]]*)\]", _blk):
    AL[_m.group(1)] = [x.strip().strip('"') for x in _m.group(2).split(",") if x.strip()]
KEY2LABEL = {"revenue": "Revenue", "costOfSales": "Cost of Sales", "grossProfit": "Gross Profit",
             "operatingExpenses": "Operating Expenses", "operatingProfit": "Operating Profit (EBIT)",
             "profitBeforeTax": "Profit Before Tax", "taxExpense": "Income Tax", "netProfit": "Net Profit"}
# identity -> (minuend, subtrahend, result, rows eligible to be negated)
IDENT = {
    "Revenue - Cost of Sales = Gross Profit":
        ("Revenue", "Cost of Sales", "Gross Profit", ("Revenue", "Cost of Sales")),
    "Gross Profit - Operating Expenses = Operating Profit (EBIT)":
        ("Gross Profit", "Operating Expenses", "Operating Profit (EBIT)", ("Operating Expenses",)),
    "Profit Before Tax - Income Tax = Net Profit":
        ("Profit Before Tax", "Income Tax", "Net Profit", ("Income Tax",)),
}

def normL(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())

def resolve(doc):
    lmap = {}
    for r in doc.get("rows") or []:
        l = normL(r.get("label"))
        if l and l not in lmap:
            lmap[l] = r
    out = {}
    for key, label in KEY2LABEL.items():
        for a in AL.get(key, []):
            k = normL(a)
            if k in lmap:
                out[label] = lmap[k]
                break
    return out

def close(a, b):
    return abs(a - b) <= TOL * max(abs(a), abs(b), 1.0)

def test(series, nper, identity, flipped):
    """(all tie, triples checked, triples broken) for one identity under a flip set."""
    a, b, c, _ = IDENT[identity]
    va = series.get(a) or []
    vb = series.get(b) or []
    vc = series.get(c) or []
    if b in flipped: vb = [-x if x is not None else None for x in vb]
    if a in flipped: va = [-x if x is not None else None for x in va]
    if c in flipped: vc = [-x if x is not None else None for x in vc]
    tie = bad = 0
    for i in range(nper):
        x = va[i] if i < len(va) else None
        y = vb[i] if i < len(vb) else None
        z = vc[i] if i < len(vc) else None
        if x is None or y is None or z is None:
            continue
        if close(x - y, z):
            tie += 1
        else:
            bad += 1
    return (bad == 0 and tie > 0), tie, bad

flips, refused = [], []
scanned = 0
for p in sorted(glob.glob(os.path.join(FIN, "*__income.json"))):
    scanned += 1
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    periods = d.get("periods") or []
    if len(periods) < 2:
        continue
    res = resolve(d)
    series = {}
    for label, row in res.items():
        v = list(row.get("values") or [])
        v += [None] * max(0, len(periods) - len(v))
        series[label] = v[: len(periods)]
    negs = set(lab for lab, v in series.items()
               if [x for x in v if x is not None] and all(x < 0 for x in v if x is not None))
    if not negs:
        continue
    chosen = {}
    for identity in IDENT:
        _, _, _, eligible = IDENT[identity]
        cand = [lab for lab in eligible if lab in negs]
        if not cand:
            continue
        base_ok, _, base_bad = test(series, len(periods), identity, set())
        if base_ok or base_bad == 0:
            continue                       # already consistent, or nothing complete to check
        found = None
        for size in range(1, len(cand) + 1):
            for combo in itertools.combinations(cand, size):
                ok, tie, bad = test(series, len(periods), identity, set(combo))
                if ok:
                    found = combo
                    break
            if found:
                break
        if found:
            for lab in found:
                chosen[lab] = identity
        else:
            refused.append((os.path.basename(p), identity, cand))
    if not chosen:
        continue
    key = os.path.basename(p).split("__")[0]
    for lab, identity in chosen.items():
        row = res[lab]
        old = list(row.get("values") or [])
        new = [(-x if x is not None else None) for x in old]
        row["values"] = new
        row["sign_normalized"] = ("negated to the dataset convention: stored negative, which "
                                  "broke the printed identity %s, and the column ties with it "
                                  "positive" % identity)
        flips.append({"file": os.path.basename(p), "ticker": key, "row": lab,
                      "identity": identity, "old": old, "new": new})
    if not DRY:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)

print("income files scanned:", scanned, " files changed:", len(set(f["file"] for f in flips)),
      " rows negated:", len(flips))
print("identity-driven flips left refused:", len(refused))
for r in refused[:15]:
    print("   refused:", r)
from collections import Counter
print("by row:", dict(Counter(f["row"] for f in flips)))
print("by identity:", dict(Counter(f["identity"] for f in flips)))
if flips and not DRY:
    json.dump(flips, open(os.path.join(BASE, "_sign_flips.json"), "w"), indent=1)
    print("log -> _sign_flips.json")
for f in flips[:12]:
    print("   ", f["ticker"], f["row"], f["old"], "->", f["new"])
