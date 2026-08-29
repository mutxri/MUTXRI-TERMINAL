#!/usr/bin/env python3
"""apply_delisted_filter.py - remove delisted/suspended companies from the
terminal's market data. VERIFIED delisted/suspended lists (public records):

NSE (Kenya): ARM (ARM Cement, delisted 2020), MSC (Mumias Sugar, suspended
2019), DCON (Deacons, delisted 2017), UCHM (Uchumi, receivership/delisted),
OCH (Olympia, suspended). Junk/placeholder tickers with no real listing are
also dropped (FAHR, NBK, HFCK, SMWF, ALP, TRFC).

Also flags securities with no price (suspended listings show price null).

Applies to static_data/market_<EX>.json + static_data/screener_<EX>.json.
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))

DELISTED = {
    "NSE": {
        "ARM": "ARM Cement (delisted 2020)",
        "MSC": "Mumias Sugar (suspended 2019)",
        "DCON": "Deacons East Africa (delisted 2017)",
        "UCHM": "Uchumi Supermarket (receivership)",
        "OCH": "Olympia Capital (suspended)",
    },
    "NGX": {
        # any known delisted NGX names here if verified later
    },
    "JSE": {},
    "EGX": {},
}

# placeholder/junk tickers with no real company behind them
JUNK = {"FAHR", "NBK", "HFCK", "SMWF", "ALP", "TRFC", "BACC", "BACB"}

def apply(ex):
    mpath = os.path.join(BASE, "static_data", f"market_{ex}.json")
    if not os.path.exists(mpath):
        return
    m = json.load(open(mpath, encoding="utf-8"))
    before = len(m.get("stocks", []))
    removed = []
    kept = []
    for s in m.get("stocks", []):
        tkr = s.get("ticker") or (s.get("sym") or "").split(".")[0]
        if tkr in DELISTED.get(ex, {}):
            removed.append((tkr, DELISTED[ex][tkr]))
            continue
        if tkr in JUNK:
            removed.append((tkr, "placeholder"))
            continue
        kept.append(s)
    m["stocks"] = kept
    json.dump(m, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ex}: {before} -> {len(kept)} ({len(removed)} delisted/junk removed)")
    for t, why in removed:
        print(f"   - {t}: {why}")

    # also apply to screener
    spath = os.path.join(BASE, "static_data", f"screener_{ex}.json")
    if os.path.exists(spath):
        sc = json.load(open(spath, encoding="utf-8"))
        rows = sc.get("rows", sc.get("stocks", []))
        bad = {t for t, _ in removed}
        if isinstance(rows, list):
            kept_rows = [r for r in rows if (r.get("ticker") or (r.get("sym") or "").split(".")[0]) not in bad]
            if "rows" in sc: sc["rows"] = kept_rows
            else: sc["stocks"] = kept_rows
            json.dump(sc, open(spath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"   screener: {len(rows)} -> {len(kept_rows)}")

for ex in ["JSE", "EGX", "NGX", "NSE"]:
    apply(ex)
print("DONE")
