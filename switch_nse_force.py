import json, os
from concurrent.futures import ThreadPoolExecutor, as_completed
import tv_backfill as tv

# Switch split-affected tickers to TradingView's split-adjusted data,
# overriding the "existing deeper" guard (adjusted correctness > raw depth).
SWITCH = ["ABSA", "BRIT", "IMH", "KEGN", "TCL"]

def force_switch(t):
    dp, mp = tv.out_paths("NSE", t)
    bars, err = tv.fetch_tv(tv.tv_symbol("NSE", t))
    if err or not bars:
        return t, "fail", err or "no data"
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
    json.dump({"sym": os.path.basename(dp)[:-5], "bars": iso_bars}, open(dp, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"sym": os.path.basename(mp)[:-5], "bars": tv.aggregate_monthly(iso_bars)}, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
    return t, "ok", f"{len(iso_bars)} bars {iso_bars[0]['t']}->{iso_bars[-1]['t']}"

with ThreadPoolExecutor(max_workers=5) as ex:
    futs = {ex.submit(force_switch, t): t for t in SWITCH}
    for fut in as_completed(futs):
        t, st, msg = fut.result()
        print(f"  {t}: {st} - {msg}", flush=True)

# verify peaks
import datetime
def ts(x):
    return datetime.datetime.fromtimestamp(x, datetime.UTC).strftime("%Y-%m-%d") if isinstance(x, (int, float)) else x
for t in SWITCH:
    b = json.load(open(f"static_data/history/NSE_{t}.json", encoding="utf-8"))["bars"]
    peak = max(x["h"] for x in b)
    pdt = ts([x["t"] for x in b if x["h"] == peak][0])
    print(f"  {t} peak now: {peak:.1f} on {pdt} ({len(b)} bars)", flush=True)
