#!/usr/bin/env python3
"""bot/technicals.py - what the price history itself says.

The daily end-of-day update keeps every security's bars current, so the bot can
read the tape as well as the filings: trend, momentum, volatility, volume and
where a price sits in its year.

Python computes every number here. The rules this module holds itself to:

  * Only real bars. A security with too little history gets "not enough
    history", never an indicator seeded from invented values.
  * Thin trading is named, not averaged away. A price that did not change for
    most of the last sixty sessions has a low volatility and a flat RSI because
    nobody traded it, not because it is calm. Those securities carry a caution
    and are left out of the board scan.
  * Daily returns are only taken between consecutive sessions, and a move beyond
    the exchange's plausibility cap (universe.MAX_MOVE) is excluded as a bad
    print rather than treated as a real day.
  * 52-week highs and lows use closing prices. Some published bars are
    internally inconsistent (open above high); closes are the field that is
    reliably what the market settled at.

Indicators use their standard definitions: simple and exponential moving
averages (EMA seeded with the SMA of its first window), Wilder's RSI(14) and
ATR(14), MACD(12, 26, 9), Bollinger Bands(20, 2) with population deviation.
"""
import datetime as dt
import glob
import json
import math
import os

from . import eod as E, universe as U

HIST = E.HIST
MIN_BARS = 30            # below this nothing is computed
THIN_ZERO_CHANGE = 0.50  # more unchanged closes than this in 60 bars = thin
THIN_TRADED = 0.50       # printed on fewer than half the sessions = thin
LOOKBACK_DAYS = {"1w": 7, "1m": 30, "3m": 91, "6m": 182, "1y": 365}
CROSS_WINDOW = 5         # a moving-average cross this recent is an event


# ------------------------------------------------------------------ loading
def _f(v):
    return float(v) if isinstance(v, (int, float)) else None


def _candidates(ticker, ex):
    t = ticker.strip().upper()
    base = t[:-3] if t.endswith((".JO", ".CA")) else t
    return {"NSE": "NSE_%s.json" % base, "NGX": "NGX_%s.json" % base,
            "JSE": "%s.JO.json" % base, "EGX": "%s.CA.json" % base}[ex]


def locate(ticker, ex=None):
    """(exchange, id, path) for a ticker, or None. Raises when ambiguous."""
    t = ticker.strip().upper()
    if ex:
        exs = [ex.upper()]
    elif t.endswith(".JO"):
        exs = ["JSE"]
    elif t.endswith(".CA"):
        exs = ["EGX"]
    else:
        exs = list(U.EXCHANGES)
    hits = []
    for x in exs:
        name = _candidates(t, x)
        path = os.path.join(HIST, name)
        if os.path.exists(path):
            prefix = E.PATTERNS[x][1]
            hits.append((x, name[len(prefix):-len(".json")], path))
    if len(hits) > 1:
        raise ValueError("%s is on more than one exchange (%s); pass --exchange"
                         % (ticker, ", ".join(h[0] for h in hits)))
    return hits[0] if hits else None


