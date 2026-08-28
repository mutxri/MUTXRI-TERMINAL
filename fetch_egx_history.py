#!/usr/bin/env python3
"""fetch_egx_history.py - fetch 1y daily history for EGX securities using the
TICKER.CA format (NOT the EGS code - Yahoo doesn't recognize it). Slow pace
(3s) learned from the throttle failures. Writes the same format as
fetch_history.py: static_data/history/<EGS_SYM>.json {sym,name,currency,bars}.
Skips files that already have >=2 bars."""
import json, os, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
STOCKS = os.path.join(BASE, "stocks.json")

def yahoo_chart(sym, rng="1y", ivl="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={ivl}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q0 = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for i, t in enumerate(ts):
        o = (q0.get("open") or [None]*len(ts))[i]
        h = (q0.get("high") or [None]*len(ts))[i]
        l = (q0.get("low") or [None]*len(ts))[i]
        c = (q0.get("close") or [None]*len(ts))[i]
        v = (q0.get("volume") or [None]*len(ts))[i]
        if None in (o, h, l, c):
            continue
        bars.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return bars

def fetch_one(sym, name, cur, out):
    for attempt in range(3):
        try:
            bars = yahoo_chart(sym)
            if len(bars) >= 2:
                with open(out, "w", encoding="utf-8") as f:
                    json.dump({"sym": out.split("\\")[-1].replace(".json", ""), "name": name, "currency": cur, "bars": bars}, f)
                return True
            if attempt < 2:
                time.sleep(5 + attempt * 5)
        except Exception:
            if attempt < 2:
                time.sleep(4 + attempt * 4)
    return False

def main():
    stocks = json.load(open(STOCKS, encoding="utf-8"))["stocks"]
    egx = stocks.get("EGX", [])
    done = fail = skip = 0
    for i, s in enumerate(egx):
        sym = s.get("sym")
        tkr = (s.get("ticker") or "").strip().upper()
        if not sym or not tkr:
            continue
        out = os.path.join(HIST, sym.replace("/", "_") + ".json")
        if os.path.exists(out):
            try:
                d = json.load(open(out, encoding="utf-8"))
                if len(d.get("bars", [])) >= 2:
                    skip += 1
                    continue
            except Exception:
                pass
        ok = fetch_one(tkr + ".CA", s.get("name", ""), s.get("currency", ""), out)
        if ok:
            done += 1
        else:
            fail += 1
        if (i + 1) % 5 == 0:
            print(f"  {i+1}/{len(egx)} (done {done}, fail {fail}, skip {skip})", flush=True)
        time.sleep(3.0)
    print(f"DONE: {done} fetched, {fail} no-data, {skip} existing")

if __name__ == "__main__":
    main()
