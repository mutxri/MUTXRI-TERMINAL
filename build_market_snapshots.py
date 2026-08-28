#!/usr/bin/env python3
"""build_market_snapshots.py - rebuild market_<EX>.json for ALL exchanges
from the per-security history files (max range = since IPO).

For every listing with a history file, this produces:
  sym, ticker, name, price (latest close), chgPct (vs prev close),
  volume (latest), w52High, w52Low (from bars), ipo (first bar date),
  currency, sector, instrument.

Securities with NO history file (NGX/NSE + structured notes) keep their
existing snapshot row if present, else are listed with price=null.
"""
import json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static_data")
HIST = os.path.join(STATIC, "history")

def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def build(ex):
    stocks = load_json(os.path.join(BASE, "stocks.json"))["stocks"].get(ex, [])
    # listings carry real prices for NGX/NSE (no Yahoo history there)
    listing = {}
    lp = os.path.join(STATIC, f"listing_{ex}.json")
    if os.path.exists(lp):
        for s in load_json(lp).get("stocks", []):
            sym = s.get("sym") or s.get("ticker")
            if sym:
                listing[sym] = s
    out_rows = []
    covered = 0
    for s in stocks:
        sym = s.get("sym") or s.get("ticker")
        row = {
            "sym": sym, "ticker": s.get("ticker"), "name": s.get("name"),
            "price": None, "chgPct": None, "volume": None,
            "w52High": None, "w52Low": None, "ipo": None,
            "currency": s.get("currency"), "sector": s.get("sector"),
            "instrument": s.get("instrument", "common"),
        }
        if sym:
            hf = os.path.join(HIST, sym.replace("/", "_") + ".json")
            mf = os.path.join(HIST, sym.replace("/", "_") + ".max.json")
            src = mf if os.path.exists(mf) else (hf if os.path.exists(hf) else None)
            # 52W range MUST come from the daily file (same price scale);
            # the max file mixes scales across splits/corporate actions
            daily_src = hf if os.path.exists(hf) else None
            if src:
                try:
                    d = load_json(src)
                    bars = d.get("bars", [])
                    if bars:
                        last = bars[-1]
                        prev = bars[-2] if len(bars) > 1 else last
                        row["price"] = last["c"]
                        row["volume"] = last.get("v")
                        if prev and prev.get("c") and last["c"] is not None:
                            row["chgPct"] = round((last["c"] - prev["c"]) / prev["c"] * 100, 4)
                        row["ipo"] = datetime.datetime.utcfromtimestamp(bars[0]["t"]).strftime("%Y-%m-%d")
                        row["currency"] = d.get("currency") or row["currency"]
                        covered += 1
                    # 52W from daily bars (last 260), winsorized against
                    # Yahoo glitch bars (e.g. SBK 2025-03-31 low=227 with 109M vol)
                    if daily_src:
                        try:
                            db = load_json(daily_src).get("bars", [])
                            if db:
                                recent = db[-260:]
                                highs = [b["h"] for b in recent if b.get("h") is not None]
                                lows = [b["l"] for b in recent if b.get("l") is not None]
                                if lows:
                                    med = sorted(lows)[len(lows) // 2]
                                    lows = [x for x in lows if x > med * 0.5]
                                if highs:
                                    medh = sorted(highs)[len(highs) // 2]
                                    highs = [x for x in highs if x < medh * 2.0]
                                if highs:
                                    row["w52High"] = max(highs)
                                if lows:
                                    row["w52Low"] = min(lows)
                        except Exception:
                            pass
                except Exception:
                    pass
            # NGX/NSE fallback: real prices from the listing snapshot
            if row["price"] is None and sym in listing:
                ls = listing[sym]
                row["price"] = ls.get("price")
                row["chgPct"] = ls.get("chgPct")
                row["volume"] = ls.get("volume")
                row["currency"] = ls.get("currency") or row["currency"]
                if row["price"] is not None:
                    covered += 1
        out_rows.append(row)
    return out_rows, covered

def main():
    total = covered_total = 0
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        rows, covered = build(ex)
        with open(os.path.join(STATIC, f"market_{ex}.json"), "w", encoding="utf-8") as f:
            json.dump({"stocks": rows, "asOf": datetime.datetime.now().isoformat(), "covered": covered}, f)
        total += len(rows)
        covered_total += covered
        print(f"{ex}: {covered}/{len(rows)} covered -> market_{ex}.json")
    print(f"TOTAL: {covered_total}/{total}")

if __name__ == "__main__":
    main()
