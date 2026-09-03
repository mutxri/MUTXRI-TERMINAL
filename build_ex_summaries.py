#!/usr/bin/env python3
"""build_ex_summaries.py - build per-exchange market summaries for the CORP panel.

For each exchange (JSE/EGX/NGX/NSE):
  - summary: top 5 gainers, top 5 losers, top 5 movers (by volume)
    computed from market_<EX>.json (real data, no fabrication)
  - indices: the exchange's own indices from the listing data where
    available; otherwise honest empty list

Writes static_data/ex_<EX>_summary.json + static_data/ex_<EX>_indices.json
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))

def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None

EX_INDICES = {
    "JSE": [{"ticker": "^JSE", "name": "FTSE/JSE All Share", "price": None}],
    "EGX": [{"ticker": "^EGX30", "name": "EGX 30", "price": None},
            {"ticker": "^EGX70", "name": "EGX 70 EWI", "price": None},
            {"ticker": "^EGX100", "name": "EGX 100 EWI", "price": None}],
    "NGX": [{"ticker": "^NGXASI", "name": "NGX All-Share Index", "price": None}],
    "NSE": [{"ticker": "^NASI", "name": "NSE All-Share", "price": None},
            {"ticker": "^N20I", "name": "NSE 20-Share", "price": None},
            {"ticker": "^N25I", "name": "NSE 25-Share", "price": None}],
}

def build(ex):
    path = os.path.join(BASE, "static_data", f"market_{ex}.json")
    if not os.path.exists(path):
        return
    m = json.load(open(path, encoding="utf-8"))
    stocks = m.get("stocks", [])

    # gainers: highest chgPct among stocks with a real price + change
    valid = [s for s in stocks if s.get("price") is not None and s.get("chgPct") is not None]
    gainers = sorted(valid, key=lambda s: s["chgPct"], reverse=True)[:5]
    losers = sorted(valid, key=lambda s: s["chgPct"])[:5]

    # movers: highest volume (excluding non-common instruments)
    common = [s for s in stocks if s.get("price") is not None and s.get("volume")]
    movers = sorted(common, key=lambda s: s.get("volume") or 0, reverse=True)[:5]

    def mini(s):
        return {
            "ticker": s.get("ticker") or (s.get("sym") or "").split(".")[0],
            "price": s.get("price"),
            "changePct": (round(s["chgPct"], 2) if s.get("chgPct") is not None else None),
            "volume": s.get("volume"),
        }

    summary = {
        "exchange": ex,
        "asOf": m.get("asOf", ""),
        "topGainers": [mini(s) for s in gainers],
        "topLosers": [mini(s) for s in losers],
        "topMovers": [mini(s) for s in movers],
    }
    out = os.path.join(BASE, "static_data", f"ex_{ex}_summary.json")
    json.dump(summary, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # indices: NSE has real values from nse_indices.json; others show names only
    idx = EX_INDICES.get(ex, [])
    if ex == "NSE":
        # merge real NSE index values (NASI/N20I/N25I) so they never regress to empty
        try:
            real = json.load(open(os.path.join(BASE, "static_data", "nse_indices.json"), encoding="utf-8"))
            rmap = {r.get("ticker", "").lower(): r for r in real}
            for it in idx:
                for rt, rv in rmap.items():
                    if ("nasi" in rt and "all-share" in it["name"].lower()) or \
                       ("n20i" in rt and "20-share" in it["name"].lower()) or \
                       ("n25i" in rt and "25-share" in it["name"].lower()):
                        it["price"] = _num(rv.get("price"))
                        it["changePct"] = _num(rv.get("changePct"))
                        it["change"] = rv.get("change")
        except Exception:
            pass
    json.dump(idx, open(os.path.join(BASE, "static_data", f"ex_{ex}_indices.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ex}: {len(gainers)} gainers, {len(losers)} losers, {len(movers)} movers, {len(idx)} indices")

# JSE: FTSE/JSE All Share has a real free quote (^JSE on Yahoo) - fill it in
try:
    import yfinance as yf
    h = yf.Ticker("^JSE").history(period="5d")
    if len(h) >= 2:
        last = float(h["Close"].iloc[-1]); prev = float(h["Close"].iloc[-2])
        for it in EX_INDICES.get("JSE", []):
            it["price"] = last
            it["changePct"] = round((last - prev) / prev * 100.0, 2)
            it["change"] = ("%+.2f (%+.2f%%)" % (last - prev, (last - prev) / prev * 100.0))
        json.dump(EX_INDICES["JSE"], open(os.path.join(BASE, "static_data", "ex_JSE_indices.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("JSE: ^JSE real value", round(last, 2))
except Exception as e:
    print("JSE ^JSE fetch failed (honest None):", str(e)[:60])

for ex in ["JSE", "EGX", "NGX", "NSE"]:
    build(ex)
print("DONE")
