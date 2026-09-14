#!/usr/bin/env python3
"""bot/eod.py - the daily end-of-day price update, and proof that it landed.

The terminal already has a collector for every exchange's closing prices:

  NSE   the exchange's own board (fetch_nse_official + append_nse_bars), with
        the NSE IR feed as a merge-safe backfill for any missed sessions
  NGX   the NGX's official daily price lists (fetch_ngx_history)
  JSE   Yahoo daily bars (refresh_history --topup)
  EGX   Yahoo daily bars (refresh_history --topup)

What it did not have was a daily job that reliably ran them and then checked the
result. The scheduled run was one step in a chain where any failure - a news feed
timing out - aborted everything after it, and the Windows task skips silently on
battery power. So the question "are today's closes in?" had no answer short of
opening files. This module is that answer:

  run    each exchange's collector in isolation (one failing never blocks the
         others), then rebuild the market snapshots, then verify, then retry
         the securities that should have printed and did not
  check  per exchange: which session should be on disk by now, which session
         actually is, and for every security whether its close is current,
         lagging, illiquid, dormant or missing
  due    whether an expected session has not landed yet - so any refresh that
         happens to run after the close can catch up a missed daily run

A security that did not print is not automatically a failure. NGX's FGN savings
bonds trade a few times a year, and Yahoo omits days an illiquid JSE name did not
trade. "Lagging" is reserved for a security that printed on most recent sessions
and is missing the latest - that is a fetch miss, and only those are retried.

Bars are never rewritten here. An OHLC bar that contradicts itself is flagged,
not repaired: the NSE board itself published Safaricom's 14 Sep session with an
open of 37.20 above a high of 36.65, and the honest record of that is the
exchange's own print with a flag beside it.

Market holidays are not modelled. When no security at all has the expected
session, the report says it was either not fetched or a holiday, rather than
guessing which.
"""
import concurrent.futures as cf
import datetime as dt
import glob
import importlib.util
import json
import os
import subprocess
import sys
import time

from . import universe as U

BASE = U.BASE
SD = U.SD
HIST = os.path.join(SD, "history")
STATUS_FILE = os.path.join(SD, "eod_status.json")
LEDGER_FILE = os.path.join(SD, "eod_ledger.jsonl")
PY = sys.executable

# Trading week (Python weekday: Mon=0 .. Sun=6), and the UTC hour after which the
# session's closing data can be expected from the source we actually use. These
# are publication times, not closing bells: NGX's price list and Yahoo's JSE bars
# arrive well after the market shuts.
CALENDAR = {
    "NSE": {"days": (0, 1, 2, 3, 4), "publishUtc": 13.0},   # closes 15:00 EAT
    "NGX": {"days": (0, 1, 2, 3, 4), "publishUtc": 17.0},   # closes 14:30 WAT
    "JSE": {"days": (0, 1, 2, 3, 4), "publishUtc": 17.5},   # closes 17:00 SAST
    "EGX": {"days": (6, 0, 1, 2, 3), "publishUtc": 15.0},   # Sun-Thu, 14:30 local
}

PATTERNS = {
    "NSE": ("NSE_*.json", "NSE_", ""),
    "NGX": ("NGX_*.json", "NGX_", ""),
    "JSE": ("*.JO.json", "", ""),
    "EGX": ("*.CA.json", "", ""),
}

ACTIVE_DAYS = 30          # a security with no bar for longer is dormant, not late
QUORUM = 0.30             # share of active securities that defines a session
DAILY_TRADER_HITS = 6     # printed on >= 6 of the last 10 sessions = trades daily
TAIL = 16                 # bars kept in memory per security for the checks


# ------------------------------------------------------------------ calendar
def bar_day(t):
    """A bar's session date. Yahoo stores epoch seconds, the exchanges ISO."""
    if isinstance(t, (int, float)):
        return dt.datetime.fromtimestamp(int(t), dt.timezone.utc).date()
    try:
        return dt.date.fromisoformat(str(t)[:10])
    except (TypeError, ValueError):
        return None


def is_session(ex, d):
    return d.weekday() in CALENDAR[ex]["days"]


