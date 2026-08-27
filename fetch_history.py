#!/usr/bin/env python3
"""fetch_history.py - bulk-fetch 1y daily OHLC history from Yahoo for every
JSE/EGX security and write per-security JSON files under static_data/history/.

Files: static_data/history/<SYM>.json with {"sym","name","currency","bars":[{t,o,h,l,c,v},...]}
Honest data: Yahoo EOD daily bars. NGX/NSE have NO free historical feed -> skipped
(with a manifest entry so the frontend shows an honest 'no history' state).
Resumes: completed symbols are skipped on re-run.
"""
import json, os, sys, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "history")
os.makedirs(OUT, exist_ok=True)

def load_listing(ex):
    p = os.path.join(BASE, "static_data", f"listing_{ex}.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("stocks", [])

def yahoo_chart(sym, rng="1y", ivl="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={ivl}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

def fetch_one(sym, name, currency, out):
    try:
        d = yahoo_chart(sym)
        res = (d.get("chart") or {}).get("result") or []
        if not res:
            return False
        r0 = res[0]
        ts = r0.get("timestamp") or []
        q = r0.get("indicators", {}).get("quote", [{}])[0]
        o, h, l, c, v = q.get("open"), q.get("high"), q.get("low"), q.get("close"), q.get("volume")
        bars = []
        for i in range(len(ts)):
            if i >= len(c) or c[i] is None:
                continue
            bars.append({
                "t": ts[i], "o": o[i] if i < len(o) and o[i] is not None else c[i],
                "h": h[i] if i < len(h) and h[i] is not None else c[i],
                "l": l[i] if i < len(l) and l[i] is not None else c[i],
                "c": c[i],
                "v": v[i] if i < len(v) and v[i] is not None else 0,
            })
        if not bars:
            return False
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"sym": sym, "name": name, "currency": currency, "bars": bars}, f)
        return True
    except Exception:
        return False

def main(ex_list, start=0):
    symbols = []
    for ex in ex_list:
        for s in load_listing(ex):
            sym = s.get("sym") or s.get("ticker")
            if sym:
                symbols.append((ex, sym, s.get("name", ""), s.get("currency", "")))
    print(f"total symbols: {len(symbols)}")
    done = fail = skip = 0
    for i, (ex, sym, name, cur) in enumerate(symbols):
        if i < start:
            continue
        out = os.path.join(OUT, sym.replace("/", "_") + ".json")
        if os.path.exists(out):
            skip += 1
            continue
        ok = fetch_one(sym, name, cur, out)
        if ok:
            done += 1
        else:
            fail += 1
            # record the failure so we don't retry forever: write an empty marker
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"sym": sym, "bars": []}, f)
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(symbols)} (done {done}, fail {fail}, skip {skip})", flush=True)
        time.sleep(0.4)
    print(f"DONE: {done} fetched, {fail} no-data, {skip} already present")

if __name__ == "__main__":
    exs = sys.argv[1].split(",") if len(sys.argv) > 1 else ["JSE", "EGX"]
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    main(exs, start)
