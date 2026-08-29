#!/usr/bin/env python3
"""rebuild_heatmaps.py - rebuild static_data/heatmap_<EX>.json FROM
market_<EX>.json so the heatmap and the watchlist can never disagree.

Before this, the two panels read two independent pipelines: the watchlist read
market_<EX>.json (derived from the per-security history bars) while the heatmap
read a snapshot of the backend's live quote cache. They drifted apart - 220/327
JSE cells and 226/374 EGX cells carried a different day-change from the
watchlist row for the same security, and a cents-vs-rand mix-up in the quote
cache produced cells reading +9900%.

Now market_<EX>.json is the single source of price truth. The heatmap keeps its
own presentation metadata (code/short/logo/sector) and takes price, chgPct and
volume from the market snapshot, with a per-exchange sanity cap that nulls out
any move no real session could produce.
"""
import json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data")

# widest credible one-day move per exchange. NGX/NSE run hard price bands
# (10%/10%), EGX has a 20% band, the JSE has none but >50% is a data artifact
# in practice. Anything past the cap is a broken baseline, not a real move.
MAX_MOVE = {"JSE": 50.0, "EGX": 25.0, "NGX": 15.0, "NSE": 15.0}


def num(v):
    """volumes arrive as 227,596 strings from the NGX price lists"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def rebuild(ex):
    mp = os.path.join(OUT, f"market_{ex}.json")
    hp = os.path.join(OUT, f"heatmap_{ex}.json")
    if not os.path.exists(mp):
        print(f"  {ex}: no market file, skipped")
        return
    market = json.load(open(mp, encoding="utf-8"))
    meta = {}
    if os.path.exists(hp):
        try:
            for c in json.load(open(hp, encoding="utf-8")).get("stocks", []):
                if c.get("sym"):
                    meta[c["sym"]] = c
        except Exception:
            pass

    cap = MAX_MOVE.get(ex, 50.0)
    cells, capped, priced = [], 0, 0
    for s in market.get("stocks", []):
        sym = s.get("sym")
        if not sym:
            continue
        price = num(s.get("price"))
        if price is None:
            continue  # a cell with no price is not a cell, it is a gap
        chg = num(s.get("chgPct"))
        # the market build applies the same cap upstream and records why
        suspect = (chg is not None and abs(chg) > cap) or s.get("chgFlag") == "suspect-baseline"
        if suspect:
            capped += 1
            chg = None
        vol = num(s.get("volume")) or 0
        m = meta.get(sym, {})
        code = m.get("code") or s.get("ticker") or sym.split(".")[0]
        cell = {
            "sym": sym,
            "code": code,
            "name": s.get("name"),
            "short": m.get("short") or s.get("ticker"),
            "price": price,
            "chgPct": chg,
            "volume": vol,
            "weight": price * vol,
            "sector": s.get("sector") or m.get("sector"),
            "currency": s.get("currency") or m.get("currency"),
            "logo": m.get("logo"),
        }
        if suspect:
            # keep the gap visible and explainable rather than silently flat
            cell["chgFlag"] = "suspect-baseline"
        cells.append(cell)
        priced += 1

    out = {
        "exchange": ex,
        "count": len(cells),
        "asOf": market.get("asOf"),
        "source": f"market_{ex}.json (history bars) - single source of truth",
        "stocks": cells,
    }
    json.dump(out, open(hp, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False)
    print(f"  {ex}: {priced} cells from market snapshot, {capped} moves past "
          f"+/-{cap:g}% nulled as suspect baselines")


def main():
    print("Rebuilding heatmaps from market snapshots ...")
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        rebuild(ex)


if __name__ == "__main__":
    main()