def previous_session(ex, d):
    d = d - dt.timedelta(days=1)
    while not is_session(ex, d):
        d -= dt.timedelta(days=1)
    return d


def sessions_ending(ex, end, n):
    """The n trading dates up to and including `end`."""
    out, d = [], end
    while len(out) < n:
        if is_session(ex, d):
            out.append(d)
        d -= dt.timedelta(days=1)
    return out


def sessions_between(ex, a, b):
    """Trading sessions after `a` up to and including `b`."""
    if b <= a:
        return 0
    n, d = 0, a + dt.timedelta(days=1)
    while d <= b:
        n += is_session(ex, d)
        d += dt.timedelta(days=1)
    return n


def expected_session(ex, now=None):
    """The latest session whose closing data should be published by `now`."""
    now = now or dt.datetime.now(dt.timezone.utc)
    hour = now.hour + now.minute / 60.0
    d = now.date()
    for _ in range(15):
        if is_session(ex, d) and (d < now.date() or hour >= CALENDAR[ex]["publishUtc"]):
            return d
        d -= dt.timedelta(days=1)
    return None


# ------------------------------------------------------------------- loading
def load_exchange(ex):
    pattern, prefix, _ = PATTERNS[ex]
    out = []
    for path in glob.glob(os.path.join(HIST, pattern)):
        name = os.path.basename(path)
        if name.endswith(".max.json"):
            continue
        sid = name[len(prefix):-len(".json")]
        try:
            with open(path, encoding="utf-8") as f:
                bars = json.load(f).get("bars") or []
        except Exception:
            bars = []
        bars = [b for b in bars if b.get("t") is not None]
        tail = bars[-TAIL:]
        out.append({"id": sid, "bars": tail, "count": len(bars),
                    "last": bar_day(tail[-1]["t"]) if tail else None})
    return out


def bar_issues(ex, bars):
    """What is wrong with the newest bar, as published. Nothing is repaired."""
    if not bars:
        return []
    last = bars[-1]
    o, h, l, c = last.get("o"), last.get("h"), last.get("l"), last.get("c")
    issues = []
    if c is None or c <= 0:
        issues.append("no_positive_close")
        return issues
    if None not in (o, h, l):
        # 0.05% slack absorbs Yahoo's float noise (303.1799926 vs 303.18)
        tol = abs(c) * 0.0005
        if h + tol < l or h + tol < max(o, c) or l - tol > min(o, c):
            issues.append("ohlc_inconsistent")
    if len(bars) > 1:
        prev = bars[-2]
        d1, d0 = bar_day(last["t"]), bar_day(prev["t"])
        if d1 and d0 and d1 <= d0:
            issues.append("dates_not_increasing")
        elif d1 and d0 and prev.get("c") and sessions_between(ex, d0, d1) <= 1:
            move = abs(c / prev["c"] - 1) * 100
            if move > U.MAX_MOVE.get(ex, 50.0):
                issues.append("implausible_move")
    return issues


def snapshot_as_of(ex):
    p = os.path.join(SD, "market_%s.json" % ex)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("asOf")
    except Exception:
        return None


