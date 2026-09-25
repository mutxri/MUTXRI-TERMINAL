import json, os
from concurrent.futures import ThreadPoolExecutor, as_completed
import tv_backfill as tv

IR = tv.NSE_IR_COVERED
HIST = "static_data/history"

def ir_info(tkr):
    p = f"{HIST}/NSE_{tkr}.json"
    if not os.path.exists(p):
        return tkr, None, None, None
    b = json.load(open(p, encoding="utf-8"))["bars"]
    peak = max(x["h"] for x in b)
    return tkr, len(b), peak, b[-1]["c"]

def tv_info(tkr):
    bars, err = tv.fetch_tv(f"NSEKE:{tkr}", count=20000)
    if not bars:
        return tkr, 0, None, None, err
    peak = max(x["h"] for x in bars)
    return tkr, len(bars), peak, bars[-1]["c"], None

results = {}
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(tv_info, t): t for t in IR}
    for fut in as_completed(futs):
        t, nd, pk, lastc, err = fut.result()
        results[t] = (nd, pk, lastc, err)

print(f"{'TKR':6} {'IR bars':>8} {'IR peak':>8} {'TV bars':>8} {'TV peak':>8}  verdict")
for t in sorted(IR):
    i_len, i_peak, i_last = ir_info(t)[1:]
    tv_nd, tv_pk, tv_lastc, err = results.get(t, (None, None, None, "?"))
    ir_s = f"{i_len}" if i_len else "-"
    ir_p = f"{i_peak:.1f}" if i_peak is not None else "-"
    tv_s = f"{tv_nd}" if tv_nd else "-"
    tv_p = f"{tv_pk:.1f}" if tv_pk is not None else "-"
    # split-adjusted if recent closes match but historical peak differs a lot
    split = ""
    if tv_pk and i_peak:
        ratio = tv_pk / i_peak
        if ratio > 1.6 or ratio < 0.6:
            split = f"  <-- SPLIT x{ratio:.1f}"
    deeper = "  <-- TV DEEPER" if tv_nd and i_len and tv_nd > i_len else ""
    print(f"{t:6} {ir_s:>8} {ir_p:>8} {tv_s:>8} {tv_p:>8}{split}{deeper}")
