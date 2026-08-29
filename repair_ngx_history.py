#!/usr/bin/env python3
"""repair_ngx_history.py - fix NGX history files whose prices were corrupted
by a misparse that read the MARKET CAP column as the close price.

Background: a background refetch of the NGX official price-list zips read
PRICES_LIST2 rows (S/N NAME MARKET_CAP PRICE %CHG TRADES VOLUME) and took
MARKET_CAP (77,719.72 for ETERNA) instead of PRICE (35.55). Those wrong
values went into both history/NX_*.json and market_NGX.json and were
deployed live. This script rebuilds the affected per-symbol history files
from the official zips using the CORRECT column mapping:
  PRICES1:   S/N SYM PCLOSE OOPEN OPEN HIGH LOW %SPREAD OCLOSE CLOSE CHANGE %CHANGE TRADES VOLUME VALUE
             -> close = parts[9], open = parts[4], high = parts[5], low = parts[6]
  PRICES_LIST2 premium/odd-lot: S/N NAME MARKET_CAP PRICE %CHG TRADES VOLUME
             -> price = the value whose NEXT value is the signed %chg (|x|<100)
"""
import urllib.request, zipfile, io, json, os, re, sys, time, datetime
import pdfplumber

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")

UA = {'User-Agent': 'Mozilla/5.0'}
API = "https://doclib.ngxgroup.com/_api/Web/Lists(guid'dd86e37a-4967-478e-a670-e70e6986138f')/Items"

def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={**UA, 'Accept': 'application/json;odata=verbose'})
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read().decode(errors="replace"))

def find_price_list(date_str):
    filt = f"substringof('GAINERS%20AND%20PRICE%20LIST%20FOR%20{date_str}',Title)"
    d = get_json(f"{API}?$select=Title,FileLeafRef&$format=json&$filter={filt}")
    for item in d.get("d", {}).get("results", []):
        leaf = item.get("FileLeafRef") or ""
        if leaf.endswith(".zip") and date_str in leaf:
            return leaf
    return None

def download_zip(leaf):
    url = "https://doclib.ngxgroup.com/DownloadsContent/" + leaf.replace(" ", "%20")
    req = urllib.request.Request(url, headers=UA)
    data = urllib.request.urlopen(req, timeout=60).read()
    return zipfile.ZipFile(io.BytesIO(data))

def parse_prices(zf):
    """Correct parser: PRICES1 full-OHLC + PRICES_LIST2 (price = before %chg)."""
    rows = {}
    for name in zf.namelist():
        if not name.lower().endswith(".pdf") or "PRICES" not in name.upper():
            continue
        try:
            with pdfplumber.open(io.BytesIO(zf.read(name))) as doc:
                for page in doc.pages:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        if not re.match(r"^\d+ ", line):
                            continue
                        parts = line.split()
                        try:
                            if len(parts) >= 14 and re.match(r"^[A-Z][A-Z0-9&]{2,}$", parts[1]):
                                sym = parts[1]
                                pclose = float(parts[2].replace(",", ""))
                                o = float(parts[4].replace(",", "")) if parts[4] != "-" else pclose
                                high = float(parts[5].replace(",", "")) if parts[5] != "-" else pclose
                                low = float(parts[6].replace(",", "")) if parts[6] != "-" else pclose
                                close = float(parts[9].replace(",", "")) if parts[9] != "-" else pclose
                                vol = parts[-2].replace(",", "")
                                volume = int(vol) if vol.isdigit() else 0
                                rows[sym] = {"o": o, "h": high, "l": low, "c": close, "v": volume}
                            else:
                                nums = []
                                for p in parts[1:]:
                                    clean = p.replace(",", "").replace("(", "").replace(")", "")
                                    try:
                                        nums.append(float(clean))
                                    except ValueError:
                                        nums.append(None)
                                # walk from the end: last two ints are TRADES VOLUME,
                                # before them %CHG (signed), before that PRICE
                                price = None
                                for i in range(len(nums) - 4, -1, -1):
                                    v, nxt = nums[i], (nums[i + 1] if i + 1 < len(nums) else None)
                                    if v is None or v > 50000:
                                        continue
                                    if nxt is not None and abs(nxt) < 100:
                                        price = v
                                        break
                                if price is None:
                                    small = [v for v in nums[:-2] if v is not None and v < 50000]
                                    if small:
                                        price = min(small, key=lambda x: abs(x - 50))
                                sym = None
                                for p in parts[1:]:
                                    if re.match(r"^[A-Z][A-Z0-9&]{2,}$", p) and len(p) >= 3:
                                        sym = p
                                        break
                                if sym is None:
                                    words = [p for p in parts[1:-3] if p.isalpha() and p == p.upper()]
                                    if words:
                                        sym = words[-1][:8]
                                if sym and price:
                                    vol = parts[-1].replace(",", "")
                                    volume = int(vol) if vol.isdigit() else 0
                                    rows[sym] = {"o": price, "h": price, "l": price, "c": price, "v": volume}
                        except (ValueError, IndexError):
                            continue
        except Exception:
            continue
    return rows

def main():
    # rebuild last N trading days (default 45 = ~2 months)
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    dates = []
    cur = datetime.date(2026, 8, 28)
    while len(dates) < n_days:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%d-%m-%Y"))
        cur -= datetime.timedelta(days=1)

    all_bars = {}
    fetched = 0
    for date_str in dates:
        try:
            leaf = find_price_list(date_str)
            if not leaf:
                continue
            zf = download_zip(leaf)
            rows = parse_prices(zf)
            iso = f"{date_str[6:]}-{date_str[3:5]}-{date_str[0:2]}"
            for sym, bar in rows.items():
                all_bars.setdefault(sym, {})[iso] = bar
            fetched += 1
        except Exception as e:
            print(f"  {date_str}: ERR {str(e)[:60]}")
        time.sleep(0.4)

    saved = 0
    for sym, bars_map in all_bars.items():
        bars = []
        for iso in sorted(bars_map.keys()):
            b = bars_map[iso]
            bars.append({"t": iso, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
        if len(bars) >= 2:
            # merge with existing good bars (keep older history if present and sane)
            path = os.path.join(HIST, f"NGX_{sym}.json")
            existing = []
            if os.path.exists(path):
                try:
                    existing = json.load(open(path, encoding="utf-8")).get("bars", [])
                except Exception:
                    existing = []
            merged = {b["t"]: b for b in existing if b["c"] < 50000}  # drop corrupt
            for b in bars:
                merged[b["t"]] = b
            final = [merged[k] for k in sorted(merged.keys())]
            json.dump({"bars": final[-1500:]}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            saved += 1
    print(f"DONE: {fetched} days, {saved} symbols rebuilt")

if __name__ == "__main__":
    main()
