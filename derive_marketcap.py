#!/usr/bin/env python3
"""derive_marketcap.py - fill missing marketCap from shares x price.

Reads the EXISTING (correct) market_<EX>.json prices + sharesIssued (filled by
build_shares.py), derives marketCap = price / scale * shares, and writes it into
both market_<EX>.json (compact string) and financials_index.json (raw int).

Fill-only: never overwrites an existing marketCap, never touches prices.
No network. Safe to re-run.
"""
import json, os

SD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data")

def fmt_short(v):
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    for lim, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= lim:
            return f"{x / lim:.2f}".rstrip("0").rstrip(".") + suf
    if abs(x) < 1:
        return (f"{x:.2f}".rstrip("0").rstrip(".") or "0")
    return f"{x:,.0f}"

def scale_for(cur):
    return 100.0 if str(cur) == "ZAc" else 1.0

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# Pass 1: derive per-ticker raw marketCap from market files, collect map.
mcap_map = {}
per_file = {}
for ex in ("NSE", "NGX", "JSE", "EGX"):
    mp = os.path.join(SD, f"market_{ex}.json")
    if not os.path.exists(mp):
        continue
    m = json.load(open(mp, encoding="utf-8"))
    derived = []
    for s in m.get("stocks", []):
        tkr = s.get("ticker") or s.get("sym")
        if not tkr:
            continue
        px, sh = num(s.get("price")), num(s.get("sharesIssued"))
        if px is None or sh is None:
            continue
        mcap = px / scale_for(s.get("currency")) * sh
        if mcap <= 0:
            continue
        mcap_map[tkr] = int(mcap)
        derived.append((tkr, fmt_short(mcap)))
    per_file[ex] = derived
    print(f"{ex}: derivable marketCap for {len(derived)} tickers")

# Pass 2: write compact marketCap into market files (fill missing only).
for ex, derived in per_file.items():
    mp = os.path.join(SD, f"market_{ex}.json")
    m = json.load(open(mp, encoding="utf-8"))
    by_tkr = {t: s for s in m.get("stocks", []) for t in ((s.get("ticker"), s.get("sym")))}
    cnt = 0
    for s in m.get("stocks", []):
        tkr = s.get("ticker") or s.get("sym")
        if not s.get("marketCap") and tkr in mcap_map:
            s["marketCap"] = fmt_short(mcap_map[tkr])
            cnt += 1
    json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ex}: wrote marketCap to {cnt} rows (fill-only)")

# Pass 3: fill financials_index.json marketCap (raw int, fill missing only).
ip = os.path.join(SD, "financials_index.json")
idx = json.load(open(ip, encoding="utf-8"))
cnt = 0
for k, rec in idx.items():
    if not isinstance(rec, dict) or rec.get("marketCap"):
        continue
    v = mcap_map.get(k) or mcap_map.get(k.split(".")[0])
    if v:
        rec["marketCap"] = v
        cnt += 1
json.dump(idx, open(ip, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"financials_index: filled marketCap for {cnt} tickers")
print("DONE")
