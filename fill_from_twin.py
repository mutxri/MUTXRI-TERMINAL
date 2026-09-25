#!/usr/bin/env python3
"""fill_from_twin.py - copy a value from a security's twin statement file.

The same issuer ships under two keys on two of the four boards: EGX as both
<ISIN> and <ticker> (and <ticker>.CA), JSE as both <code> and <code>.JO. The two
files are built by different steps, so one can carry a figure the other has
blank. Where the two files hold the SAME period list and agree on every cell
they both populate, a blank in one is filled from the other: same issuer, same
period, same row, and a value that is already published in the shipped dataset.

Nothing is invented. A cell is filled only when the twin has a number, the
period lists are identical, and the two files never disagree on a shared cell.
Every fill is recorded on the row as filled_from_twin with the source key.

Usage: python3 fill_from_twin.py [--dry]
"""
import json, os, re, sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv
SUFFIXES = (".JO", ".CA")

files = sorted(os.listdir(FIN))
fills = []
skipped_disagree = []

def load(n):
    try:
        return json.load(open(os.path.join(FIN, n), encoding="utf-8"))
    except Exception:
        return None

for stmt in ("income", "balance", "cashflow"):
    for f in files:
        m = re.match(r"^([A-Z0-9\-]+)__%s\.json$" % stmt, f)
        if not m:
            continue
        base = m.group(1)
        a = load(f)
        if not a:
            continue
        for sfx in SUFFIXES:
            tn = base + sfx + "__%s.json" % stmt
            if tn not in files:
                continue
            b = load(tn)
            if not b:
                continue
            pa, pb = a.get("periods") or [], b.get("periods") or []
            if not pa or pa != pb:
                continue
            ra = {r.get("label"): r for r in (a.get("rows") or [])}
            rb = {r.get("label"): (r.get("values") or []) for r in (b.get("rows") or [])}
            # refuse to use a twin that disagrees anywhere on a shared cell
            disagree = 0
            for lab, rw in ra.items():
                va, vb = rw.get("values") or [], rb.get(lab)
                if vb is None:
                    continue
                for i in range(min(len(va), len(vb))):
                    x, y = va[i], vb[i]
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        if abs(x - y) > 0.005 * max(abs(x), abs(y), 1):
                            disagree += 1
            if disagree:
                skipped_disagree.append((base, stmt, sfx, disagree))
                continue
            dirty = False
            for lab, rw in ra.items():
                vb = rb.get(lab)
                if vb is None:
                    continue
                va = rw.get("values")
                if va is None:
                    va = [None] * len(pa)
                    rw["values"] = va
                n = 0
                for i in range(len(pa)):
                    x = va[i] if i < len(va) else None
                    y = vb[i] if i < len(vb) else None
                    if x is None and isinstance(y, (int, float)):
                        while len(va) <= i:
                            va.append(None)
                        va[i] = y
                        n += 1
                if n:
                    rw["filled_from_twin"] = ("%d cell(s) from %s, the same issuer's "
                                              "statement under its other key" % (n, tn))
                    dirty = True
                    fills.append((base, stmt, lab, n, tn))
            if dirty and not DRY:
                json.dump(a, open(os.path.join(FIN, f), "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)

byfile = Counter()
for base, stmt, lab, n, tn in fills:
    byfile[(base, stmt)] += n
print("cells filled from a twin:", len(fills) and sum(n for *_, n, _ in fills) or 0)
print("rows touched:", len(fills))
print("files touched:", len(byfile))
print("by statement:", dict(Counter(k[1] for k in byfile.elements())))
print("twins refused for disagreeing:", len(skipped_disagree))
for k, v in sorted(byfile.items(), key=lambda x: -x[1])[:20]:
    print("   ", k, v)
if DRY:
    print("(dry run)")
