#!/usr/bin/env python3
"""build_nse_history.py - build REAL NSE OHLC history from the official
NSE ticker API (nsenairobi.nse.co.ke). Each run appends today's bar to a
per-symbol history file (static_data/history/NSE_<SYM>.json). Run daily
(via cron) to accumulate a genuine candle series.

The NSE has NO free historical data feed (they sell it: Ksh 350/download),
so the only honest way to get NSE candles is to archive the official
snapshot day by day. This script also re-fetches the current snapshot so
running it once seeds today's bar.

2026-09-14 fix (NSE changed their API server-side, not an outage):
  1. sanityCheck() in their app now does
     parse_url($request->headers->get('origin'))['host'] without a null
     guard, so any request with no Origin header dies with HTTP 500
     "Undefined index: host". We now always send Origin/Referer.
  2. The response is now wrapped: {"message":[{"snapshot":[...]},
     {"updated_at":{...}}]} instead of a bare list. extract_snapshot()
     unwraps it and still accepts the old shape.
  3. Feed field names are lowercase-snake: issuer, price, today_open,
     today_high, today_low, volume. They are mapped explicitly.
  4. The feed repeats some issuers (KPLC, TCL, CRWN, GLD, SLAM, UMME)
     across boards, so we now take the FIRST row per ticker - last row
     would overwrite e.g. KPLC's ordinary share (~22.15) with an
     unrelated board's quote (6.00).
"""
import json, os, time, urllib.request, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

API = "https://nsenairobi.nse.co.ke/nseticker/api/v1/ticker"
ACCOUNT = "KE3000009674"  # public value from NSE's own eembed.js
ORIGIN = "https://nsenairobi.nse.co.ke"  # required by the API's sanityCheck()


def extract_snapshot(d):
    """Pull the ticker rows out of whatever shape the API returns."""
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for key in ("snapshot", "data", "result"):
            v = d.get(key)
            if isinstance(v, list) and v:
                return v
        msg = d.get("message")
        if isinstance(msg, list):
            for part in msg:
                if isinstance(part, dict):
                    snap = part.get("snapshot")
                    if isinstance(snap, list) and snap:
                        return snap
    return []


def fetch_snapshot(retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API, data=json.dumps({"nopage": "true", "isinno": ACCOUNT}).encode(),
                                         headers={"User-Agent": "Mozilla/5.0",
                                                  "Content-Type": "application/json",
                                                  "Origin": ORIGIN,
                                                  "Referer": ORIGIN + "/"},
                                         method="POST")
            r = urllib.request.urlopen(req, timeout=30)
            d = json.loads(r.read().decode())
            items = extract_snapshot(d)
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
    seen = set()
    for s in items:
        tkr = get_field(s, "ticker", "sym", "code", "issuer")
        if not tkr:
            continue
        if tkr in seen:
            continue  # feed repeats some issuers across boards: first row wins
        price = get_field(s, "price", "ltp", "todayClose", "today_close")
        if price is None:
            skipped += 1
            continue
        open_ = get_field(s, "open", "todayOpen", "today_open") or price
        high = get_field(s, "high", "dayHigh", "today_high") or price
        low = get_field(s, "low", "dayLow", "today_low") or price
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
        seen.add(tkr)
        saved += 1

    print(f"DONE: {saved} NSE symbols archived ({today} bar appended), {skipped} skipped (no price)")
    return 0


if __name__ == "__main__":
    sys_exit = main()
    raise SystemExit(sys_exit)
