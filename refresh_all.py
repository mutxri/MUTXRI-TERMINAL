#!/usr/bin/env python3
"""refresh_all.py - scheduled data refresh for the MUTXRI TERMINAL static site.

Chain (each step safe to re-run):
  1. [optional, daily] history top-up for JSE/EGX from Yahoo (prices source)
  2. market_<EX>.json  <- build_market_snapshots.py (prices/chg/volume)
  3. screener_<EX>.json <- build_screener.py
  3b. heatmap_<EX>.json <- rebuild_heatmaps.py (derived from step 2)
  4. ex_<EX>_summary/indices <- build_ex_summaries.py
  5. fx/bonds/commodities/reg/ratings/tas <- refresh_live_data.py (LIVE backend)
  6. jse_news.json <- news_collect_jse.py (Moneyweb, current)
  7. bot_market_state/bot_signals.json <- market_bot.py (exchange state + news scan)
  8. assemble gh_pages_deploy2
  9. push changed files to the gh-pages branch (bulk_push tree-compare)

usage: python refresh_all.py [--history]     (--history adds step 1)
"""
import subprocess, sys, os, time

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
API = "https://mutxri-terminal.onrender.com"
t0 = time.time()


def run(name, args, env=None, timeout=1800):
    print(f"\n=== {name} ===", flush=True)
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run([PY] + args, capture_output=True, text=True, cwd=BASE, env=e, timeout=timeout)
    tail = (r.stdout or "")[-600:] + (r.stderr or "")[-300:]
    print(tail, flush=True)
    if r.returncode != 0:
        print(f"!!! {name} FAILED rc={r.returncode}", flush=True)
        sys.exit(1)
    return r


steps = 0
if "--history" in sys.argv:
    run("history topup JSE/EGX", ["refresh_history.py", "JSE", "EGX", "--topup", "--workers", "8"], timeout=3600)
    steps += 1
run("market snapshots", ["build_market_snapshots.py"])
run("screener", ["build_screener.py"])
# heatmap_<EX>.json is derived from market_<EX>.json - without this the
# default view silently ages while every price behind it refreshes
run("heatmaps", ["rebuild_heatmaps.py"])
run("exchange summaries/indices", ["build_ex_summaries.py"])
run("live panel data (fx/bonds/commodities/reg/ratings/tas)", ["refresh_live_data.py"], env={"API": API})
run("jse news", ["news_collect_jse.py"])
run("ngx/nse news", ["news_collect_ngx_nse.py"], timeout=300)
run("market bot (state + news signals)", ["market_bot.py", "--quiet"], timeout=900)
run("assemble deploy", ["assemble_deploy.py"])
run("push changed files", ["bulk_push.py"], timeout=3600)

print(f"\nALL DONE in {time.time()-t0:.0f}s")
