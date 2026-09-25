#!/usr/bin/env python3
"""inject_marketcap.py - write raw marketCap + sharesOutstanding into the
statement files (financials/<TKR>__*.json) so bot/statements.load_public()
and the valuation() step can read them.

Fill-only: never overwrites an existing value. No network. Raw integers
(the valuation step's _num() would misparse compact strings like "1.46T").
"""
import json, os, glob

SD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data")
FIN = os.path.join(SD, "financials")

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def scale_for(cur):
    return 100.0 if str(cur) == "ZAc" else 1.0

# raw marketCap + shares per ticker, from market files
mcap = {}
shares = {}
for ex in ("NSE", "NGX", "JSE", "EGX"):
    mp = os.path.join(SD, f"market_{ex}.json")
    if not os.path.exists(mp):
        continue
    m = json.load(open(mp, encoding="utf-8"))
    for s in m.get("stocks", []):
        tkr = s.get("ticker") or s.get("sym")
        if not tkr:
            continue
        px, sh = num(s.get("price")), num(s.get("sharesIssued"))
        if sh is not None:
            shares[tkr] = int(sh)
        if px is not None and sh is not None:
            mcap[tkr] = int(px / scale_for(s.get("currency")) * sh)

changed_files = 0
mcap_filled = shares_filled = 0
for p in glob.glob(os.path.join(FIN, "*__*.json")):
    tkr = os.path.basename(p).split("__")[0]
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    dirty = False
    if not d.get("marketCap") and tkr in mcap:
        d["marketCap"] = mcap[tkr]
        mcap_filled += 1
        dirty = True
    if not d.get("sharesOutstanding") and tkr in shares:
        d["sharesOutstanding"] = shares[tkr]
        shares_filled += 1
        dirty = True
    if dirty:
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        changed_files += 1

print(f"marketCap filled into {mcap_filled} fields | sharesOutstanding {shares_filled} | files touched {changed_files}")
print("DONE")
