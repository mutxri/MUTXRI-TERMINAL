#!/usr/bin/env python3
"""append_nse_bars.py - append one real OHLC bar per NSE security from the
official board snapshot in market_NSE.json.

Background: the NSE history archive under static_data/history/NSE_*.json was
built from ir.nse.co.ke/hist/<TICKER>, which now serves only the NSE's own
ticker (every other symbol returns 406) - there is no remaining bulk source for
Nairobi OHLC history, and Yahoo does not list the NSE at all. What we do still
get daily is the official board snapshot, which carries open/high/low/close and
volume per security. This appends that as a dated bar so each symbol's archive
grows forward from every snapshot instead of staying one bar deep.

Idempotent: re-running for the same session date replaces that day's bar rather
than duplicating it. Never invents a bar for a security with no traded price.
"""
import json, os, re, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
MARKET = os.path.join(BASE, "static_data", "market_NSE.json")


def session_date(as_of):
    """'NSE 28/08/2026 17:03 PM GMT+3 (closed)' -> '2026-08-28'"""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", as_of or "")
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", as_of or "")
    return m.group(1) if m else datetime.date.today().isoformat()


def main():
    market = json.load(open(MARKET, encoding="utf-8"))
    day = session_date(market.get("asOf"))
    added = updated = skipped = 0

    for s in market.get("stocks", []):
        tkr = s.get("ticker") or s.get("sym")
        close = s.get("todayClose") if s.get("todayClose") is not None else s.get("price")
        if not tkr or close is None:
            skipped += 1
            continue
        o = s.get("open") if s.get("open") is not None else close
        h = s.get("high") if s.get("high") is not None else close
        l = s.get("low") if s.get("low") is not None else close
        v = s.get("volume") or 0
        bar = {"t": day, "o": o, "h": h, "l": l, "c": close, "v": v}

        path = os.path.join(HIST, f"NSE_{tkr}.json")
        bars = []
        if os.path.exists(path):
            try:
                bars = json.load(open(path, encoding="utf-8")).get("bars", [])
            except Exception:
                bars = []
        by_day = {b.get("t"): b for b in bars if b.get("t")}
        existed = day in by_day
        by_day[day] = bar
        merged = [by_day[k] for k in sorted(by_day.keys())]
        json.dump({"sym": tkr, "currency": s.get("currency", "KES"),
                   "source": "NSE official board snapshot",
                   "bars": merged[-1500:]},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False)
        if existed:
            updated += 1
        else:
            added += 1

    print(f"NSE {day}: {added} bars appended, {updated} refreshed, "
          f"{skipped} securities with no traded price skipped")


if __name__ == "__main__":
    main()
