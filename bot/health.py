#!/usr/bin/env python3
"""bot/health.py - is the data under this bot still true?

Everything above this file assumes static_data is current. Nothing checks that,
and stale data fails quietly: a price file three weeks old still parses, still
renders, still gets scored, and reports yesterday's market with total confidence.
The bonds file already ships rows tagged "15 days ago - may be out of date".

So this reports age and coverage for every input the bot depends on, and grades
each one. It fixes nothing - it tells you which collector to run.

Freshness is judged per file, because these sources genuinely differ: prices go
stale in a day, parsed annual statements do not go stale for months, and a
sovereign yield curve sits somewhere between.
"""
import datetime as dt, json, os, time

from . import statements as S, universe as U

SD = S.SD

# name -> (warn after N days, fail after N days, what it is)
EXPECTATIONS = {
    "indices.json": (2, 7, "index levels"),
    "commodities.json": (2, 7, "commodity prices"),
    "fx.json": (3, 14, "FX matrix"),
    "bonds.json": (10, 30, "sovereign yields"),
    "bot_signals.json": (1, 4, "news scan"),
    "bot_market_state.json": (1, 4, "consolidated market state"),
    "financials_index.json": (120, 400, "statement index"),
    "logos.json": (400, 1000, "company domains"),
}
for _ex in U.EXCHANGES:
    EXPECTATIONS["market_%s.json" % _ex] = (3, 10, "%s prices" % _ex)
    EXPECTATIONS["listing_%s.json" % _ex] = (7, 30, "%s listing" % _ex)


def _age_days(path):
    try:
        return (time.time() - os.path.getmtime(path)) / 86400.0
    except OSError:
        return None


def _grade(age, warn, fail):
    if age is None:
        return "missing"
    if age >= fail:
        return "stale"
    if age >= warn:
        return "ageing"
    return "ok"


def files():
    """Age and grade for each expected data file."""
    out = []
    for name, (warn, fail, what) in sorted(EXPECTATIONS.items()):
        p = os.path.join(SD, name)
        exists = os.path.exists(p)
        age = _age_days(p) if exists else None
        out.append({"file": name, "what": what, "exists": exists,
                    "ageDays": round(age, 2) if age is not None else None,
                    "warnAfter": warn, "failAfter": fail,
                    "status": _grade(age, warn, fail) if exists else "missing"})
    return out


def coverage():
    """How much of each exchange actually carries usable data."""
    out = []
    uni = U.load()
    for ex in U.EXCHANGES:
        secs = uni.get(ex) or []
        if not secs:
            out.append({"exchange": ex, "status": "missing", "securities": 0})
            continue
        priced = sum(1 for s in secs if s.get("price") is not None)
        chg = sum(1 for s in secs if s.get("chgPct") is not None)
        flagged = sum(1 for s in secs if s.get("chgFlag"))
        pct = 100.0 * priced / len(secs)
        out.append({
            "exchange": ex, "securities": len(secs), "priced": priced,
            "withChange": chg, "suspectRows": flagged,
            "pricedPct": round(pct, 1),
            # Below half priced the board is not usable for breadth or movers.
            "status": "ok" if pct >= 80 else ("thin" if pct >= 50 else "poor"),
        })
    return out


def statements_health():
    """Statement corpus size and how much of it is analysable."""
    tickers = S.available_public()
    idx = os.path.join(SD, "financials_index.json")
    listed = 0
    if os.path.exists(idx):
        try:
            listed = len(json.load(open(idx, encoding="utf-8")))
        except Exception:
            pass
    return {"tickersWithStatements": len(tickers), "indexEntries": listed,
            "status": "ok" if len(tickers) > 100 else "thin"}


def sources():
    """Did the last news scan reach its feeds?"""
    p = os.path.join(SD, "bot_signals.json")
    if not os.path.exists(p):
        return {"status": "missing", "detail": "no scan has been run"}
    try:
        blob = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        return {"status": "unreadable", "detail": type(e).__name__}
    rep = blob.get("sourceReport", {})
    errs = rep.get("errors", [])
    ok = len(rep.get("sources", []))
    social = (rep.get("social") or {}).get("status")
    return {"status": "ok" if not errs else ("degraded" if ok else "down"),
            "sourcesOk": ok, "sourcesFailed": len(errs),
            "failures": [{"source": e["source"], "error": e["error"]} for e in errs],
            "social": social, "generated": blob.get("generated"),
            "signals": (blob.get("counts") or {}).get("signals")}


def credentials():
    """Which optional capabilities are switched on. Never prints a secret."""
    def has(*names):
        return any(os.environ.get(n, "").strip() for n in names)
    return [
        {"capability": "Claude analysis (brief/ask/explain/PDF reading)",
         "env": "ANTHROPIC_API_KEY", "enabled": has("ANTHROPIC_API_KEY",
                                                    "ANTHROPIC_AUTH_TOKEN")},
        {"capability": "X/Twitter news tier", "env": "X_BEARER_TOKEN",
         "enabled": has("X_BEARER_TOKEN")},
        {"capability": "Posting to X", "env": "X_API_KEY + 3 more",
         "enabled": has("X_API_KEY") and has("X_API_SECRET")
                    and has("X_ACCESS_TOKEN") and has("X_ACCESS_SECRET")},
        {"capability": "Posting to LinkedIn", "env": "LINKEDIN_ACCESS_TOKEN",
         "enabled": has("LINKEDIN_ACCESS_TOKEN") and has("LINKEDIN_URN")},
    ]


def report():
    f = files()
    c = coverage()
    s = sources()
    worst = "ok"
    for row in f:
        if row["status"] in ("missing", "stale"):
            worst = "problems"
    for row in c:
        if row["status"] in ("poor", "missing"):
            worst = "problems"
    if s.get("status") in ("down", "missing", "unreadable"):
        worst = "problems"
    return {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "overall": worst, "files": f, "coverage": c,
            "statements": statements_health(), "sources": s,
            "credentials": credentials()}


if __name__ == "__main__":
    r = report()
    print("overall:", r["overall"])
    for row in r["files"]:
        print("  %-26s %-8s %s" % (row["file"], row["status"],
                                   ("%.1fd" % row["ageDays"]) if row["ageDays"] is not None else "-"))
    for row in r["coverage"]:
        print("  %-6s %s" % (row["exchange"], row))
