#!/usr/bin/env python3
"""fix_ngx_oddlot.py - rebuild ASSOCIATED + RONCHESS NGX history from the
PRICES_LIST2 odd-lot rows using the CORRECT column mapping:
  S/N NAME... MARKET_CAP PRICE %CHG TRADES VOLUME  -> price = nums[1]
(previous attempts took the market cap as price: ASSOCIATED 12,561 vs 5.25,
 RONCHESS 7,371 vs 81.00)
"""
import json, os, datetime, urllib.request, zipfile, io, pdfplumber, re, time

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")

def parse_prices2(zf):
    rows = {}
    for name in zf.namelist():
        if "PRICES_LIST2" not in name.upper() or not name.endswith(".pdf"):
            continue
        with pdfplumber.open(io.BytesIO(zf.read(name))) as doc:
            for page in doc.pages:
                for line in (page.extract_text() or "").split("\n"):
                    parts = line.split()
                    if not re.match(r"^\d+ ", line):
                        continue
                    nums = []
                    for p in parts[1:]:
                        clean = p.replace(",", "").replace("(", "").replace(")", "")
                        try:
                            nums.append(float(clean))
                        except ValueError:
                            nums.append(None)
                    nums = [v for v in nums if v is not None]
                    if len(nums) >= 4:
                        mktcap, price = nums[0], nums[1]
                        if price != mktcap and 0 < price < 50000:
                            nl = " ".join(parts[1:-3]).lower()
                            sym = None
                            if "associated" in nl: sym = "ASSOCIATED"
                            elif "ronchess" in nl: sym = "RONCHESS"
                            if sym:
                                vol = parts[-1].replace(",", "")
                                volume = int(vol) if vol.isdigit() else 0
                                rows[sym] = {"o": price, "h": price, "l": price, "c": price, "v": volume}
    return rows

def main():
    dates = []
    cur = datetime.date(2026, 8, 28)
    while len(dates) < 45:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%d-%m-%Y"))
        cur -= datetime.timedelta(days=1)
    data = {"ASSOCIATED": {}, "RONCHESS": {}}
    for ds in dates:
        url = f"https://doclib.ngxgroup.com/DownloadsContent/GAINERS%20AND%20PRICE%20LIST%20FOR%20{ds}.zip"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            raw = urllib.request.urlopen(req, timeout=40).read()
            zf = zipfile.ZipFile(io.BytesIO(raw))
            rows = parse_prices2(zf)
            iso = f"{ds[6:]}-{ds[3:5]}-{ds[0:2]}"
            for s in data:
                if s in rows:
                    data[s][iso] = rows[s]
        except Exception:
            pass
        time.sleep(0.3)
    for s in data:
        bars = [{"t": k, "o": v["o"], "h": v["h"], "l": v["l"], "c": v["c"], "v": v["v"]}
                for k, v in sorted(data[s].items())]
        if bars:
            json.dump({"bars": bars}, open(os.path.join(HIST, f"NGX_{s}.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(f"NGX_{s}.json: {len(bars)} bars, last C={bars[-1]['c']}", flush=True)
        else:
            print(f"NGX_{s}.json: NO DATA", flush=True)

if __name__ == "__main__":
    main()
