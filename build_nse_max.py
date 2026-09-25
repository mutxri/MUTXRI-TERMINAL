#!/usr/bin/env python3
"""build_nse_max.py - generate monthly .max.json for NSE from daily history.

The chart's 10Y/ALL ranges read <SYM>.max.json (monthly) when it exists, else
they fall back to a thin daily slice. NSE has no monthly file, so 10Y renders
~2 years instead of 10. This aggregates each NSE_<SYM>.json daily file into a
monthly OHLC bar (first open, max high, min low, last close) and writes it as
NSE_<SYM>.max.json, matching the JSE/EGX layout the chart already understands.

Fill-only and lossless: reads the daily file, never rewrites it. A monthly file
that already exists is left untouched unless --force is passed.
"""
import json, glob, os, sys

HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data", "history")
FORCE = "--force" in sys.argv

def month_key(t):
    s = str(t)
    # ISO "YYYY-MM-DD" -> "YYYY-MM"; epoch seconds (numeric) -> its YYYY-MM
    if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
        try:
            n = float(s)
            if n > 1e11:
                n /= 1000.0
            import datetime
            return datetime.datetime.utcfromtimestamp(n).strftime("%Y-%m")
        except Exception:
            return s[:7]
    return s[:7]

def build(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return 0
    bars = d.get("bars", [])
    if not bars:
        return 0
    # group by YYYY-MM, preserving first-seen order of months
    months = {}
    order = []
    for b in bars:
        t = b.get("t")
        if t is None:
            continue
        k = month_key(t)
        if k not in months:
            months[k] = {"t": None, "o": None, "h": None, "l": None, "c": None, "v": 0}
            order.append(k)
        m = months[k]
        o, h, l, c, v = b.get("o"), b.get("h"), b.get("l"), b.get("c"), b.get("v")
        def f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        o, h, l, c, v = f(o), f(h), f(l), f(c), f(v)
        if m["o"] is None and o is not None:
            m["o"] = o
        if h is not None:
            m["h"] = h if m["h"] is None else max(m["h"], h)
        if l is not None:
            m["l"] = l if m["l"] is None else min(m["l"], l)
        if c is not None:
            m["c"] = c
        if v:
            m["v"] = (m["v"] or 0) + v
        # use the last bar's date in the month as the monthly timestamp (ISO)
        m["t"] = str(t)[:10]
    out_bars = []
    for k in order:
        m = months[k]
        if m["o"] is None or m["c"] is None:
            continue
        out_bars.append({"t": m["t"], "o": m["o"], "h": m["h"], "l": m["l"], "c": m["c"], "v": m["v"]})
    if not out_bars:
        return 0
    out = path[:-5] + ".max.json"
    if os.path.exists(out) and not FORCE:
        return 0
    json.dump({"sym": os.path.basename(path)[:-5], "bars": out_bars}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    return len(out_bars)

if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(HIST, "NSE_*.json")))
    files = [f for f in files if not f.endswith(".max.json")]
    total = 0
    for f in files:
        n = build(f)
        if n:
            total += 1
            print(f"{os.path.basename(f)}: {n} monthly bars")
    print(f"DONE: {total} monthly files written")