def load_bars(path):
    """(document, bars) with bars cleaned: dated, positive close, one per day."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    by_day = {}
    for b in doc.get("bars") or []:
        d = E.bar_day(b.get("t"))
        c = _f(b.get("c"))
        if d is None or c is None or c <= 0:
            continue
        by_day[d] = {"d": d, "o": _f(b.get("o")), "h": _f(b.get("h")),
                     "l": _f(b.get("l")), "c": c, "v": _f(b.get("v"))}
    return doc, [by_day[k] for k in sorted(by_day)]


def exchange_files(ex):
    pattern = E.PATTERNS[ex][0]
    prefix = E.PATTERNS[ex][1]
    for path in sorted(glob.glob(os.path.join(HIST, pattern))):
        name = os.path.basename(path)
        if name.endswith(".max.json"):
            continue
        yield name[len(prefix):-len(".json")], path


# --------------------------------------------------------------- primitives
def mean(xs):
    return sum(xs) / float(len(xs)) if xs else None


def stdev(xs, sample=True):
    n = len(xs)
    if n < (2 if sample else 1):
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1 if sample else n))


def sma(xs, n):
    return sum(xs[-n:]) / float(n) if n > 0 and len(xs) >= n else None


def sma_series(xs, n):
    out, run = [], 0.0
    for i, x in enumerate(xs):
        run += x
        if i >= n:
            run -= xs[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def ema_series(xs, n):
    """EMA seeded with the simple average of the first n values."""
    if len(xs) < n:
        return [None] * len(xs)
    k = 2.0 / (n + 1)
    e = sum(xs[:n]) / float(n)
    out = [None] * (n - 1) + [e]
    for x in xs[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes, n=14):
    """Wilder's RSI. None when there is too little history or no movement."""
    if len(closes) < n + 1:
        return None
    ch = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ag = sum(max(c, 0.0) for c in ch[:n]) / n
    al = sum(max(-c, 0.0) for c in ch[:n]) / n
    for c in ch[n:]:
        ag = (ag * (n - 1) + max(c, 0.0)) / n
        al = (al * (n - 1) + max(-c, 0.0)) / n
    if ag == 0 and al == 0:
        return None
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def macd(closes, fast=12, slow=26, signal=9):
    if len(closes) < slow + signal - 1:
        return None
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    line = [a - b for a, b in zip(ef, es) if a is not None and b is not None]
    sig = ema_series(line, signal)
    hist = [l - s for l, s in zip(line, sig) if s is not None]
    cross = None
    if len(hist) >= 2 and hist[-2] * hist[-1] < 0:
        cross = "bullish" if hist[-1] > 0 else "bearish"
    return {"macd": line[-1], "signal": sig[-1], "histogram": hist[-1],
            "crossedToday": cross}


def bollinger(closes, n=20, k=2.0):
    if len(closes) < n:
        return None
    w = closes[-n:]
    m = sum(w) / n
    sd = stdev(w, sample=False)
    up, lo = m + k * sd, m - k * sd
    return {"middle": m, "upper": up, "lower": lo,
            "pctB": (closes[-1] - lo) / (up - lo) if up > lo else None,
            "bandwidthPct": (up - lo) / m * 100 if m else None}


def atr(bars, n=14):
    """Wilder's average true range. None if any bar in the run lacks a range."""
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, b in zip(bars[:-1], bars[1:]):
        if b["h"] is None or b["l"] is None:
            return None
        # max(h, l, prev close) - min(h, l, prev close) is the textbook true
        # range, and stays a range on the bars published with high below low.
        trs.append(max(b["h"], b["l"], prev["c"]) - min(b["h"], b["l"], prev["c"]))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def daily_returns(ex, bars):
    """[(date, return)] between consecutive sessions, bad prints excluded."""
    cap = U.MAX_MOVE.get(ex, 50.0) / 100.0
    out, gaps, suspect = [], 0, 0
    for prev, b in zip(bars[:-1], bars[1:]):
        if E.sessions_between(ex, prev["d"], b["d"]) != 1:
            gaps += 1
            continue
        r = b["c"] / prev["c"] - 1
        if abs(r) > cap:
            suspect += 1
            continue
        out.append((b["d"], r))
    return out, {"gapsSkipped": gaps, "suspectMovesExcluded": suspect}


def max_drawdown(closes, dates=None):
    if len(closes) < 2:
        return None
    peak_i, worst, span = 0, 0.0, (0, 0)
    for i, c in enumerate(closes):
        if c > closes[peak_i]:
            peak_i = i
        dd = c / closes[peak_i] - 1
        if dd < worst:
            worst, span = dd, (peak_i, i)
    p, t = span
    out = {"pct": worst * 100, "peak": closes[p], "trough": closes[t],
           "recovered": worst == 0 or max(closes[t:]) >= closes[p]}
    if dates:
        out["peakDate"], out["troughDate"] = str(dates[p]), str(dates[t])
    return out


