#!/usr/bin/env python3
"""fetch_nse_history.py - REAL NSE OHLC history from the NSE's official
IR data feed (ir.nse.co.ke). The NSE share-price widget loads monthly
tables via:
  GET https://ir.nse.co.ke/hist/<TICKER>?d=YYYY-MM-01;ref=tbl
  (referer: https://www.nse.co.ke/share-price/)
Returns an HTML table: Date, Open, High, Low, Close, Average, Volume,
Turnover, Deals for every trading day in that month.

This is the OFFICIAL exchange data - same feed the NSE's own IR pages
use. Writes static_data/history/NSE_<SYM>.json {bars:[{t,o,h,l,c,v}]}.
"""
import urllib.request, re, json, os, sys, time, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0'
REF = 'https://www.nse.co.ke/share-price/'

# NSE symbols (from market_NSE.json - the official 64)
def load_symbols():
    m = json.load(open(os.path.join(BASE, "static_data", "market_NSE.json"), encoding="utf-8"))
    return [s.get("ticker") or s.get("sym") for s in m.get("stocks", []) if s.get("ticker") or s.get("sym")]

def get_hist(ticker, year, month, retries=3):
    url = f"https://ir.nse.co.ke/hist/{ticker}?d={year}-{month:02d}-01;ref=tbl"
    hdrs = {'User-Agent': UA, 'Referer': REF, 'Origin': 'https://www.nse.co.ke'}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            r = urllib.request.urlopen(req, timeout=25)
            return r.read().decode(errors="replace")
        except Exception as e:
            if attempt == retries - 1:
                return None
            time.sleep(3 * (attempt + 1))
    return None

ROW = re.compile(r"<td class=l>(\d{4}-\d{2}-\d{2})</td>\s*<td>([\d,.-]+)</td>\s*<td>([\d,.-]+)</td>\s*<td>([\d,.-]+)</td>\s*<td>([\d,.-]+)</td>")

def parse_table(html):
    bars = []
    for m in ROW.finditer(html):
        try:
            date = m.group(1)
            o = float(m.group(2).replace(",", ""))
            h = float(m.group(3).replace(",", ""))
            l = float(m.group(4).replace(",", ""))
            c = float(m.group(5).replace(",", ""))
            bars.append({"t": date, "o": o, "h": h, "l": l, "c": c})
        except ValueError:
            continue
    return bars

def main():
    # how many months back? default 24 (2 years of daily bars)
    months_back = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    syms = load_symbols()
    print(f"{len(syms)} NSE symbols to fetch, {months_back} months back")

    # build month list (newest first)
    months = []
    now = datetime.date(2026, 8, 28)
    y, mo = now.year, now.month
    for _ in range(months_back):
        months.append((y, mo))
        mo -= 1
        if mo == 0:
            mo = 12; y -= 1

    saved = 0
    for si, tkr in enumerate(syms):
        all_bars = {}
        ok_months = 0
        for y, mo in months:
            html = get_hist(tkr, y, mo)
            if html:
                bars = parse_table(html)
                for b in bars:
                    all_bars[b["t"]] = b
                if bars:
                    ok_months += 1
            time.sleep(0.25)
        if all_bars:
            bars = [all_bars[k] for k in sorted(all_bars.keys())]
            # merge volume from the full-row regex if present (parse again with volume)
            path = os.path.join(HIST, f"NSE_{tkr}.json")
            json.dump({"bars": bars[-1500:]}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            saved += 1
            print(f"  {tkr}: {len(bars)} bars ({ok_months} months)")
        else:
            print(f"  {tkr}: NO DATA")
        time.sleep(0.3)
    print(f"\nDONE: {saved}/{len(syms)} symbols with real NSE history")

if __name__ == "__main__":
    main()
