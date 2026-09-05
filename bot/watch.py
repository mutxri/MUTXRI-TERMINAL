#!/usr/bin/env python3
"""bot/watch.py - telling you what changed, not what exists.

Every other part of this package produces a snapshot: the scan ranks today's
news, the screener ranks today's statements. Run either twice and you see the
same things twice. A desk does not want the same things twice - it wants the
difference, and only for the securities it actually holds.

So this module keeps two pieces of state on disk:

  watchlist.json    what to care about - tickers, exchanges, an impact floor
  watch_state.json  what has already been reported

and reports only what is new since the last check. A signal fires once. A
statement flag fires when it appears, and its disappearance is reported too,
because "the going-concern flag cleared" is news.

Seen-state is pruned by age so the file cannot grow without bound, and the
pruning window is deliberately longer than the news window - a signal must not
expire from the state file while it is still in the scan, or it would be
reported as new all over again.
"""
import datetime as dt, json, os, time

from . import screen as SC, statements as S

SD = S.SD
WATCHLIST = os.path.join(SD, "watchlist.json")
STATE = os.path.join(SD, "watch_state.json")
SIGNALS = os.path.join(SD, "bot_signals.json")

# The news scan keeps 7 days; hold seen-ids for 30 so nothing can re-fire.
SEEN_TTL_DAYS = 30
DEFAULT_MIN_IMPACT = 35.0


def _read(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _write(path, blob):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=1)


# ----------------------------------------------------------------- watchlist
def watchlist():
    wl = _read(WATCHLIST, {})
    return {"tickers": [t.upper() for t in wl.get("tickers", [])],
            "exchanges": [e.upper() for e in wl.get("exchanges", [])],
            "minImpact": wl.get("minImpact", DEFAULT_MIN_IMPACT),
            "flagSeverities": wl.get("flagSeverities", ["high"])}


def add(tickers=(), exchanges=(), min_impact=None, severities=None):
    wl = watchlist()
    wl["tickers"] = sorted(set(wl["tickers"]) | {t.upper() for t in tickers})
    wl["exchanges"] = sorted(set(wl["exchanges"]) | {e.upper() for e in exchanges})
    if min_impact is not None:
        wl["minImpact"] = float(min_impact)
    if severities:
        wl["flagSeverities"] = list(severities)
    _write(WATCHLIST, wl)
    return wl


def remove(tickers=(), exchanges=()):
    wl = watchlist()
    wl["tickers"] = [t for t in wl["tickers"] if t not in {x.upper() for x in tickers}]
    wl["exchanges"] = [e for e in wl["exchanges"]
                       if e not in {x.upper() for x in exchanges}]
    _write(WATCHLIST, wl)
    return wl


def _base(ticker):
    """ABG.JO and ABG are the same security for watchlist purposes."""
    return (ticker or "").upper().split(".")[0]


def _matches(wl, signal):
    """Does this signal concern anything on the watchlist?"""
    if wl["exchanges"] and signal.get("exchange", "").upper() in wl["exchanges"]:
        return True, "exchange %s" % signal.get("exchange")
    want = {_base(t) for t in wl["tickers"]}
    for s in signal.get("securities", []):
        if _base(s.get("ticker")) in want:
            return True, "holds %s" % (s.get("ticker") or "")
    return False, None


# --------------------------------------------------------------------- check
def check(record=True, include_statements=True):
    """Return alerts new since the last check.

    `record=False` previews without consuming them, so a dry run does not
    silently mark everything as reported and hide it from the next real check.
    """
    wl = watchlist()
    if not wl["tickers"] and not wl["exchanges"]:
        return {"error": "watchlist is empty - add tickers or exchanges first",
                "news": [], "statements": []}

    state = _read(STATE, {})
    seen = state.get("seenSignals", {})
    prior_flags = state.get("flags", {})
    now = time.time()

    news = []
    blob = _read(SIGNALS, None)
    if blob:
        for sig in blob.get("signals", []):
            if sig["id"] in seen:
                continue
            if sig.get("impact", 0) < wl["minImpact"]:
                continue
            hit, why = _matches(wl, sig)
            if not hit:
                continue
            news.append({
                "id": sig["id"], "exchange": sig["exchange"], "title": sig["title"],
                "impact": sig["impact"], "bias": sig["bias"], "url": sig.get("url"),
                "publisher": sig.get("publisher"), "ts": sig.get("ts"),
                "why": why,
                "securities": [s.get("ticker") for s in sig.get("securities", [])][:4],
            })

    statements = []
    if include_statements and wl["tickers"]:
        want = {_base(t) for t in wl["tickers"]}
        companies = SC.load()
        sev_ok = set(wl["flagSeverities"])
        for c in companies:
            if _base(c["ticker"]) not in want:
                continue
            now_ids = {f["id"] for f in c["flags"] if f["severity"] in sev_ok}
            was_ids = set(prior_flags.get(c["ticker"], []))
            for fid in sorted(now_ids - was_ids):
                f = next(f for f in c["flags"] if f["id"] == fid)
                statements.append({"ticker": c["ticker"], "name": c["name"],
                                   "change": "appeared", "flag": fid,
                                   "severity": f["severity"], "label": f["label"],
                                   "period": c["latest"].get("period")})
            for fid in sorted(was_ids - now_ids):
                statements.append({"ticker": c["ticker"], "name": c["name"],
                                   "change": "cleared", "flag": fid,
                                   "severity": "info",
                                   "label": "%s no longer flagged" % fid,
                                   "period": c["latest"].get("period")})

    if record:
        for n in news:
            seen[n["id"]] = int(now)
        cutoff = now - SEEN_TTL_DAYS * 86400
        seen = {k: v for k, v in seen.items() if v >= cutoff}
        flags = dict(prior_flags)
        if include_statements and wl["tickers"]:
            want = {_base(t) for t in wl["tickers"]}
            for c in SC.load():
                if _base(c["ticker"]) in want:
                    flags[c["ticker"]] = sorted(
                        f["id"] for f in c["flags"]
                        if f["severity"] in set(wl["flagSeverities"]))
        _write(STATE, {"seenSignals": seen, "flags": flags,
                       "lastCheck": dt.datetime.now(dt.timezone.utc)
                                      .isoformat(timespec="seconds")})

    news.sort(key=lambda x: -x["impact"])
    return {"watchlist": wl, "news": news, "statements": statements,
            "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "signalsFileAge": (None if not blob else blob.get("generated"))}


def reset():
    """Forget what has been reported - the next check sees everything again."""
    if os.path.exists(STATE):
        os.remove(STATE)
    return True


if __name__ == "__main__":
    print(json.dumps(check(record=False), indent=1)[:2000])
