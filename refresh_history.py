#!/usr/bin/env python3
"""refresh_history.py - refresh + backfill daily/monthly OHLC history from
Yahoo for JSE/EGX securities.

Two files per symbol, matching what the terminal chart panel expects:
  static_data/history/<SYM>.json      daily bars   (1D / 1M / 1Y ranges, 52w)
  static_data/history/<SYM>.max.json  monthly bars (10Y / ALL ranges)

Unlike the original fetch_history.py this NEVER overwrites a good file with an
empty one: a failed fetch leaves whatever was already on disk untouched, so a
Yahoo outage cannot silently wipe the archive.

usage: refresh_history.py [JSE,EGX] [--workers N] [--only-empty]
"""
import json, os, sys, time, datetime, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "history")
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

lock = threading.Lock()
TOPUP = "--topup" in sys.argv
stats = {"daily": 0, "max": 0, "nodata": 0, "kept": 0, "sym": 0}

def load_listing(ex):
    p = os.path.join(BASE, "static_data", f"listing_{ex}.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("stocks", [])

def chart(sym, rng, ivl, retries=4):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={ivl}"
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (404, 422):      # symbol genuinely not on Yahoo
                return None
            time.sleep(2 * (a + 1) + a * 3)
        except Exception:
            time.sleep(2 * (a + 1))
    return None

def to_bars(d):
    res = (d or {}).get("chart", {}).get("result") or []
    if not res:
        return [], {}
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = (r0.get("indicators", {}).get("quote") or [{}])[0]
    o, h, l, c, v = q.get("open") or [], q.get("high") or [], q.get("low") or [], q.get("close") or [], q.get("volume") or []
    bars = []
    for i in range(len(ts)):
        if i >= len(c) or c[i] is None:
            continue
        bars.append({
            "t": ts[i],
            "o": o[i] if i < len(o) and o[i] is not None else c[i],
            "h": h[i] if i < len(h) and h[i] is not None else c[i],
            "l": l[i] if i < len(l) and l[i] is not None else c[i],
            "c": c[i],
            "v": v[i] if i < len(v) and v[i] is not None else 0,
        })
    return bars, (r0.get("meta") or {})

def merge_bars(old, new):
    """union by session date, newest value wins - a short recent window must
    extend the archive, never replace it"""
    by_day = {}
    for b in list(old) + list(new):
        t = b.get("t")
        if t is None:
            continue
        key = datetime.datetime.utcfromtimestamp(int(t)).date().isoformat()
        by_day[key] = b
    return [by_day[k] for k in sorted(by_day.keys())]


def with_latest_session(bars, meta):
    """Yahoo's daily arrays lag the JSE/EGX board by a session or two: the
    timestamps for the last day or two are present but every OHLC value is
    null, while meta.regularMarketPrice already carries that session's close.
    Without this the terminal quotes a two-day-old price as today's (ABG showed
    22,854 when the 28 Aug close was 23,147). Append the meta session as a real
    dated bar when it is newer than anything in the array."""
    px = meta.get("regularMarketPrice")
    t = meta.get("regularMarketTime")
    if px is None or not t:
        return bars
    day = datetime.datetime.utcfromtimestamp(t).date()
    if bars:
        last_day = datetime.datetime.utcfromtimestamp(bars[-1]["t"]).date()
        if day <= last_day:
            return bars
    prev = bars[-1]["c"] if bars else px
    bar = {
        "t": int(t),
        "o": meta.get("regularMarketOpen") or prev,
        "h": meta.get("regularMarketDayHigh") or max(px, prev),
        "l": meta.get("regularMarketDayLow") or min(px, prev),
        "c": px,
        "v": meta.get("regularMarketVolume") or 0,
    }
    # Carry the exchange's own day change with the bar. Yahoo leaves the last
    # session or two null in the daily array while still knowing their closes,
    # so a change recomputed from the previous POPULATED bar silently spans the
    # gap - Sasol read +4.90% (26 Aug -> 28 Aug) when the 28 Aug session was
    # +1.05%. Recording the real figure beats inventing the missing bar.
    chg = meta.get("regularMarketChangePercent")
    if chg is not None:
        bar["chg"] = round(float(chg), 4)
    return bars + [bar]


def existing_bars(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("bars", [])
    except Exception:
        return []

def write_if_better(path, sym, name, currency, bars):
    """Only replace a file when the new fetch is at least as good as what we
    already have - a short/empty response never destroys a deeper archive."""
    old = existing_bars(path)
    if len(bars) < max(2, len(old)) and len(old) >= 2:
        with lock:
            stats["kept"] += 1
        return False
    if not bars:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"sym": sym, "name": name, "currency": currency, "bars": []}, f)
        return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sym": sym, "name": name, "currency": currency, "bars": bars}, f)
    return True

def do_symbol(args):
    sym, name, cur, only_empty = args
    safe = sym.replace("/", "_")
    dpath = os.path.join(OUT, safe + ".json")
    mpath = os.path.join(OUT, safe + ".max.json")
    if only_empty and len(existing_bars(dpath)) >= 2:
        return
    d = chart(sym, "1mo" if TOPUP else "2y", "1d")
    bars, meta = to_bars(d)
    bars = with_latest_session(bars, meta)
    ccy = meta.get("currency")
    if TOPUP:
        bars = merge_bars(existing_bars(dpath), bars)
    if write_if_better(dpath, sym, name, ccy or cur, bars):
        with lock:
            stats["daily"] += 1
    elif not bars:
        with lock:
            stats["nodata"] += 1
    if TOPUP:
        with lock:
            stats["sym"] += 1
            if stats["sym"] % 50 == 0:
                print(f"  {stats['sym']} topped up | daily {stats['daily']} kept {stats['kept']}", flush=True)
        return
    time.sleep(0.4)
    m = chart(sym, "max", "1mo")
    mbars, mmeta = to_bars(m)
    mccy = mmeta.get("currency")
    if write_if_better(mpath, sym, name, mccy or cur, mbars):
        with lock:
            stats["max"] += 1
    with lock:
        stats["sym"] += 1
        if stats["sym"] % 25 == 0:
            print(f"  {stats['sym']} symbols | daily {stats['daily']} max {stats['max']} "
                  f"nodata {stats['nodata']} kept {stats['kept']}", flush=True)

def main():
    exs = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "JSE,EGX").split(",")
    workers = 6
    only_empty = "--only-empty" in sys.argv
    if "--workers" in sys.argv:
        workers = int(sys.argv[sys.argv.index("--workers") + 1])
    jobs = []
    seen = set()
    for ex in exs:
        for s in load_listing(ex):
            sym = s.get("sym") or s.get("ticker")
            if sym and sym not in seen:
                seen.add(sym)
                jobs.append((sym, s.get("name", ""), s.get("currency", ""), only_empty))
    print(f"{len(jobs)} symbols across {exs} | workers={workers} only_empty={only_empty}", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(do_symbol, jobs))
    print(f"DONE: daily {stats['daily']} written, max {stats['max']} written, "
          f"{stats['nodata']} no-data, {stats['kept']} kept (fetch was worse)")

if __name__ == "__main__":
    main()