def _close_on_or_before(bars, day):
    lo, hi = 0, len(bars) - 1
    if not bars or bars[0]["d"] > day:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if bars[mid]["d"] <= day:
            lo = mid
        else:
            hi = mid - 1
    return bars[lo]


# ---------------------------------------------------------------- analysis
def liquidity(ex, bars):
    last = bars[-1]["d"]
    recent = bars[-61:]
    unchanged = sum(1 for a, b in zip(recent[:-1], recent[1:]) if a["c"] == b["c"])
    zero_change = unchanged / float(max(1, len(recent) - 1))
    start = last - dt.timedelta(days=90)
    sessions = E.sessions_between(ex, start, last)
    printed = sum(1 for b in bars if b["d"] > start)
    traded = min(1.0, printed / float(sessions)) if sessions else None
    expected = E.expected_session(ex)
    behind = E.sessions_between(ex, last, expected) if expected else None
    thin = zero_change > THIN_ZERO_CHANGE or (traded is not None and traded < THIN_TRADED)
    return {"unchangedShare60": round(zero_change, 3),
            "sessionsPrintedShare90d": round(traded, 3) if traded is not None else None,
            "sessionsBehind": behind, "thin": thin}


_NAMES = {}


def display_name(ex, sid):
    """History files from the exchanges carry no name; the listing does."""
    if not _NAMES:
        try:
            for x, rows in U.load().items():
                for r in rows:
                    t = str(r.get("ticker") or "").upper()
                    _NAMES[(x, t[:-3] if t.endswith((".JO", ".CA")) else t)] = r.get("name")
        except Exception:
            _NAMES[None] = None
    s = sid.upper()
    return _NAMES.get((ex, s[:-3] if s.endswith((".JO", ".CA")) else s))


def latest_bar_suspect(ex, bars):
    """The newest bar moved beyond the exchange's plausibility cap in one session."""
    if len(bars) < 2:
        return None
    prev, last = bars[-2], bars[-1]
    if E.sessions_between(ex, prev["d"], last["d"]) != 1:
        return None
    move = (last["c"] / prev["c"] - 1) * 100
    if abs(move) <= U.MAX_MOVE.get(ex, 50.0):
        return None
    return {"movePct": move, "previousClose": prev["c"],
            "note": "a %+.1f%% one-session move is beyond the %s plausibility cap of %.0f%%; "
                    "treat the latest price as a likely bad print until the next session "
                    "confirms it" % (move, ex, U.MAX_MOVE.get(ex, 50.0))}


