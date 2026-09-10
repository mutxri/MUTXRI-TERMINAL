#!/usr/bin/env python3
"""check_market_integrity.py - prove the market_<EX>.json rows a user reads as
ONE quote block actually belong to one session and agree with each other.

Run after build_market_snapshots.py (refresh_all does this in step 2). It is a
REPORT: it never edits data, so a failing check is a data problem to fix at the
source, not something to paper over.

Checks per row:
  1. chgPct == (price - prevClose) / prevClose          (the panel prints all 3)
  2. marketCap == price * sharesIssued                  (when both are present)
  3. range52w contains price                            (else the range is a lie)
  4. turnover reconciles with price * volume            (when present)
  5. every row carries an asOf session date             (no undated prices)
Flags a board as FROZEN when its newest session is more than 4 calendar days
behind the newest session across the four boards.

usage: python check_market_integrity.py [--quiet]
exit code 1 if any hard check fails, so refresh_all / CI can gate on it.
"""
import json, os, sys, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static_data")
EXS = ["JSE", "EGX", "NGX", "NSE"]


def num(v):
    if v is None or isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def parse_short(s):
    if s is None:
        return None
    x = str(s).strip()
    mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}.get(x[-1:].upper(), 1)
    if mult != 1:
        x = x[:-1]
    v = num(x)
    return None if v is None else v * mult


def main():
    quiet = "--quiet" in sys.argv
    newest = {}
    report = {}
    for ex in EXS:
        p = os.path.join(STATIC, f"market_{ex}.json")
        if not os.path.exists(p):
            print(f"{ex}: market_{ex}.json MISSING")
            continue
        d = json.load(open(p, encoding="utf-8"))
        rows = d.get("stocks", [])
        bad = {"chg": [], "mcap": [], "range": [], "turnover": [], "undated": []}
        for r in rows:
            t = r.get("ticker") or r.get("sym")
            px, pc = num(r.get("price")), num(r.get("prevClose"))
            chg = num(r.get("chgPct"))
            if px is not None and pc and chg is not None:
                impl = (px - pc) / pc * 100
                if abs(impl - chg) > 0.25:
                    bad["chg"].append((t, chg, round(impl, 2)))
            sh = num(r.get("sharesIssued"))
            mc = parse_short(r.get("marketCap"))
            # JSE quotes in ZAc (cents) while a market cap is in ZAR, so the
            # comparison needs the same scale the display uses
            scale = 100.0 if str(r.get("currency")) == "ZAc" else 1.0
            if mc is not None and px is not None and sh:
                if abs(mc - (px / scale) * sh) / ((px / scale) * sh) > 0.05:
                    bad["mcap"].append((t, r.get("marketCap"), round((px / scale) * sh)))
            r52 = r.get("range52w")
            if r52 and px is not None:
                parts = [num(x) for x in str(r52).split("-")]
                if len(parts) == 2 and None not in parts and not (parts[0] <= px <= parts[1]):
                    bad["range"].append((t, r52, px))
            tv = parse_short(r.get("turnover"))
            vol = num(r.get("volume"))
            if tv is not None and px is not None and vol:
                if abs(tv - (px / scale) * vol) / ((px / scale) * vol) > 0.20:
                    bad["turnover"].append((t, r.get("turnover"), round(px * vol)))
            if px is not None and not r.get("asOf"):
                bad["undated"].append(t)
        priced = [r for r in rows if r.get("price") is not None]
        sessions = sorted({r.get("asOf") for r in rows if r.get("asOf")})
        newest[ex] = sessions[-1] if sessions else None
        report[ex] = (len(rows), len(priced), sessions, bad)
        print(f"{ex}: {len(priced)}/{len(rows)} priced | sessions {sessions[0] if sessions else '-'} .. "
              f"{sessions[-1] if sessions else '-'} ({len(sessions)} distinct) | "
              f"undated prices {len(bad['undated'])} | chg mismatches {len(bad['chg'])} | "
              f"mcap mismatches {len(bad['mcap'])} | 52w broken {len(bad['range'])} | "
              f"turnover off {len(bad['turnover'])}")
        if not quiet:
            for k in ("chg", "mcap", "range"):
                for item in bad[k][:5]:
                    print(f"      {k}: {item}")
    dated = [v for v in newest.values() if v]
    if dated:
        latest = max(dated)
        latest_d = datetime.date.fromisoformat(latest)
        for ex, v in newest.items():
            if not v:
                continue
            lag = (latest_d - datetime.date.fromisoformat(v)).days
            if lag > 4:
                print(f"FROZEN: {ex} newest session {v} is {lag} days behind {latest}")
    hard = sum(len(report[e][3]["chg"]) + len(report[e][3]["mcap"]) + len(report[e][3]["range"])
               for e in report)
    print(f"HARD CHECK FAILURES: {hard}")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
