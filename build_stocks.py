#!/usr/bin/env python3
"""Build stocks.json — full listings for JSE, EGX, NGX, NSE.
JSE/EGX: live-capable symbol lists (Yahoo). NGX/NSE: EOD from African Financials.
Run: python build_stocks.py  → writes stocks.json
"""
import json, re, html, urllib.request, time

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}

def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def to_float(s):
    try:
        return float(str(s).replace(",", "").replace("%", "").strip() or 0)
    except ValueError:
        return 0.0

def parse_af_table(page):
    """Parse African Financials share-price table: name, price, chg%, sector, date."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)
    out = []
    for r in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if len(cells) >= 8 and cells[0] not in ("Company", ""):
            out.append({
                "name": cells[0], "price": to_float(cells[1]), "chgPct": to_float(cells[2]),
                "value": cells[3], "volume": cells[4], "ytd": cells[5],
                "sector": cells[6], "date": cells[7],
            })
    return out

def fetch_twelve(exchange):
    d = json.loads(get(f"https://api.twelvedata.com/stocks?exchange={exchange}"))["data"]
    return d

def build():
    stocks = {"JSE": [], "EGX": [], "NGX": [], "NSE": []}

    # ---- JSE (South Africa) — live via Yahoo .JO ----
    print("fetching JSE list…")
    jse = fetch_twelve("XJSE")
    seen = set()
    for x in jse:
        if x.get("type") != "Common Stock": continue
        s = x["symbol"]
        if s in seen: continue
        seen.add(s)
        stocks["JSE"].append({"sym": s + ".JO", "code": s, "name": x["name"],
                              "currency": "ZAc", "country": "South Africa"})
    print(f"  JSE: {len(stocks['JSE'])} common stocks")

    # ---- EGX (Egypt) — live via Yahoo ISIN.CA ----
    print("fetching EGX list…")
    egx = fetch_twelve("XCAI")
    seen = set()
    for x in egx:
        s = x["symbol"]
        if s in seen: continue
        seen.add(s)
        stocks["EGX"].append({"sym": s + ".CA", "code": s, "name": x["name"],
                              "currency": "EGP", "country": "Egypt"})
    print(f"  EGX: {len(stocks['EGX'])} stocks")

    # ---- NGX (Nigeria) — EOD from African Financials ----
    print("fetching NGX table…")
    ng = parse_af_table(get("https://africanfinancials.com/nigerian-stock-exchange-share-prices/"))
    for r in ng:
        stocks["NGX"].append({"name": r["name"], "price": r["price"], "chgPct": r["chgPct"],
                              "value": r["value"], "volume": r["volume"], "ytd": r["ytd"],
                              "sector": r["sector"], "date": r["date"],
                              "currency": "NGN", "country": "Nigeria"})
    print(f"  NGX: {len(stocks['NGX'])} stocks (EOD {ng[0]['date'] if ng else '?'})")

    # ---- NSE (Kenya) — EOD from African Financials ----
    print("fetching NSE table…")
    nse = parse_af_table(get("https://africanfinancials.com/nairobi-securities-exchange-kenya-share-prices/"))
    for r in nse:
        stocks["NSE"].append({"name": r["name"], "price": r["price"], "chgPct": r["chgPct"],
                              "value": r["value"], "volume": r["volume"], "ytd": r["ytd"],
                              "sector": r["sector"], "date": r["date"],
                              "currency": "KES", "country": "Kenya"})
    print(f"  NSE: {len(stocks['NSE'])} stocks (EOD {nse[0]['date'] if nse else '?'})")

    meta = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "note": "JSE/EGX = live via Yahoo chart API. NGX/NSE = end-of-day from African Financials."}
    with open("stocks.json", "w") as f:
        json.dump({"meta": meta, "stocks": stocks}, f, indent=1)
    print("wrote stocks.json")

if __name__ == "__main__":
    build()
