#!/usr/bin/env python3
"""fetch_nse_official.py - pull the NSE's official live market snapshot.

Endpoint: POST https://nsenairobi.nse.co.ke/nseticker/api/v1/ticker
  body: {"nopage":"true","isinno":"KE3000009674"}   (NSE's own ticker account)

Returns the official NSE market snapshot (79 securities): issuer, price,
ltp, prev_price, today_open, today_high, today_low, turnover, volume,
change, today_close + market status/time. This is the same official feed
that professional terminals license from the NSE.

Writes static_data/market_NSE.json (merged with names/sectors from the
existing listing) + static_data/nse_extra.json (kept). Labels honestly:
source = "NSE official ticker (nsenairobi.nse.co.ke)".
"""
import json, os, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_MARKET = os.path.join(BASE, "static_data", "market_NSE.json")
OUT_EXTRA = os.path.join(BASE, "static_data", "nse_extra.json")
STOCKS = os.path.join(BASE, "stocks.json")

def fetch_snapshot():
    req = urllib.request.Request(
        "https://nsenairobi.nse.co.ke/nseticker/api/v1/ticker",
        data=json.dumps({"nopage": "true", "isinno": "KE3000009674"}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "Mozilla/5.0",
                 "Origin": "https://www.nse.co.ke", "Referer": "https://www.nse.co.ke/"})
    d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    msg = d["message"]
    snap = msg[0]["snapshot"]
    meta = msg[1].get("updated_at", {}) if len(msg) > 1 else {}
    return snap, meta

def main():
    snap, meta = fetch_snapshot()
    print(f"snapshot: {len(snap)} securities | status {meta.get('market_status')} {meta.get('date')} {meta.get('time')}")

    stocks = json.load(open(STOCKS, encoding="utf-8"))["stocks"]
    nse_listing = stocks.get("NSE", [])
    tkr_info = {}
    for s in nse_listing:
        tkr_info[(s.get("ticker") or "").upper()] = s

    market = {"stocks": [], "asOf": f"NSE {meta.get('date')} {meta.get('time')} ({meta.get('market_status')})"}
    for row in snap:
        tkr = row["issuer"]
        listing = tkr_info.get(tkr, {})
        price = row.get("price")
        prev = row.get("prev_price")
        chg = row.get("change")
        # NSE's "change" field is already the percentage (SCOM 2.16 = 2.16%)
        chg_pct = chg if chg is not None else None
        market["stocks"].append({
            "ticker": tkr,
            "sym": listing.get("sym") or tkr,
            "name": listing.get("name") or tkr,
            "sector": listing.get("sector") or "",
            "price": price,
            "ltp": row.get("ltp"),
            "prevClose": prev,
            "open": row.get("today_open"),
            "high": row.get("today_high"),
            "low": row.get("today_low"),
            "chg": chg,
            "chgPct": chg_pct,
            "volume": row.get("volume"),
            "turnover": row.get("turnover"),
            "todayClose": row.get("today_close"),
            "currency": "KES", "country": "Kenya",
            "source": "NSE official ticker (nsenairobi.nse.co.ke)",
        })

    json.dump(market, open(OUT_MARKET, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DONE: {len(market['stocks'])} stocks -> market_NSE.json (official NSE feed)")

if __name__ == "__main__":
    main()