# --------------------------------------------------------------------- check
def check_exchange(ex, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date()
    secs = load_exchange(ex)
    expected = expected_session(ex, now)

    usable = [s for s in secs if s["last"] and s["last"] <= today]
    active = [s for s in usable if (today - s["last"]).days <= ACTIVE_DAYS]
    observed = None
    if active:
        need = max(1, int(QUORUM * len(active)))
        for d in sorted({s["last"] for s in active}, reverse=True):
            if sum(1 for s in active if s["last"] >= d) >= need:
                observed = d
                break

    window = set()
    if observed:
        window = set(sessions_ending(ex, previous_session(ex, observed), 10))

    counts = dict.fromkeys(("current", "lagging", "illiquid", "dormant", "nodata",
                            "future"), 0)
    lagging, future, integrity = [], [], {}
    examples = []
    for s in secs:
        last = s["last"]
        if not last:
            cls = "nodata"
        elif last > today:
            cls = "future"
            future.append(s["id"])
        elif observed and last >= observed:
            cls = "current"
        elif (today - last).days > ACTIVE_DAYS:
            cls = "dormant"
        else:
            printed = {bar_day(b["t"]) for b in s["bars"]}
            cls = "lagging" if len(window & printed) >= DAILY_TRADER_HITS else "illiquid"
            if cls == "lagging":
                lagging.append(s["id"])
        counts[cls] += 1
        if cls in ("current", "lagging", "illiquid"):
            for issue in bar_issues(ex, s["bars"]):
                integrity[issue] = integrity.get(issue, 0) + 1
                if len(examples) < 5:
                    b = s["bars"][-1]
                    examples.append({"id": s["id"], "issue": issue,
                                     "session": str(bar_day(b["t"])),
                                     "o": b.get("o"), "h": b.get("h"),
                                     "l": b.get("l"), "c": b.get("c")})

    if not observed:
        status, behind = "empty", None
    elif expected and observed < expected:
        status, behind = "behind", sessions_between(ex, observed, expected)
    else:
        status, behind = "current", 0

    note = None
    if status == "behind":
        note = ("no security has the %s session yet - either it has not been "
                "fetched or it was a market holiday (holidays are not modelled)"
                % expected)
    in_play = counts["current"] + counts["lagging"] + counts["illiquid"]
    snap = snapshot_as_of(ex)
    return {
        "exchange": ex,
        "expectedSession": str(expected) if expected else None,
        "observedSession": str(observed) if observed else None,
        "status": status,
        "sessionsBehind": behind,
        "securities": len(secs),
        "counts": counts,
        # Coverage is measured against securities that are actually trading;
        # dormant listings and names no source carries would make any board look
        # broken, and are reported on their own lines instead.
        "currentPct": round(100.0 * counts["current"] / in_play, 1) if in_play else None,
        "lagging": sorted(lagging),
        "future": sorted(future),
        "integrity": integrity,
        "integrityExamples": examples,
        "snapshotAsOf": snap,
        "snapshotAgrees": (snap is None or observed is None or str(snap)[:10] >= str(observed)),
        "note": note,
    }


def check(now=None, write=True):
    now = now or dt.datetime.now(dt.timezone.utc)
    report = {"checkedAt": now.isoformat(timespec="seconds"),
              "exchanges": {ex: check_exchange(ex, now) for ex in U.EXCHANGES}}
    report["allCurrent"] = all(r["status"] == "current"
                               for r in report["exchanges"].values())
    if write:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    return report


def _collection_runs():
    """(ranAt, exchanges actually collected) for every logged run.

    Only a run that fetched an exchange counts as an attempt at its session. A
    verify-only run, or one limited to NSE, must not persuade the next refresh
    that JSE's close was already tried and suppress the catch-up.
    """
    out = []
    try:
        with open(LEDGER_FILE, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    row = json.loads(ln)
                    out.append((dt.datetime.fromisoformat(row["ranAt"]),
                                set(row.get("collected") or [])))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def due(now=None):
    """(True, reasons) when a published session is missing from disk AND no EOD
    run has attempted it since it was published.

    The second condition matters. A session can be legitimately absent - a
    public holiday, or Yahoo still catching up - and without it every
    three-hourly refresh overnight would relaunch the full half-hour collection
    for a close that is not coming.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    rep = check(now, write=False)
    runs = _collection_runs()
    reasons = []
    for ex, r in rep["exchanges"].items():
        if r["status"] == "current" or not r["expectedSession"]:
            continue
        exp = dt.date.fromisoformat(r["expectedSession"])
        published = (dt.datetime(exp.year, exp.month, exp.day, tzinfo=dt.timezone.utc)
                     + dt.timedelta(hours=CALENDAR[ex]["publishUtc"]))
        tried = any(ran >= published and ex in collected for ran, collected in runs)
        if not tried:
            reasons.append("%s: expected %s, have %s" %
                           (ex, r["expectedSession"], r["observedSession"]))
    return bool(reasons), reasons


def last_status():
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ----------------------------------------------------------------------- run
def _step(name, args, timeout, log):
    """One collector, run to completion in its own process, retried once."""
    for attempt in (1, 2):
        t0 = time.time()
        stdout = stderr = ""
        try:
            r = subprocess.run([PY] + args, cwd=BASE, capture_output=True, text=True,
                               timeout=timeout)
            rc, stdout, stderr = r.returncode, (r.stdout or ""), (r.stderr or "")
        except subprocess.TimeoutExpired as e:
            rc = "timeout"
            stdout = ((e.stdout or b"").decode("utf-8", "replace")
                      if isinstance(e.stdout, bytes) else (e.stdout or ""))
        except Exception as e:
            rc, stderr = "error", "%s: %s" % (type(e).__name__, e)
        # A step that succeeded reports its own conclusion from stdout. Merging
        # stderr after it made the Yahoo top-up "report" a DeprecationWarning
        # instead of what it wrote. A failing step reports stderr, where the
        # traceback is.
        src = stdout if (rc == 0 and stdout.strip()) else (stderr if stderr.strip() else stdout)
        res = {"step": name, "rc": rc, "attempt": attempt,
               "seconds": round(time.time() - t0, 1),
               "tail": src.strip().splitlines()[-3:] if src.strip() else []}
        if rc == 0:
            log(res)
            return res
        if attempt == 1:
            time.sleep(5)
    log(res)
    return res


def _nse_board_closed():
    """Read-only look at the NSE board. Recording the board mid-session would
    write an intraday price into the archive as that day's close."""
    try:
        spec = importlib.util.spec_from_file_location(
            "_fno", os.path.join(BASE, "fetch_nse_official.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _snap, meta = m.fetch_snapshot()
        return str(meta.get("market_status", "")).lower() == "closed", meta
    except Exception as e:
        return False, {"error": "%s: %s" % (type(e).__name__, str(e)[:80])}


def _collect(exchanges, log):
    groups = []
    if "NSE" in exchanges:
        def nse():
            out = [_step("NSE IR feed backfill (merges)", ["fetch_nse_history_fast.py", "2"],
                         900, log)]
            closed, meta = _nse_board_closed()
            if closed:
                out.append(_step("NSE official board", ["fetch_nse_official.py"], 180, log))
                if out[-1]["rc"] == 0:
                    out.append(_step("NSE board bar -> archive", ["append_nse_bars.py"],
                                     180, log))
            else:
                res = {"step": "NSE official board", "rc": "skipped", "attempt": 0,
                       "seconds": 0, "tail": ["board not closed (%s) - no intraday price "
                                              "recorded as a close" %
                                              (meta.get("market_status") or meta.get("error"))]}
                log(res)
                out.append(res)
            return out
        groups.append(nse)
    if "NGX" in exchanges:
        groups.append(lambda: [_step("NGX official price lists",
                                     ["fetch_ngx_history.py", "10"], 1800, log)])
    yahoo = [ex for ex in ("JSE", "EGX") if ex in exchanges]
    if yahoo:
        groups.append(lambda: [_step("%s Yahoo top-up" % "/".join(yahoo),
                                     ["refresh_history.py"] + yahoo +
                                     ["--topup", "--workers", "8"], 3600, log)])
    # Different sources writing different files, so they run side by side; the
    # Yahoo top-up dominates the wall clock either way.
    steps = []
    with cf.ThreadPoolExecutor(max_workers=len(groups) or 1) as pool:
        for got in pool.map(lambda g: g(), groups):
            steps.extend(got)
    return steps


def _retry_yahoo(ids, log):
    """Re-fetch just the securities that trade daily and missed the session."""
    if not ids:
        return None
    spec = importlib.util.spec_from_file_location("_rh", os.path.join(BASE, "refresh_history.py"))
    rh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rh)
    rh.TOPUP = True
    meta = {}
    for ex in ("JSE", "EGX"):
        try:
            for s in rh.load_listing(ex):
                sym = s.get("sym") or s.get("ticker")
                if sym:
                    meta[sym] = (s.get("name", ""), s.get("currency", ""))
        except Exception:
            pass
    jobs = [(sid, meta.get(sid, ("", ""))[0], meta.get(sid, ("", ""))[1], False) for sid in ids]
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(rh.do_symbol, jobs))
    res = {"step": "retry %d lagging JSE/EGX securities" % len(ids), "rc": 0, "attempt": 1,
           "seconds": round(time.time() - t0, 1),
           "tail": ["daily %d written, %d kept, %d no-data" %
                    (rh.stats["daily"], rh.stats["kept"], rh.stats["nodata"])]}
    log(res)
    return res


def run(exchanges=None, collect=True, retry=True, verbose=True):
    exchanges = [e.upper() for e in (exchanges or U.EXCHANGES)]
    started = dt.datetime.now(dt.timezone.utc)
    steps = []

    def log(res):
        if verbose:
            mark = "ok  " if res["rc"] == 0 else ("skip" if res["rc"] == "skipped" else "FAIL")
            print("  %s %-38s %6.1fs%s" % (mark, res["step"][:38], res["seconds"],
                                          ("  " + res["tail"][-1][:70]) if res["tail"] else ""),
                  flush=True)

    if collect:
        if verbose:
            print("collecting end-of-day prices for %s ..." % ", ".join(exchanges), flush=True)
        steps += _collect(exchanges, log)

    steps.append(_step("rebuild market snapshots", ["build_market_snapshots.py"], 900, log))
    report = check(write=False)

    if retry:
        lagging = [sid for ex in ("JSE", "EGX") if ex in exchanges
                   for sid in report["exchanges"][ex]["lagging"]]
        if lagging:
            # A crash here must not stop the status and ledger being written:
            # without the ledger line every later refresh would decide the
            # session was never attempted and relaunch the whole collection.
            try:
                retry_step = _retry_yahoo(lagging, log)
            except Exception as e:
                retry_step = {"step": "retry %d lagging JSE/EGX securities" % len(lagging),
                              "rc": "error", "attempt": 1, "seconds": 0,
                              "tail": ["%s: %s" % (type(e).__name__, str(e)[:100])]}
                log(retry_step)
            steps.append(retry_step)
            steps.append(_step("rebuild market snapshots", ["build_market_snapshots.py"],
                               900, log))
            report = check(write=False)
            # "81 written" only says files were rewritten. Whether the missing
            # session actually arrived is measured here: on 14 Sep all 81
            # lagging JSE/EGX names were still lagging after their retry,
            # because Yahoo had not yet published those sessions - a result
            # the step's own count would have passed off as a fix.
            still = {sid for ex in ("JSE", "EGX") if ex in exchanges
                     for sid in report["exchanges"][ex]["lagging"]}
            recovered = [sid for sid in lagging if sid not in still]
            retry_step["outcome"] = {"retried": len(lagging), "recovered": len(recovered),
                                     "stillLagging": len(lagging) - len(recovered)}
            if verbose:
                print("  retry recovered %d of %d; %d still lack the session at the source"
                      % (len(recovered), len(lagging), len(lagging) - len(recovered)),
                      flush=True)

    steps = [s for s in steps if s]
    # An exchange counts as collected only when one of its own COLLECTOR steps
    # succeeded. A run where the Yahoo top-up failed outright has not attempted
    # JSE's session in any useful sense, and recording it as tried would stop
    # every later refresh that night from catching up. The retry and rebuild
    # steps are excluded: "retry 35 lagging JSE/EGX securities" names both
    # exchanges and would otherwise pass off a failed top-up as a collection.
    collector_ok = [st for st in steps if st.get("rc") == 0
                    and not st["step"].startswith(("retry", "rebuild"))]
    collected = [ex for ex in exchanges
                 if collect and any(ex in st["step"] for st in collector_ok)]

    report["run"] = {"startedAt": started.isoformat(timespec="seconds"),
                     "seconds": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
                     "exchanges": exchanges, "collected": collected,
                     "steps": steps,
                     "failedSteps": [s["step"] for s in steps if s["rc"] not in (0, "skipped")]}
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # One compact line per run: the history of whether each day's closes landed.
    line = {"ranAt": report["run"]["startedAt"], "seconds": report["run"]["seconds"],
            "collected": collected,
            "failedSteps": report["run"]["failedSteps"],
            "exchanges": {ex: {k: r[k] for k in ("expectedSession", "observedSession",
                                                 "status", "currentPct")}
                          | {"lagging": len(r["lagging"])}
                          for ex, r in report["exchanges"].items()}}
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return report
