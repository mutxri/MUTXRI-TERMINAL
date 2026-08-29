#!/usr/bin/env python3
"""fetch_nse_mystocks.py - pull complete NSE data from live.mystocks.co.ke.

Gets for every NSE stock:
  - pricelist: ticker, price, change%, volume, sector (69 stocks, one fetch)
  - per-stock page: previous, open, average, deals, volume, turnover,
    day range, 52-week range, shares issued, year end, profile blurb

Writes static_data/market_NSE.json (same shape as other exchanges) and
static_data/nse_extra.json (the full per-stock details). Honest: this is
myStocks' public EOD board data - we label it EOD, not real-time.
"""
import json, os, re, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_MARKET = os.path.join(BASE, "static_data", "market_NSE.json")
OUT_EXTRA = os.path.join(BASE, "static_data", "nse_extra.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(errors="replace")

def fetch_pricelist():
    body = get("https://live.mystocks.co.ke/m/pricelist")
    blocks = re.split(r"<h2>([^<]+)</h2>", body)
    rows = []
    for i in range(1, len(blocks) - 1, 2):
        sec = blocks[i].strip()
        content = blocks[i + 1]
        for m in re.finditer(r'stock=([A-Z0-9]+)"[^>]*>([^<]*)</a><br>\s*<td class=n>([^<]*)<td class="n[^"]*">([^<]*)<td class=n>([^<]*)<', content):
            chg = m.group(4)
            chg = chg.replace("&#9650;", "+").replace("&#9660;", "-").replace("&nbsp;", "").strip()
            rows.append({
                "ticker": m.group(1),
                "name": m.group(2).strip(),
                "price": m.group(3).strip(),
                "changePct": chg,
                "volume": m.group(5).strip(),
                "sector": sec,
            })
    return rows

def fetch_stock(tkr):
    """Fetch one stock page and extract the full quote table."""
    try:
        body = get(f"https://live.mystocks.co.ke/m/stock={tkr}")
    except Exception:
        return None
    out = {}
    m = re.search(r"<strong>KES ([0-9.,]+)</strong>\s*&nbsp;\s*([+\-0-9.]+)\s*\(([0-9.]+%)\)", body)
    if m:
        out["price"] = m.group(1)
        out["change"] = m.group(2)
        out["changePct"] = m.group(3)
    m = re.search(r"<div id=mktTime>([^<]+)</div>", body)
    if m:
        out["asOf"] = m.group(1)
    # the shareInfo table
    table = {}
    for m in re.finditer(r"<th>([^<]+):</th><td>([^<]+)</td>", body):
        table[m.group(1).strip()] = m.group(2).strip()
    for m in re.finditer(r"<th>([^<]+):</th>\s*<td>([^<]+)</td>\s*<th>([^<]+):</th>\s*<td>([^<]+)</td>", body, re.S):
        table[m.group(1).strip()] = m.group(2).strip()
        table[m.group(3).strip()] = m.group(4).strip()
    out["info"] = table
    # 52-week
    m = re.search(r"<th>52-week:</th>\s*<td>([^<]+)</td>", body)
    if m:
        out["range52w"] = m.group(1).strip()
    m = re.search(r"<th>Day:</th>\s*<td>([^<]+)</td>", body)
    if m:
        out["dayRange"] = m.group(1).strip()
    # profile first sentence
    m = re.search(r"<h2>Profile</h2>\s*<p>\s*<p>([^<]+)", body)
    if m:
        out["profile"] = m.group(1).strip()
    return out

def main():
    rows = fetch_pricelist()
    print(f"pricelist: {len(rows)} stocks")
    # map existing NSE listing (stocks.json) so we keep the same sym keys
    stocks = json.load(open(os.path.join(BASE, "stocks.json"), encoding="utf-8"))["stocks"]
    nse_listing = stocks.get("NSE", [])
    tkr2sym = {}
    for s in nse_listing:
        tkr2sym[(s.get("ticker") or "").upper()] = s.get("sym") or s.get("ticker")

    market = {"stocks": [], "asOf": "mystocks EOD"}
    extra = {}
    for i, r in enumerate(rows):
        tkr = r["ticker"]
        sym = tkr2sym.get(tkr, tkr)
        det = fetch_stock(tkr)
        if det:
            extra[sym] = det
        market["stocks"].append({
            "ticker": tkr, "sym": sym,
            "name": r["name"], "sector": r["sector"],
            "price": float(r["price"].replace(",", "")) if r["price"].replace(",", "").replace(".", "").isdigit() else None,
            "chgPct": r["changePct"],
            "volume": r["volume"],
            "currency": "KES", "country": "Kenya",
            "source": "live.mystocks.co.ke (EOD)",
        })
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(rows)}", flush=True)
        time.sleep(0.4)

    json.dump(market, open(OUT_MARKET, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(extra, open(OUT_EXTRA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DONE: {len(rows)} stocks -> market_NSE.json + nse_extra.json")

if __name__ == "__main__":
    main()
