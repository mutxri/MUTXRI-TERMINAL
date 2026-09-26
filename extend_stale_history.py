#!/usr/bin/env python3
"""extend_stale_history.py - bring the tail of stale candlestick series up to date.

Some series carry a live price (the security still trades) but their candles stop
weeks or months back, so the chart shows a stale last bar. This tops those up from
Yahoo's daily bars.

SAFETY - the standing guard is that deeper existing history is never clobbered by
shallower data:
  * existing bars are never modified, reordered or removed
  * only dates strictly NEWER than the file's current last bar are appended
  * the result is re-sorted by date and de-duplicated
  * every touched file is backed up first

A symbol whose Yahoo name does not look like the listed company is skipped and
reported, never written.

Usage: python3 extend_stale_history.py [--apply]
"""
import glob, json, os, re, shutil, sys, time, urllib.request
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
APPLY = "--apply" in sys.argv
STALE_DAYS = 10
TODAY = datetime.date.today()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def yahoo(sym, rng="3mo"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?range=%s&interval=1d" % (sym, rng))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def parse_bars(d):
    res = (d.get("chart") or {}).get("result") or []
    if not res:
        return [], ""
    r0 = res[0]
    meta = r0.get("meta") or {}
    ts = r0.get("timestamp") or []
    q = (r0.get("indicators") or {}).get("quote") or [{}]
    q0 = q[0] if q else {}
    out = []
    for i, t in enumerate(ts):
        try:
            o = (q0.get("open") or [])[i]
            h = (q0.get("high") or [])[i]
            l = (q0.get("low") or [])[i]
            c = (q0.get("close") or [])[i]
            v = (q0.get("volume") or [])[i]
        except IndexError:
            continue
        if None in (o, h, l, c):
            continue
        day = datetime.datetime.utcfromtimestamp(int(t)).date().isoformat()
        b = {"t": day, "o": float(o), "h": float(h), "l": float(l),
             "c": float(c), "v": float(v or 0)}
        # never write a bar that violates the OHLC contract
        if b["h"] < b["l"] or b["h"] < max(b["o"], b["c"]) - 1e-9 \
           or b["l"] > min(b["o"], b["c"]) + 1e-9:
            continue
        out.append(b)
    return sorted(out, key=lambda x: x["t"]), (meta.get("shortName") or meta.get("longName") or "")


def listing_names():
    st = json.load(open(os.path.join(BASE, "stocks.json"), encoding="utf-8"))["stocks"]
    n = {}
    for ex in st:
        for r in st[ex]:
            if r.get("sym"):
                n[r["sym"]] = r.get("name") or ""
    return n


def live_prices():
    p = {}
    for ex in ("JSE", "EGX", "NGX", "NSE"):
        try:
            m = json.load(open(os.path.join(BASE, "static_data", "market_%s.json" % ex),
                               encoding="utf-8"))
        except Exception:
            continue
        rows = m if isinstance(m, list) else (m.get("rows") or m.get("stocks") or [])
        for r in rows:
            k = r.get("sym") or r.get("symbol")
            if k:
                p[k] = r.get("price")
    return p


def name_ok(listed, yname):
    """Prove the Yahoo series is the SAME company before trusting it.

    Yahoo returns a bare fund code as the name for some instruments (e.g.
    "MEGM.CA,0P0000I02F,0" or "NDRL.CA,0P0000JDRD,0"). That identifies nothing,
    so such a symbol is skipped rather than written. A real company or fund name
    that merely happens to contain a comma ("Std Bank Group 6,5%Pref") is fine.
    """
    y = (yname or "").strip()
    if not y:
        return False
    if re.match(r"^[A-Z0-9]{2,}\.[A-Z]{2},", y):
        return False
    if sum(ch.isalpha() for ch in y) < 4:
        return False
    words = [w for w in (listed or "").lower().replace(".", " ").split()
             if len(w) > 3 and w not in ("limited", "holdings", "group", "company",
                                         "ltd", "plc", "inc", "corporation")]
    if not words:
        return True
    return any(w[:5] in y.lower() for w in words)


def main():
    names = listing_names()
    prices = live_prices()
    targets = []
    for f in glob.glob(os.path.join(HIST, "*.json")):
        base = os.path.basename(f)[:-5]
        if base.endswith(".max"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        bars = d.get("bars") or []
        if not bars:
            continue
        last = str(bars[-1].get("t"))[:10]
        try:
            dt = datetime.date(*map(int, last.split("-")))
        except Exception:
            continue
        if (TODAY - dt).days <= STALE_DAYS:
            continue
        if prices.get(base) in (None, "", 0):
            continue                       # delisted: nothing to extend
        targets.append((base, f, last, len(bars)))

    print("stale-but-still-priced series: %d" % len(targets))
    appended = 0
    skipped = []
    bak = os.path.join(BASE, "static_data",
                       "_bak_stale_extend_%s"
                       % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    for base, f, last, nbars in sorted(targets, key=lambda x: x[2]):
        try:
            d = yahoo(base)
            fresh, yname = parse_bars(d)
        except Exception as e:
            skipped.append((base, "fetch: " + str(e)[:38]))
            time.sleep(0.6)
            continue
        time.sleep(0.6)
        if not fresh:
            skipped.append((base, "no bars at source"))
            continue
        if not name_ok(names.get(base, ""), yname):
            skipped.append((base, "name unverified (%s)" % (yname or "none")[:34]))
            continue
        cur = json.load(open(f, encoding="utf-8"))
        have = {str(b.get("t"))[:10] for b in cur["bars"]}
        add = [b for b in fresh if b["t"] > last and b["t"] not in have]
        if not add:
            skipped.append((base, "already current"))
            continue
        cur["bars"] = sorted(cur["bars"] + add, key=lambda b: str(b.get("t")))
        appended += 1
        print("  + %-16s %s -> %s  (+%d bars)" % (base, last, add[-1]["t"], len(add)))
        if APPLY:
            os.makedirs(bak, exist_ok=True)
            shutil.copy(f, bak)
            json.dump(cur, open(f, "w", encoding="utf-8"), ensure_ascii=False)

    print()
    print("extended: %d" % appended)
    print("skipped : %d" % len(skipped))
    for b, why in skipped[:20]:
        print("   %-18s %s" % (b, why))
    print("dry run" if not APPLY else "APPLIED (originals backed up)")


if __name__ == "__main__":
    main()
