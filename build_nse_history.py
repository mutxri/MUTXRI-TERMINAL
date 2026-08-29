#!/usr/bin/env python3
"""build_nse_history.py - build REAL NSE OHLC history from the official
NSE ticker API (nsenairobi.nse.co.ke). Each run appends today's bar to a
per-symbol history file (static_data/history/NSE_<SYM>.json). Run daily
(via cron) to accumulate a genuine candle series.

The NSE has NO free historical data feed (they sell it: Ksh 350/download),
so the only honest way to get NSE candles is to archive the official
snapshot day by day. This script also re-fetches the current snapshot so
running it once seeds today's bar.
"""
import json, os, time, urllib.request, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

API = "https://nsenairobi.nse.co.ke/nseticker/api/v1/ticker"
ACCOUNT = "KE3000009674"  # public value from NSE's own eembed.js

def fetch_snapshot(retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API, data=json.dumps({"nopage": "true", "isinno": ACCOUNT}).encode(),
                                         headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
                                         method="POST")
            r = urllib.request.urlopen(req, timeout=30)
            d = json.loads(r.read().decode())
            items = d if isinstance(d, list) else d.get("data") or d.get("result") or []
            if items:
                return items
        except Exception as e:
            print(f"  retry {attempt+1}: {str(e)[:60]}")
            time.sleep(4 * (attempt + 1))
    return None

def get_field(stock, *names):
    for n in names:
        if stock.get(n) is not None:
            return stock[n]
    return None

def main():
    items = fetch_snapshot()
    if not items:
        print("FAILED to fetch NSE snapshot")
        return 1

    today = datetime.date.today().isoformat()
    saved = 0
    skipped = 0
    for s in items:
        tkr = get_field(s, "ticker", "sym", "code")
        if not tkr:
            continue
        price = get_field(s, "price", "ltp", "todayClose")
        if price is None:
            skipped += 1
            continue
        open_ = get_field(s, "open", "todayOpen") or price
        high = get_field(s, "high", "dayHigh") or price
        low = get_field(s, "low", "dayLow") or price
        close = price
        volume = get_field(s, "volume") or 0
        # round to 2dp (KES)
        bar = {"t": today, "o": round(float(open_), 2), "h": round(float(high), 2),
               "l": round(float(low), 2), "c": round(float(close), 2), "v": int(volume)}
        path = os.path.join(HIST, f"NSE_{tkr}.json")
        data = {"bars": []}
        if os.path.exists(path):
            try:
                data = json.load(open(path, encoding="utf-8"))
            except Exception:
                data = {"bars": []}
        bars = data.get("bars", [])
        # dedupe: if today's bar exists, replace it; else append
        if bars and bars[-1].get("t") == today:
            bars[-1] = bar
        else:
            bars.append(bar)
        data["bars"] = bars[-1500:]  # cap at 1500 bars
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        saved += 1

    print(f"DONE: {saved} NSE symbols archived ({today} bar appended), {skipped} skipped (no price)")
    return 0

if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
