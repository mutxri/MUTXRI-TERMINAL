#!/usr/bin/env python3
"""sync_volumes.py - one volume per security, dated, on every surface.

The terminal was showing two different volumes for the same stock. The watchlist
and the market rail read listing_<EX>.json, whose volume is an undated scrape.
The screener reads data built from market_<EX>.json, whose volume is the latest
price-history bar and carries that bar's session date. They disagreed on 298 of
324 JSE securities and on every EGX one: ENGC read 10,115,542 shares in the
listing and 128,206 in the snapshot.

market_<EX>.json wins, because it is the number that can be traced to a session:
build_market_snapshots takes volume from the last bar and keeps turnover only
where it reconciles with that volume. This copies the volume and its session date
back into listing_<EX>.json so every reader agrees, and records how much of each
board actually reported.

Three cases per listed security:
  * the snapshot has a dated volume  -> the listing takes it, with volDate
  * the snapshot has no volume for it -> the listing keeps its own number, with
    volDate null. A missing bar means thin price history, not a day with no
    trading: on the NSE the listing covers 56 of 64 securities against the
    snapshot's 35, and where both have a figure they agree on 33 of 35. Clearing
    those would delete real data scraped from the exchange's own board.
  * the snapshot has no row at all   -> same, the listing's number stands undated.

Note for the next run: build_market_snapshots falls back to the listing's volume
when a security has no bar, so after a sync that fallback reads a figure this
wrote. That is intended - it is the last dated volume rather than an unrelated
one - but it means a stale bar keeps its date rather than inventing a new one.

usage: python sync_volumes.py [--dry-run]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static_data")
EXCHANGES = ["JSE", "NGX", "NSE", "EGX"]
DRY = "--dry-run" in sys.argv


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def key(row):
    return str(row.get("ticker") or row.get("sym") or "").split(".")[0].upper()


def session(row):
    for f in ("asOf", "date", "session"):
        v = row.get(f)
        if v:
            s = str(v)[:10]
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                return s
    return None


def sync(ex):
    lp = os.path.join(STATIC, "listing_%s.json" % ex)
    mp = os.path.join(STATIC, "market_%s.json" % ex)
    if not (os.path.exists(lp) and os.path.exists(mp)):
        print("  %-4s missing listing or market file - skipped" % ex)
        return
    with open(lp, encoding="utf-8") as fh:
        listing = json.load(fh)
    with open(mp, encoding="utf-8") as fh:
        market = json.load(fh)
    mrows = {key(r): r for r in market.get("stocks", [])}

    took = cleared = kept = 0
    total = 0.0
    reported = 0
    dates = set()
    for row in listing.get("stocks", []):
        m = mrows.get(key(row))
        if m is None:
            row["volDate"] = None
            if num(row.get("volume")):
                kept += 1
            continue
        mv = num(m.get("volume"))
        if mv is None:
            row["volDate"] = None
            if num(row.get("volume")):
                kept += 1
            continue
        d = session(m)
        row["volume"] = mv
        row["volDate"] = d
        took += 1
        if mv > 0:
            if d:
                dates.add(d)

    for row in listing.get("stocks", []):
        v = num(row.get("volume"))
        if v and v > 0:
            total += v
            reported += 1
    listing["volumeTotal"] = total
    listing["volumeReported"] = reported
    listing["volumeSecurities"] = len(listing.get("stocks", []))
    listing["volumeAsOf"] = max(dates) if dates else None
    if not DRY:
        with open(lp, "w", encoding="utf-8") as fh:
            json.dump(listing, fh, ensure_ascii=False)
    print("  %-4s %3d dated from snapshot, %3d kept undated (%d) | "
          "board total %s shares across %d of %d securities%s"
          % (ex, took, kept, cleared, format(int(total), ","), reported,
             len(listing.get("stocks", [])),
             (" | newest session %s" % listing["volumeAsOf"]) if listing["volumeAsOf"] else ""))


def main():
    print("volume sync%s" % (" (dry run)" if DRY else ""))
    for ex in EXCHANGES:
        sync(ex)
    if DRY:
        print("  dry run - nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
