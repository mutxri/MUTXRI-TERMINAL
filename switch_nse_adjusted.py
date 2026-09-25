import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import tv_backfill as tv

# Split-affected NSE tickers where the raw IR feed shows wrong (unadjusted) peaks.
# Ratios from the live check: KQ x8.7 (reverse), KPLC x0.14, EQTY x0.33,
# ABSA x0.49, BRIT x0.56, IMH x0.57, KEGN x0.61, TCL x0.63.
SPLIT = ["KQ", "KPLC", "EQTY", "ABSA", "BRIT", "IMH", "KEGN", "TCL"]

tv.FORCE = True
ok = fail = 0
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(tv.process, "NSE", t): t for t in SPLIT}
    for fut in as_completed(futs):
        r = fut.result()
        if r[2] == "ok":
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {r[0]}:{r[1]} - {r[3]}", flush=True)
print(f"split tickers switched to TV: {ok} ok, {fail} fail", flush=True)

# Verify peak for each
import datetime
def ts(t):
    return datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d") if isinstance(t, (int, float)) else t
for t in SPLIT:
    p = f"static_data/history/NSE_{t}.json"
    b = json.load(open(p, encoding="utf-8"))["bars"]
    peak = max(x["h"] for x in b)
    print(f"  {t}: {len(b)} bars, peak {peak:.1f} on {ts([x['t'] for x in b if x['h']==peak][0])}", flush=True)
