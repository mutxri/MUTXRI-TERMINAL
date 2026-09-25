#!/usr/bin/env python3
"""tv_retry_fails.py - retry the TradingView backfill failures with fallbacks.

Parses FAIL lines from a tv_backfill log, and for each failed symbol tries a
fallback TradingView symbol (EGX ISIN "EGS...", NGX ticker without spaces) before
writing the daily + monthly files. Reuses tv_backfill's fetch/write helpers.
"""
import json, os, sys, time
import tv_backfill as tv

LOG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tv_backfill.log"

# parse FAIL lines -> [(ex, code)]
fails = []
for line in open(LOG, encoding="utf-8"):
    line = line.strip()
    if not line.startswith("FAIL "):
        continue
    rest = line[5:].split(" - ")[0]   # "EX:CODE"
    ex, _, code = rest.partition(":")
    code = code.strip()
    if ex and code:
        fails.append((ex, code))

stocks = json.load(open("stocks.json", encoding="utf-8"))["stocks"]
egx = {x.get("ticker"): x for x in stocks.get("EGX", [])}

def try_symbol(ex, code, full_symbol):
    dp, mp = tv.out_paths(ex, code)
    try:
        prev = json.load(open(dp, encoding="utf-8")).get("bars", [])
        if len(prev) >= 1500:
            return ex, code, "skip", "already deep"
    except Exception:
        pass
    try:
        bars, err = tv.fetch_tv(full_symbol)
    except Exception as e:
        return ex, code, "fail", str(e)[:60]
    if err or not bars:
        return ex, code, "fail", (err or "no data")[:60]
    iso_bars, seen = [], set()
    for b in bars:
        iso = tv.to_iso(b["t"])
        if iso in seen:
            continue
        seen.add(iso)
        cb = tv.clean_bar(iso, b["o"], b["h"], b["l"], b["c"], b["v"])
        if cb:
            iso_bars.append(cb)
    iso_bars.sort(key=lambda x: x["t"])
    if len(iso_bars) < 2:
        return ex, code, "fail", f"only {len(iso_bars)} bars"
    try:
        prev = json.load(open(dp, encoding="utf-8")).get("bars", [])
        if len(prev) > len(iso_bars):
            return ex, code, "skip", f"existing {len(prev)} > tv {len(iso_bars)}"
    except Exception:
        pass
    json.dump({"sym": os.path.basename(dp)[:-5], "bars": iso_bars}, open(dp, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"sym": os.path.basename(mp)[:-5], "bars": tv.aggregate_monthly(iso_bars)}, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
    return ex, code, "ok", f"{len(iso_bars)} bars {iso_bars[0]['t']}->{iso_bars[-1]['t']}"

ok = fail = skip = 0
for ex, code in fails:
    variants = []
    if ex == "EGX":
        x = egx.get(code)
        if x and x.get("sym"):
            variants.append("EGX:" + x["sym"].split(".")[0])  # ISIN fallback
    elif ex == "NGX" and " " in code:
        variants.append("NSENG:" + code.replace(" ", ""))
    # primary was already tried and failed; only variants here
    if not variants:
        fail += 1
        print(f"  NOFALLBACK {ex}:{code}", flush=True)
        continue
    got = False
    for v in variants:
        e, c, st, msg = try_symbol(ex, code, v)
        if st == "ok":
            ok += 1
            print(f"  OK {ex}:{code} via {v} -> {msg}", flush=True)
            got = True
            break
    if not got:
        fail += 1
        print(f"  STILLFAIL {ex}:{code}", flush=True)

print(f"\nRETRY DONE: {ok} ok, {fail} fail, {skip} skip")