def analyse_bars(ex, sid, doc, bars):
    if len(bars) < MIN_BARS:
        return {"available": False, "exchange": ex, "id": sid,
                "name": doc.get("name") or display_name(ex, sid),
                "reason": "only %d bars of history" % len(bars)}
    closes = [b["c"] for b in bars]
    dates = [b["d"] for b in bars]
    last = bars[-1]
    asof = last["d"]
    out = {"available": True, "exchange": ex, "id": sid,
           "name": doc.get("name") or display_name(ex, sid),
           "currency": doc.get("currency"), "asOf": str(asof),
           "firstBar": str(dates[0]), "bars": len(bars), "close": last["c"],
           "liquidity": liquidity(ex, bars),
           "latestBarSuspect": latest_bar_suspect(ex, bars)}

    perf = {}
    for label, days in LOOKBACK_DAYS.items():
        ref = _close_on_or_before(bars, asof - dt.timedelta(days=days))
        perf[label] = (last["c"] / ref["c"] - 1) * 100 if ref else None
    ytd_ref = _close_on_or_before(bars, dt.date(asof.year - 1, 12, 31))
    perf["ytd"] = (last["c"] / ytd_ref["c"] - 1) * 100 if ytd_ref else None
    out["performancePct"] = perf

    year = [b for b in bars if b["d"] > asof - dt.timedelta(days=365)]
    hi = max(year, key=lambda b: b["c"])
    lo = min(year, key=lambda b: b["c"])
    full_year = dates[0] <= asof - dt.timedelta(days=330)
    prior = [b["c"] for b in year[:-1]]
    out["range52w"] = {
        "basis": "closing prices" if full_year else "closing prices since %s" % dates[0],
        "high": hi["c"], "highDate": str(hi["d"]), "low": lo["c"], "lowDate": str(lo["d"]),
        "fromHighPct": (last["c"] / hi["c"] - 1) * 100,
        "fromLowPct": (last["c"] / lo["c"] - 1) * 100,
        "newHigh": bool(full_year and prior and last["c"] > max(prior)),
        "newLow": bool(full_year and prior and last["c"] < min(prior)),
    }

    s50, s200 = sma_series(closes, 50), sma_series(closes, 200)
    cross = None
    for i in range(max(1, len(closes) - CROSS_WINDOW), len(closes)):
        a0, b0, a1, b1 = s50[i - 1], s200[i - 1], s50[i], s200[i]
        if None in (a0, b0, a1, b1):
            continue
        if a0 <= b0 and a1 > b1:
            cross = {"type": "golden", "date": str(dates[i])}
        elif a0 >= b0 and a1 < b1:
            cross = {"type": "death", "date": str(dates[i])}
    trend = {"sma20": sma(closes, 20), "sma50": s50[-1], "sma200": s200[-1],
             "recentCross": cross}
    if s50[-1] and s200[-1]:
        trend["state"] = ("uptrend" if last["c"] > s50[-1] > s200[-1] else
                          "downtrend" if last["c"] < s50[-1] < s200[-1] else "mixed")
    out["trend"] = trend

    out["momentum"] = {"rsi14": rsi(closes, 14), "macd": macd(closes)}
    out["bands"] = bollinger(closes)
    a = atr(bars, 14)
    out["atr14"] = a
    out["atr14Pct"] = a / last["c"] * 100 if a is not None else None

    rets, rinfo = daily_returns(ex, bars)
    out["returnsInfo"] = rinfo
    vol = {}
    for label, days in (("3m", 91), ("1y", 365)):
        w = [r for d, r in rets if d > asof - dt.timedelta(days=days)]
        sd = stdev(w)
        vol[label] = sd * math.sqrt(252) * 100 if sd is not None and len(w) >= 20 else None
    out["volatilityAnnualPct"] = vol
    out["lastReturnPct"] = rets[-1][1] * 100 if rets and rets[-1][0] == asof else None
    prior_r = [r for d, r in rets[:-1] if d > asof - dt.timedelta(days=91)]
    sd = stdev(prior_r)
    out["lastReturnSigma"] = (rets[-1][1] / sd if rets and rets[-1][0] == asof
                              and sd and len(prior_r) >= 20 else None)

    vols = [b["v"] for b in bars[-21:-1] if b["v"] is not None]
    lv = last["v"]
    volume = {"last": lv, "avg20": mean(vols) if len(vols) >= 15 else None}
    if volume["avg20"] and lv is not None:
        volume["ratio"] = lv / volume["avg20"]
        vsd = stdev(vols)
        volume["zScore"] = (lv - volume["avg20"]) / vsd if vsd else None
    out["volume"] = volume

    out["drawdown1y"] = max_drawdown([b["c"] for b in year], [b["d"] for b in year])
    out["priorHigh52w"] = max(prior) if prior else None
    cautions = []
    if out["latestBarSuspect"]:
        cautions.append(out["latestBarSuspect"]["note"])
    if out["liquidity"]["thin"]:
        cautions.append("thinly traded: the price rarely changes or rarely prints, so "
                        "volatility, RSI and trend describe the absence of trading")
    if cautions:
        out["caution"] = "; ".join(cautions)
    return out


