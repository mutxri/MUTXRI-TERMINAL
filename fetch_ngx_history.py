#!/usr/bin/env python3
"""fetch_ngx_history.py - build REAL NGX OHLC history from the NGX's
official daily price lists (doclib.ngxgroup.com/DownloadsContent).

The NGX publishes 'GAINERS AND PRICE LIST FOR <DATE>.zip' for every
trading day since 2014. Each zip contains PRICES1.pdf + PRICES_LIST2.pdf
with the full daily price list (PCLOSE/OPEN/HIGH/LOW/CLOSE/CHANGE/
%CHANGE/VOLUME/VALUE per security).

This fetches the most recent N days, parses the PDFs, and writes
per-symbol history files: static_data/history/NGX_<SYM>.json
  {bars: [{t: "YYYY-MM-DD", o, h, l, c, v}, ...]}
"""
import urllib.request, zipfile, io, json, os, re, sys, time
import pdfplumber

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

API = "https://doclib.ngxgroup.com/_api/Web/Lists(guid'dd86e37a-4967-478e-a670-e70e6986138f')/Items"
UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json;odata=verbose'}

def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read().decode(errors="replace"))

def find_price_list(date_str):
    """find the GAINERS AND PRICE LIST item for a date (DD-MM-YYYY)"""
    filt = f"substringof('GAINERS%20AND%20PRICE%20LIST%20FOR%20{date_str}',Title)"
    d = get_json(f"{API}?$select=Title,FileLeafRef&$format=json&$filter={filt}")
    for item in d.get("d", {}).get("results", []):
        leaf = item.get("FileLeafRef") or ""
        if leaf.endswith(".zip") and date_str in leaf:
            return leaf
    return None

def download_zip(leaf):
    url = "https://doclib.ngxgroup.com/DownloadsContent/" + leaf.replace(" ", "%20")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=60).read()
    return zipfile.ZipFile(io.BytesIO(data))

def parse_prices(zf, prefix):
    """parse all PRICES pdfs in the zip, return {symbol: {o,h,l,c,v}}"""
    rows = {}
    for name in zf.namelist():
        if not name.lower().endswith(".pdf") or "PRICES" not in name.upper():
            continue
        data = zf.read(name)
        try:
            with pdfplumber.open(io.BytesIO(data)) as doc:
                for page in doc.pages:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        # skip headers
                        if re.match(r"^\d+ [A-Z]{2,}", line) and len(line) > 30:
                            parts = line.split()
                            if len(parts) >= 11:
                                try:
                                    sym = parts[1]
                                    pclose = float(parts[2].replace(",", ""))
                                    o = float(parts[4].replace(",", "")) if parts[4] != "-" else pclose
                                    high = float(parts[5].replace(",", "")) if parts[5] != "-" else pclose
                                    low = float(parts[6].replace(",", "")) if parts[6] != "-" else pclose
                                    close = float(parts[9].replace(",", "")) if parts[9] != "-" else pclose
                                    vol = parts[-2].replace(",", "")
                                    volume = int(vol) if vol.isdigit() else 0
                                    rows[sym] = {"o": o, "h": high, "l": low, "c": close, "v": volume}
                                except (ValueError, IndexError):
                                    continue
        except Exception:
            continue
    return rows

def main():
    # fetch the last N trading days (default 30 = ~6 weeks)
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    import datetime
    dates = []
    d = datetime.date(2026, 8, 28)
    cur = d
    while len(dates) < n_days:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%d-%m-%Y"))
        cur -= datetime.timedelta(days=1)

    all_bars = {}  # sym -> {date: bar}
    fetched = 0
    for i, date_str in enumerate(dates):
        try:
            leaf = find_price_list(date_str)
            if not leaf:
                print(f"  {date_str}: no file")
                continue
            zf = download_zip(leaf)
            rows = parse_prices(zf, "PRICES")
            iso = f"{date_str[6:]}-{date_str[3:5]}-{date_str[0:2]}"
            for sym, bar in rows.items():
                all_bars.setdefault(sym, {})[iso] = bar
            fetched += 1
            print(f"  {date_str}: {len(rows)} securities")
        except Exception as e:
            print(f"  {date_str}: ERR {str(e)[:60]}")
        time.sleep(0.4)

    # write per-symbol files
    saved = 0
    for sym, bars_map in all_bars.items():
        bars = []
        for iso in sorted(bars_map.keys()):
            b = bars_map[iso]
            bars.append({"t": iso, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
        if len(bars) >= 2:
            path = os.path.join(HIST, f"NGX_{sym}.json")
            json.dump({"bars": bars[-1500:]}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            saved += 1
    print(f"\nDONE: {fetched} days fetched, {saved} symbols with >=2 bars saved")

if __name__ == "__main__":
    main()
