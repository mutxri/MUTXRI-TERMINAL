import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import tv_backfill as tv

tv.FORCE = True
stocks = json.load(open("stocks.json", encoding="utf-8"))["stocks"]["NGX"]
codes = [s.get("ticker") for s in stocks if s.get("ticker")]
ok = fail = 0
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(tv.process, "NGX", c): c for c in codes}
    for fut in as_completed(futs):
        r = fut.result()
        if r[2] == "ok":
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {r[0]}:{r[1]} - {r[3]}", flush=True)
print(f"NGX re-fetch: {ok} ok, {fail} fail", flush=True)