def analyse(ticker, ex=None):
    loc = locate(ticker, ex)
    if not loc:
        return {"available": False, "reason": "no price history on file for %s" % ticker}
    x, sid, path = loc
    doc, bars = load_bars(path)
    return analyse_bars(x, sid, doc, bars)


# -------------------------------------------------------------------- scan
EVENT_LABELS = {
    "new_52w_high": "new 52-week closing high",
    "new_52w_low": "new 52-week closing low",
    "golden_cross": "50-day average crossed above the 200-day",
    "death_cross": "50-day average crossed below the 200-day",
    "overbought": "RSI(14) at or above 70",
    "oversold": "RSI(14) at or below 30",
    "volume_spike": "volume at least 3x its 20-day average and 3 deviations above it",
    "outsized_move": "daily move beyond 3 standard deviations of the last quarter",
    "macd_cross": "MACD crossed its signal line on the latest session",
}


def events_for(a):
    ev = []
    if a.get("latestBarSuspect"):
        # An event built on a bad print is a false alarm; report nothing.
        return ev
    r = a["range52w"]
    if r["newHigh"]:
        ev.append(("new_52w_high", "%g, prior high %g" % (a["close"], a["priorHigh52w"])))
    if r["newLow"]:
        ev.append(("new_52w_low", "%g" % a["close"]))
    cross = a["trend"].get("recentCross")
    if cross:
        ev.append((cross["type"] + "_cross", "on %s" % cross["date"]))
    rs = a["momentum"]["rsi14"]
    if rs is not None and rs >= 70:
        ev.append(("overbought", "RSI %.1f" % rs))
    if rs is not None and rs <= 30:
        ev.append(("oversold", "RSI %.1f" % rs))
    v = a["volume"]
    if (v.get("ratio") or 0) >= 3 and (v.get("zScore") or 0) >= 3:
        ev.append(("volume_spike", "%.1fx average, z %.1f" % (v["ratio"], v["zScore"])))
    sg = a.get("lastReturnSigma")
    if sg is not None and abs(sg) >= 3:
        ev.append(("outsized_move", "%+.2f%% (%.1f sigma)" % (a["lastReturnPct"], sg)))
    m = a["momentum"]["macd"]
    if m and m.get("crossedToday"):
        ev.append(("macd_cross", m["crossedToday"]))
    return ev


def scan(ex, events=None):
    """Every liquid, current security on one board, with its technical events."""
    ex = ex.upper()
    results = []
    for sid, path in exchange_files(ex):
        try:
            doc, bars = load_bars(path)
        except Exception:
            continue
        if bars:
            results.append((sid, doc, bars))
    newest = max((b[-1]["d"] for _, _, b in results), default=None)
    out = {"exchange": ex, "asOf": str(newest) if newest else None, "scanned": 0,
           "skipped": {"stale": 0, "thin": 0, "short": 0, "suspect": 0}, "events": [],
           "suspect": []}
    for sid, doc, bars in results:
        if bars[-1]["d"] != newest:
            out["skipped"]["stale"] += 1
            continue
        if len(bars) < 60:
            out["skipped"]["short"] += 1
            continue
        a = analyse_bars(ex, sid, doc, bars)
        if a["latestBarSuspect"]:
            out["skipped"]["suspect"] += 1
            out["suspect"].append({"id": sid, "name": a["name"], "close": a["close"],
                                   "movePct": a["latestBarSuspect"]["movePct"]})
            continue
        if a["liquidity"]["thin"]:
            out["skipped"]["thin"] += 1
            continue
        out["scanned"] += 1
        for kind, detail in events_for(a):
            if events and kind not in events:
                continue
            out["events"].append({"id": sid, "name": a["name"], "event": kind,
                                  "label": EVENT_LABELS[kind], "detail": detail,
                                  "close": a["close"],
                                  "chg1dPct": a["lastReturnPct"]})
    order = list(EVENT_LABELS)
    out["events"].sort(key=lambda e: (order.index(e["event"]), e["id"]))
    return out
