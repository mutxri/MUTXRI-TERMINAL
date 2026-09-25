#!/usr/bin/env python3
"""align_short_rows.py - realign rows whose values array is shorter than periods.

A statement file stores values POSITIONALLY against periods, so a row carrying
fewer values than there are periods prints its figures under the WRONG years.
This does not guess: for each short row it tries every possible offset and keeps
the one the printed accounting identities PROVE.

Identities, per statement, with the operator they actually use:

  income    Revenue - Cost of Sales = Gross Profit                      (a - b = c)
            Gross Profit - Operating Expenses = Operating Profit (EBIT)
            Profit Before Tax - Income Tax = Net Profit
  balance   Non-current Assets + Current Assets = Total Assets          (a + b = c)
            Non-current Liabilities + Current Liabilities = Total Liabilities
            Total Liabilities + Total Equity = Total Assets
  cashflow  Operating Cash Flow + Investing Cash Flow = Net Change in Cash
            Operating Cash Flow + Financing Cash Flow = Net Change in Cash
            Investing Cash Flow + Financing Cash Flow = Net Change in Cash

An offset is applied only when it agrees with at least MIN_AGREE identities and
contradicts none, and only when it is the ONE offset that does. Anything else is
left exactly as it is and listed in _short_rows_unresolved.json. No value is
invented: the padding is null, and the row records aligned_from and
identityAgreement.

Usage: python3 align_short_rows.py [--dry]
"""
import json, os, re, sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv
MIN_AGREE = 2

# (statement, operator, triple). income triples read a - b = c; the others a + b = c.
IDENTS = {
  "income": [
    ("Revenue", "Cost of Sales", "Gross Profit"),
    ("Gross Profit", "Operating Expenses", "Operating Profit (EBIT)"),
    ("Profit Before Tax", "Income Tax", "Net Profit"),
  ],
  "balance": [
    ("Non-current Assets", "Current Assets", "Total Assets"),
    ("Non-current Liabilities", "Current Liabilities", "Total Liabilities"),
    ("Total Liabilities", "Total Equity", "Total Assets"),
  ],
  "cashflow": [
    ("Operating Cash Flow", "Investing Cash Flow", "Net Change in Cash"),
    ("Operating Cash Flow", "Financing Cash Flow", "Net Change in Cash"),
    ("Investing Cash Flow", "Financing Cash Flow", "Net Change in Cash"),
  ],
}

def suite(stmt, label):
    return [t for t in IDENTS.get(stmt, []) if label in t]

def target_for(stmt, label, t, o):
    """t is the identity triple, o the two known operands in triple order."""
    a, b, c = t
    o1, o2 = o
    if stmt == "income":          # a - b = c
        if label == a: return o1 + o2      # a = b + c
        if label == b: return o1 - o2      # b = a - c
        return o1 - o2                      # c = a - b
    else:                          # a + b = c
        if label == a: return o2 - o1      # a = c - b
        if label == b: return o2 - o1      # b = c - a
        return o1 + o2                      # c = a + b

changed, unresolved = [], []
scanned = 0
for f in sorted(os.listdir(FIN)):
    m = re.match(r"^(.+)__(income|balance|cashflow)\.json$", f)
    if not m:
        continue
    key, stmt = m.group(1), m.group(2)
    p = os.path.join(FIN, f)
    try:
        rec = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    per = rec.get("periods") or []
    rows = rec.get("rows") or []
    if not per or not rows:
        continue
    P = len(per)
    lab = {}
    for rw in rows:
        lab.setdefault(rw.get("label"), rw.get("values") or [])
    def val(label, j):
        # Only a row carrying a value for EVERY period is trusted as an anchor.
        # A short neighbour is itself positionally shifted, so comparing against
        # it would manufacture contradictions against a correct alignment.
        v = lab.get(label)
        if not v or len(v) < P or j >= len(v):
            return None
        x = v[j]
        return x if isinstance(x, (int, float)) else None
    dirty = False
    for rw in rows:
        vals = rw.get("values") or []
        L = len(vals)
        if L == 0 or L >= P:
            continue
        scanned += 1
        label = rw.get("label")
        tests = suite(stmt, label)
        if not tests:
            continue
        cands = []
        for k in range(0, P - L + 1):
            agree = contra = 0
            for j in range(k, k + L):
                got = vals[j - k]
                if not isinstance(got, (int, float)):
                    continue
                for t in tests:
                    others = [x for x in t if x != label]
                    o1, o2 = val(others[0], j), val(others[1], j)
                    if o1 is None or o2 is None:
                        continue
                    target = target_for(stmt, label, t, (o1, o2))
                    if target == 0 and got == 0:
                        agree += 1
                    elif abs(got - target) <= 0.005 * max(abs(got), abs(target)):
                        agree += 1
                    else:
                        contra += 1
            cands.append((k, agree, contra))
        good = [c for c in cands if c[2] == 0 and c[1] >= MIN_AGREE]
        if len(good) == 1:
            k, agree, _ = good[0]
            rw["values"] = [None] * k + list(vals) + [None] * (P - L - k)
            rw["aligned_from"] = ("positional alignment proved by accounting identity: "
                                  "values moved to periods %d-%d of %d" % (k + 1, k + L, P))
            rw["identityAgreement"] = agree
            dirty = True
            changed.append((key, stmt, label, L, P, k, agree))
        else:
            unresolved.append({"file": f, "stmt": stmt, "label": label, "values": L,
                               "periods": P,
                               "candidates": [{"offset": c[0], "agree": c[1],
                                               "contradict": c[2]} for c in cands]})
    if dirty and not DRY:
        json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("short rows scanned:", scanned)
print("rows realigned:", len(changed))
print("  by statement:", dict(Counter(c[1] for c in changed)))
print("  by label:", dict(Counter(c[2] for c in changed).most_common(14)))
print("rows left alone:", len(unresolved))
for c in changed[:25]:
    print("   ", c)
if not DRY:
    json.dump(unresolved, open(os.path.join(BASE, "_short_rows_unresolved.json"), "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote _short_rows_unresolved.json")
else:
    print("(dry run)")
