#!/usr/bin/env python3
"""tv_apply_resolved.py - write candle series from a VERIFIED TradingView mapping.

Why this exists: TradingView's symbol-search endpoint is not deterministic. Two
runs of tv_fill_missing.py over the same 72 files resolved 10 symbols and then 3,
because the search intermittently returns nothing. Resolution is therefore done
ONCE, reviewed, and cached - the fetch+write step then repeats deterministically
from the cache.

The cache (static_data/_tv_resolved.json) maps a history file base -> TradingView
symbol, and each entry records the ratio and the description it was accepted on,
so the identity decision stays auditable. Every entry here was reviewed by hand
against the terminal's own listed name before being added.

Writes <base>.json (daily) + <base>.max.json (monthly) - the exact names the
chart panel requests - and never shrinks an existing series.

Usage: python3 tv_apply_resolved.py [--apply] [--only SYM,SYM]
"""
import importlib.util, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
CACHE = os.path.join(BASE, "static_data", "_tv_resolved.json")
APPLY = "--apply" in sys.argv
ONLY = None
if "--only" in sys.argv:
    ONLY = {s.strip().upper() for s in sys.argv[sys.argv.index("--only") + 1].split(",")}

_spec = importlib.util.spec_from_file_location("tv", os.path.join(BASE, "tv_backfill.py"))
tv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tv)


def main():
    mapping = json.load(open(CACHE, encoding="utf-8"))
    ok = fail = skip = 0
    for base in sorted(mapping):
        ent = mapping[base]
        if ONLY and base.upper() not in ONLY:
            continue
        full = ent["tv"] if isinstance(ent, dict) else ent
        desc = ent.get("desc", "") if isinstance(ent, dict) else ""
        ratio = ent.get("ratio", 0) if isinstance(ent, dict) else 0
        dp = os.path.join(HIST, base + ".json")
        mp = os.path.join(HIST, base + ".max.json")
        try:
            prev = json.load(open(dp, encoding="utf-8")).get("bars") or []
        except Exception:
            prev = []
        if prev:
            skip += 1
            print("  SKIP   %-18s already has %d bars" % (base, len(prev)))
            continue
        try:
            raw, err = tv.fetch_tv(full, timeout=30)
        except Exception as e:
            fail += 1
            print("  FAIL   %-18s %s -> %s" % (base, full, str(e)[:44]))
            continue
        if err or not raw:
            fail += 1
            print("  NODATA %-18s %s (%s)" % (base, full, (err or "empty")[:40]))
            continue
        seen, iso = set(), []
        for b in raw:
            d = tv.to_iso(b["t"])
            if d in seen:
                continue
            seen.add(d)
            cb = tv.clean_bar(d, b["o"], b["h"], b["l"], b["c"], b["v"])
            if cb:
                iso.append(cb)
        iso.sort(key=lambda x: x["t"])
        if len(iso) < 2:
            fail += 1
            print("  THIN   %-18s %s only %d bars" % (base, full, len(iso)))
            continue
        print("  OK     %-18s %-18s %5d bars  %s -> %s  ratio=%.2f [%s]"
              % (base, full, len(iso), iso[0]["t"], iso[-1]["t"], ratio, desc[:26]))
        ok += 1
        if APPLY:
            json.dump({"sym": base, "bars": iso}, open(dp, "w", encoding="utf-8"),
                      ensure_ascii=False)
            json.dump({"sym": base, "bars": tv.aggregate_monthly(iso)},
                      open(mp, "w", encoding="utf-8"), ensure_ascii=False)

    print()
    print("written: %d   skipped: %d   failed: %d" % (ok, skip, fail))
    print("DRY RUN - nothing written" if not APPLY else "APPLIED")


if __name__ == "__main__":
    main()
