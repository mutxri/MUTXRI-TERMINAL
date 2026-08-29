#!/usr/bin/env python3
"""fetch_egx_majors.py - fetch 1y daily history for the most important EGX
securities (liquid/major names the user will click). Slow pace (2.5s) +
3 retries with backoff to dodge Yahoo throttle. Writes the same format as
fetch_history.py: static_data/history/<SYM>.json {sym,name,currency,bars}.
"""
import json, os, sys, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
STOCKS = os.path.join(BASE, "stocks.json")

def yahoo_chart(sym, rng="1y", ivl="1d"):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={ivl}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        return None
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = (r0.get("indicators") or {}).get("quote") or [{}]
    q0 = q[0] if q else {}
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
    for attempt in range(4):
        try:
            bars = yahoo_chart(sym)
            if bars and len(bars) >= 2:
                with open(out, "w", encoding="utf-8") as f:
                    json.dump({"sym": sym, "name": name, "currency": cur, "bars": bars}, f)
                return True
            # empty - could be throttle; backoff and retry
            if attempt < 3:
                time.sleep(6 + attempt * 6)
        except Exception:
            if attempt < 3:
                time.sleep(5 + attempt * 5)
    return False

def main():
    stocks = json.load(open(STOCKS, encoding="utf-8"))["stocks"]
    egx = stocks.get("EGX", [])
    # the majors: filter to liquid names (skip the tiny ones)
    # prioritize: known major EGX tickers
    MAJORS = ["COMI", "ETEL", "HRHO", "SWDY", "CIEB", "ORAS", "TMGH", "EAST", "PHAR",
              "JUFO", "AMOC", "EFIH", "ADIB", "AIBK", "CCAP", "EKHO", "ESRS", "ISMA",
              "DOMT", "ORWE", "EDFM", "MANT", "ELSW", "ELKA", "SKPC", "PHDC", "MNHD",
              "HELI", "TALAAT", "SODIC", "TMGT", "NELK", "SMFR", "FWRY", "ELEC", "RITH",
              "ABUK", "CLHO", "ORASCOM", "BTFH", "QHGR", "SHFT", "AMER", "ELSH"]
    targets = []
    seen = set()
    for s in egx:
        sym = s.get("sym") or s.get("ticker")
        tkr = (s.get("ticker") or "").upper()
        if not sym:
            continue
        if tkr in MAJORS and tkr not in seen:
            seen.add(tkr)
            targets.append((sym, tkr, s.get("name", ""), s.get("currency", "")))
    # also add any with real price (liquid) not already included
    for s in egx:
        sym = s.get("sym") or s.get("ticker")
        tkr = (s.get("ticker") or "").upper()
        if not sym or tkr in seen:
            continue
        if s.get("price") is not None:
            seen.add(tkr)
            targets.append((sym, tkr, s.get("name", ""), s.get("currency", "")))
    print(f"EGX targets: {len(targets)}")
    done = fail = skip = 0
    for i, (sym, tkr, name, cur) in enumerate(targets):
        out = os.path.join(HIST, sym.replace("/", "_") + ".json")
        if os.path.exists(out):
            try:
                d = json.load(open(out, encoding="utf-8"))
                if len(d.get("bars", [])) >= 2:
                    skip += 1
                    continue
            except Exception:
                pass
        ok = fetch_one(sym, name, cur, out)
        if ok:
            done += 1
        else:
            fail += 1
        if (i + 1) % 5 == 0:
            print(f"  {i+1}/{len(targets)} (done {done}, fail {fail}, skip {skip})", flush=True)
        time.sleep(2.5)
    print(f"DONE: {done} fetched, {fail} failed, {skip} existing")

if __name__ == "__main__":
    main()
