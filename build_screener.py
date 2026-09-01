#!/usr/bin/env python3
"""build_screener.py - rebuild screener_<EX>.json from market_<EX>.json
(single source of price truth, per runbook Fix 4). Rows whose |chgPct| exceeds
the exchange's daily band cap are marked None (honest 'no data'), never clamped.
Carries divYield forward from the existing screener file."""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
CAPS = {"JSE": 50.0, "EGX": 25.0, "NGX": 15.0, "NSE": 15.0}

def main():
    for ex, cap in CAPS.items():
        mp = os.path.join(SD, f"market_{ex}.json")
        sp = os.path.join(SD, f"screener_{ex}.json")
        if not os.path.exists(mp):
            print(f"{ex}: no market file, skip"); continue
        market = json.load(open(mp, encoding="utf-8"))
        old = {}
        if os.path.exists(sp):
            try:
                o = json.load(open(sp, encoding="utf-8"))
                for r in o.get("stocks", []):
                    old[r.get("sym") or r.get("ticker")] = r
            except Exception:
                pass
        capped = 0
        rows = []
        for s in market.get("stocks", []):
            sym = s.get("sym") or s.get("ticker") or ""
            chg = s.get("chgPct")
            if isinstance(chg, (int, float)) and abs(chg) > cap:
                capped += 1
                chg = None  # data error beyond the exchange's daily band: honest None
            prev = old.get(sym, {})
            rows.append({
                "sym": sym,
                "ticker": s.get("ticker"),
                "name": s.get("name", ""),
                "exchange": ex,
                "sector": s.get("sector"),
                "currency": s.get("currency"),
                "price": s.get("price"),
                "chgPct": chg,
                "volume": s.get("volume"),
                "divYield": prev.get("divYield"),
                "live": bool(s.get("price") is not None),
            })
        out = {"count": len(rows), "filters_applied": old.get("filters_applied", {}),
               "sort": old.get("sort", {"by": "chgPct", "dir": "desc"}), "stocks": rows}
        json.dump(out, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{ex}: {len(rows)} rows | capped {capped} -> None")

if __name__ == "__main__":
    main()
