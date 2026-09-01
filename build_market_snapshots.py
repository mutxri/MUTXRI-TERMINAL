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

# widest credible one-day move per exchange - see rebuild_heatmaps.py. A move
# past the cap means the previous close came from a different price scale
# (cents vs currency units, or an unadjusted split), not a real session.
MAX_MOVE = {"JSE": 50.0, "EGX": 25.0, "NGX": 15.0, "NSE": 15.0}


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def num(v):
    """NGX price lists carry volumes as '227,596' strings"""
    if v is None or isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def hist_base(ex, sym):
    """NGX/NSE history files are written NGX_MTNN.json / NSE_SCOM.json, not by
    the raw listing symbol - the chart panel resolves them the same way."""
    safe = sym.replace("/", "_")
    if ex in ("NGX", "NSE"):
        return f"{ex}_{safe.split('.')[0]}"
    return safe


def bar_epoch(t):
    """bars carry epoch seconds (Yahoo) or 'YYYY-MM-DD' (NGX/NSE feeds)"""
    if isinstance(t, (int, float)):
        return int(t)
    try:
        return int(datetime.datetime.strptime(str(t)[:10], "%Y-%m-%d")
                   .replace(tzinfo=datetime.timezone.utc).timestamp())
    except Exception:
        return None

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
    # the exchange-specific collectors (fetch_nse_official.py, the NGX price
    # lists) write richer rows than this builder knows about - open/high/low/
    # prevClose/turnover/marketCap. Carry those forward instead of flattening
    # market_NSE.json down to this builder's field set on every rebuild.
    prior = {}
    mp = os.path.join(STATIC, f"market_{ex}.json")
    if os.path.exists(mp):
        try:
            for r in load_json(mp).get("stocks", []):
                k = r.get("sym") or r.get("ticker")
                if k:
                    prior[k] = r
        except Exception:
            pass

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
            hb = hist_base(ex, sym)
            hf = os.path.join(HIST, hb + ".json")
            mf = os.path.join(HIST, hb + ".max.json")
            # DAILY first: the .max file holds MONTHLY bars, so deriving the
            # day change from it compares this month against last month and
            # the guard below then discards it as non-adjacent. Monthly is only
            # a fallback for securities with no daily history at all.
            src = hf if os.path.exists(hf) else (mf if os.path.exists(mf) else None)
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
                        row["volume"] = num(last.get("v"))
                        # only call it a DAY change when the two bars really are
                        # adjacent sessions - a gappy archive (NSE/NGX) would
                        # otherwise report a five-week move as today's move
                        t_last, t_prev = bar_epoch(last.get("t")), bar_epoch(prev.get("t"))
                        adjacent = (t_last is not None and t_prev is not None
                                    and 0 < (t_last - t_prev) <= 5 * 86400)
                        if last.get("chg") is not None:
                            # the session's own reported day change, recorded
                            # with the bar - correct even when the previous
                            # session is missing from the daily array
                            row["chgPct"] = last["chg"]
                        elif prev and prev.get("c") and last["c"] is not None and adjacent:
                            row["chgPct"] = round((last["c"] - prev["c"]) / prev["c"] * 100, 4)
                        t0 = bar_epoch(bars[0].get("t"))
                        if t0:
                            row["ipo"] = datetime.datetime.utcfromtimestamp(t0).strftime("%Y-%m-%d")
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
            # the exchange's own reported day change beats a recomputed one
            # whenever we could not prove the bars were adjacent sessions
            if row["chgPct"] is None and sym in listing and listing[sym].get("chgPct") is not None:
                row["chgPct"] = num(listing[sym].get("chgPct"))

            # NGX/NSE fallback: real prices from the listing snapshot
            if row["price"] is None and sym in listing:
                ls = listing[sym]
                row["price"] = ls.get("price")
                row["chgPct"] = ls.get("chgPct")
                row["volume"] = num(ls.get("volume"))
                row["currency"] = ls.get("currency") or row["currency"]
                if row["price"] is not None:
                    covered += 1
        cap = MAX_MOVE.get(ex, 50.0)
        if row["chgPct"] is not None and abs(row["chgPct"]) > cap:
            # honest gap beats a fabricated +9900%
            row["chgPct"] = None
            row["chgFlag"] = "suspect-baseline"
        # fresh values win; anything we could not compute keeps what the
        # exchange collector already established
        # carry forward only the fields this builder does not own. Price,
        # change and volume must come from this run's history/listing sources or
        # not at all - inheriting them resurrected a stale market-cap-as-price
        # value for UBN long after the bad bars were purged.
        OWNED = ("price", "chgPct", "volume", "w52High", "w52Low", "ipo", "chgFlag")
        merged = {k: v for k, v in prior.get(sym, {}).items() if k not in OWNED}
        merged.update({k: v for k, v in row.items() if v is not None})
        if row.get("chgPct") is None:
            merged["chgPct"] = row.get("chgPct") if "chgFlag" in row else merged.get("chgPct")
        if "chgFlag" in row:
            merged["chgFlag"] = row["chgFlag"]
        else:
            merged.pop("chgFlag", None)
        out_rows.append(merged)
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
