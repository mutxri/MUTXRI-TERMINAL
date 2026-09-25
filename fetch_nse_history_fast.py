#!/usr/bin/env python3
"""fetch_nse_history_fast.py - parallel NSE history fetch from the
official IR feed (ir.nse.co.ke/hist/<TICKER>?d=YYYY-MM-01;ref=tbl).
Only tickers the API serves (verified live): SCOM EQTY EABL ABSA COOP
KPLC NCBA SCBK SBIC IMH KNRE NMG KEGN CIC TCL FMLY AMAC KPC.
Threaded 4x for speed. Writes NSE_<SYM>.json {bars:[{t,o,h,l,c}]}.
"""
import urllib.request, re, json, os, sys, time, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0'
REF = 'https://www.nse.co.ke/share-price/'

SYMS = ["SCOM", "EQTY", "EABL", "ABSA", "COOP", "KPLC", "NCBA", "SCBK", "SBIC",
        "IMH", "KNRE", "NMG", "KEGN", "CIC", "TCL", "FMLY", "AMAC", "KPC",
        "BKG", "BRIT", "KQ", "NSE"]

ROW = re.compile(r"<td class=l>(\d{4}-\d{2}-\d{2})</td>\s*<td>([\d,.-]+)</td>\s*<td>([\d,.-]+)</td>\s*<td>([\d,.-]+)</td>\s*<td>([\d,.-]+)</td>")

def parse_table(html):
    bars = []
    for m in ROW.finditer(html):
        try:
            bars.append({"t": m.group(1),
                         "o": float(m.group(2).replace(",", "")),
                         "h": float(m.group(3).replace(",", "")),
                         "l": float(m.group(4).replace(",", "")),
                         "c": float(m.group(5).replace(",", ""))})
        except ValueError:
            continue
    return bars

def get_month(ticker, y, mo):
    url = f"https://ir.nse.co.ke/hist/{ticker}?d={y}-{mo:02d}-01;ref=tbl"
    hdrs = {'User-Agent': UA, 'Referer': REF, 'Origin': 'https://www.nse.co.ke'}
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            return urllib.request.urlopen(req, timeout=20).read().decode(errors="replace")
        except Exception:
            time.sleep(2)
    return None

def fetch_symbol(ticker, months):
    all_bars = {}
    for y, mo in months:
        html = get_month(ticker, y, mo)
        if html:
            for b in parse_table(html):
                all_bars[b["t"]] = b
        time.sleep(0.15)
    if all_bars:
        # MERGE, never replace. The IR feed carries no volume and only the months
        # requested, and this used to rewrite the whole archive from it - which
        # deleted every older session outside the window and stripped the volume
        # from each day the official board had recorded (append_nse_bars). A day
        # already on disk with volume is the richer official record and is kept;
        # the feed only fills sessions the archive does not have.
        path = os.path.join(HIST, f"NSE_{ticker}.json")
        merged = {}
        try:
            with open(path, encoding="utf-8") as f:
                for b in json.load(f).get("bars", []):
                    if b.get("t"):
                        merged[b["t"]] = b
        except Exception:
            pass
        for day, b in all_bars.items():
            if day in merged and merged[day].get("v") is not None:
                continue
            merged[day] = b
        bars = [merged[k] for k in sorted(merged.keys())]
        json.dump({"bars": bars[-5000:]}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        return ticker, len(bars)
    return ticker, 0

def main():
    months_back = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    months = []
    # Start from the CURRENT month, not a hardcoded one: pinning this to a
    # fixed (year, month) meant the feed was only ever read up to that month
    # and the NSE board silently froze on the last day it covered.
    _today = datetime.date.today()
    y, mo = _today.year, _today.month
    for _ in range(months_back):
        months.append((y, mo))
        mo -= 1
        if mo == 0:
            mo = 12; y -= 1
    print(f"fetching {len(SYMS)} symbols x {len(months)} months (4 threads)", flush=True)
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_symbol, t, months): t for t in SYMS}
        for fut in as_completed(futs):
            tkr, n = fut.result()
            print(f"  {tkr}: {n} bars", flush=True)
            if n: done += 1
    print(f"DONE: {done}/{len(SYMS)} symbols", flush=True)

if __name__ == "__main__":
    main()
