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
# Runs AFTER the market/screener builds (they read stocks.json raw and re-add
# every legacy and junk listing) but BEFORE the heatmaps, which derive from the
# filtered market file. Without this step the delisted and placeholder rows come
# back on the next refresh and the board looks dirty again.
run("delisted/junk filter", ["apply_delisted_filter.py"])
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
# Rows the filer did not print but which are pure arithmetic on the rows they
# did (Gross Profit = Revenue - Cost of Sales, and so on) are computed here.
# Runs BEFORE the validator so derived rows are checked the same way as filed
# ones, and after the collectors so it works on fresh statements.
# Balance-sheet rows the shipped files lack are merged from the Yahoo source
# here. This must run BEFORE the derivations: it supplies Current Assets and
# Current Liabilities, which were 0% and 10% filled because two row names in
# the builder's map did not match the source ("Total Current Liabilities" vs
# "Current Liabilities"), so both came back empty and were dropped.
run_soft("merge yahoo balance", ["merge_yahoo_balance.py"])
# Fill individual BLANK CELLS in a row that already carries figures (the
# 5th period in most JSE files). merge_yahoo_balance only fills a wholly
# absent row, so it cannot touch these. Runs BEFORE the derivations so a
# filled input is available to them.
run_soft("merge yahoo gaps", ["merge_yahoo_gaps.py"])
# The same merge for the INCOME statement, and the same two defects: the builder
# only writes a statement file it does not already find, so a name collected once from
# a thin provider never gains the Cost of Sales, Gross Profit or Operating Expenses
# rows the same security carries in yahoo_financials.json; and the shipped files are
# keyed on the bare board symbol (SHP) while that source keys on the suffixed form
# (SHP.JO), so a stem join found a source record for 365 of 1457 files and missed the
# rest. The merge resolves the stem, refuses to pair a security with a different
# issuer on another board (BAT Kenya vs BAT.JO, which is Brait), only ADDS a row that
# is absent or wholly null, and guards each fill on the SOURCE own arithmetic. Runs
# before the derivations so a filled input is available to them.
run_soft("merge yahoo income", ["merge_yahoo_income.py"])
# The dataset mixes two sign conventions for the cost lines: measured over 3,331
# complete period triples, "Revenue - Cost of Sales = Gross Profit" holds with the
# cost POSITIVE 3,053 times and only with it NEGATIVE 205. A file on the negative
# convention prints "Cost of Sales -640.2M" against a positive figure on every other
# board and fails the identity the terminal runs. Each row is negated only when its
# own printed identity breaks as stored and ties at every complete period after the
# flip, so a genuine tax credit is left alone. Runs BEFORE the derivations, because
# they subtract these rows and would otherwise compute on an inverted input.
run_soft("normalize cost signs", ["normalize_cost_signs.py"])
run_soft("derive statement rows", ["derive_statement_rows.py"])
# Operating Expenses and Operating Profit (EBIT) are filled from the other one plus
# Gross Profit, only where that identity reproduces every period of the SAME file with
# zero contradictions. Four other candidate identities (net finance costs, profit before
# tax, net profit, income tax) contradict far more often than they agree and are NOT
# used. A negative operating expense is refused as impossible.
run_soft("derive opex and ebit", ["derive_opex_ebit.py"])
# Ratios (ROE, ROA, the margins, debt to equity) are arithmetic on the same
# figures. Must run AFTER the row derivation above, because ROE consumes the
# net profit that step may have just filled in.
run_soft("derive ratios", ["derive_ratios.py"])
run("validate financials", ["validate_financials.py", "--apply"])
# RE-DERIVE after validation. The validator WITHHOLDS an impossible figure (for
# example a net profit larger than the pre-tax profit it came from), which can
# blank a ratio's INPUT while the ratio derived from it stays on screen. Running
# the derivation a second time, after the validator, recomputes each ratio from
# the figures the panel actually prints and leaves a dash where its input is
# gone. Without this the income tab can show a Net Margin with no Net Profit.
run_soft("re-derive ratios after validation", ["derive_ratios.py"])
run("assemble deploy", ["assemble_deploy.py"])
# Single-commit push. bulk_push writes ONE COMMIT PER FILE, so a refresh that
# touches hundreds of statements fires hundreds of Pages builds, they cancel
# each other, and the live site silently stays on an old build. This is also
# why a 578-file change once ran for 20 minutes and never finished.
run("push changed files", ["push_single_commit.py", "Scheduled refresh"], timeout=3600)

print(f"\nALL DONE in {time.time()-t0:.0f}s")
