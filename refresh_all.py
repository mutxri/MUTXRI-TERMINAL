#!/usr/bin/env python3
"""refresh_all.py - scheduled data refresh for the MUTXRI TERMINAL static site.

Chain (each step safe to re-run):
  1. end-of-day prices <- mutxri_ai.py eod run (daily with --history; otherwise
     only when a published session is missing and untried, to catch up a
     skipped daily task). Non-fatal, and verified per security.
  2. market_<EX>.json  <- build_market_snapshots.py (prices/chg/volume)
  3. screener_<EX>.json <- build_screener.py
  3b. heatmap_<EX>.json <- rebuild_heatmaps.py (derived from step 2)
  4. ex_<EX>_summary/indices <- build_ex_summaries.py
  5. fx/bonds/commodities/reg/ratings/tas <- refresh_live_data.py (LIVE backend)
  6. jse_news.json <- news_collect_jse.py (Moneyweb, current)
  7. bot_market_state/bot_signals/bot_flags.json <- market_bot.py
     (exchange state, news scan, statement-flag digest for the BOT panel)
  8. data health check <- mutxri_ai.py doctor (reported, never fatal)
  9. assemble gh_pages_deploy2
 10. push changed files to the gh-pages branch (bulk_push tree-compare)

usage: python refresh_all.py [--history]     (--history forces step 1)
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


def run_soft(name, args, timeout=1800):
    """run(), except a failure is reported and the refresh carries on.

    End-of-day prices must not share run()'s all-or-nothing exit: one collector
    timing out used to abort the chain before the snapshots were rebuilt and
    before anything was deployed, so every exchange lost its close for the day.
    """
    print(f"\n=== {name} ===", flush=True)
    try:
        r = subprocess.run([PY] + args, capture_output=True, text=True, cwd=BASE,
                           timeout=timeout)
        print((r.stdout or "")[-3000:] + (r.stderr or "")[-400:], flush=True)
        return r.returncode
    except Exception as e:
        print(f"!!! {name} did not complete: {e}", flush=True)
        return None


steps = 0
if "--history" in sys.argv:
    # The daily end-of-day update, via the bot. It runs each exchange's own
    # collector in isolation - JSE/EGX Yahoo top-up, NGX official price lists,
    # NSE official board plus a merge-safe IR backfill - so one failing never
    # costs the other three their close. Then it rebuilds the snapshots, checks
    # per security that the expected session landed, re-fetches daily traders
    # that missed it, and writes static_data/eod_status.json.
    run_soft("end-of-day prices (all exchanges)", ["mutxri_ai.py", "eod", "run"], timeout=5400)
    steps += 1
else:
    # Catch-up. The daily task is skipped whenever the machine is on battery or
    # asleep at 18:30 and Windows does not re-run it, so the closes for that day
    # never arrived. Any later refresh that finds a published session missing -
    # and not already attempted - runs the end-of-day update itself.
    try:
        _due = subprocess.run([PY, "mutxri_ai.py", "eod", "due"], capture_output=True,
                              text=True, cwd=BASE, timeout=300)
        if _due.returncode == 0:
            print("\n" + (_due.stdout or "").strip(), flush=True)
            run_soft("end-of-day catch-up (daily run was missed)",
                     ["mutxri_ai.py", "eod", "run"], timeout=5400)
            steps += 1
    except Exception as _e:
        print(f"eod due-check skipped: {_e}", flush=True)
run("market snapshots", ["build_market_snapshots.py"])
# One volume per security, everywhere. The snapshot builder takes volume from
# the latest bar and dates it; the listing that the watchlist and market rail
# read carried an undated scrape that disagreed on 298 of 324 JSE securities.
# This copies the dated figure across before anything is assembled.
run("volume sync", ["sync_volumes.py"])
run("screener", ["build_screener.py"])
# heatmap_<EX>.json is derived from market_<EX>.json - without this the
# default view silently ages while every price behind it refreshes
run("heatmaps", ["rebuild_heatmaps.py"])
run("exchange summaries/indices", ["build_ex_summaries.py"])
run("live panel data (fx/bonds/commodities/reg/ratings/tas)", ["refresh_live_data.py"], env={"API": API})
run("jse news", ["news_collect_jse.py"])
run("ngx/nse news", ["news_collect_ngx_nse.py"], timeout=300)
run("market bot (state + news signals)", ["market_bot.py", "--quiet"], timeout=900)

# Data health is reported, never fatal: a stale feed should surface in the log,
# not abort a refresh that has already collected everything else successfully.
print("\n=== data health ===", flush=True)
try:
    _h = subprocess.run([PY, "mutxri_ai.py", "doctor"], capture_output=True,
                        text=True, cwd=BASE, timeout=300)
    print((_h.stdout or "")[-2200:], flush=True)
except Exception as _e:
    print("doctor skipped: %s" % _e, flush=True)
# Financial statements are regenerated from the raw parser output by the
# collectors, and that output still contains mis-parsed figures - gross profit
# above revenue, net profit above pre-tax. Re-apply the accounting checks on
# every run, immediately before assembling, or the corrupted figures go back
# out with the next refresh.
run("validate financials", ["validate_financials.py", "--apply"])
run("assemble deploy", ["assemble_deploy.py"])
run("push changed files", ["bulk_push.py"], timeout=3600)

print(f"\nALL DONE in {time.time()-t0:.0f}s")
