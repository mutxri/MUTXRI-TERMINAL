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

    # Upstream company names that are WRONG for the listed security, usually a
    # foreign company sharing part of the name. Applied at construction because
    # the listing is regenerated from this feed every cycle, so a fix applied to
    # the shipped JSON alone is reverted by the next run.
    EGX_NAME_FIXES = {
        "EGS38161C013": ("Universal for Paper and Packaging Materials (Unipack)", "Paper & Packaging"),
        "EGS38171C012": ("GlaxoSmithKline Egypt S.A.E. (BIOC)", "Pharmaceuticals"),
        "EGS23141C012": ("Creast Mark for Real Estate Investment (CRST)", "Real Estate"),
        "EGS78021C010": ("Egyptian Media Production City (MPRC)", "Real Estate"),
    }

    def normalize_code(code):
        """Strip a stray market suffix from an upstream symbol.

        The upstream feed sometimes returns ISIN-style codes with a market
        suffix attached ("EGS3E071C013.EGP", "EGS48271C018-EGP"). Appending
        ".CA" to one of those produced a symbol like EGS3E071C013.EGP.CA that
        never matched a price, a logo or a CEO, and split its own price history
        across two filenames. Normalise here so it can never be constructed.
        """
        s = str(code).strip()
        for suffix in (".EGP", "-EGP", ".egp", "-egp"):
            if s.endswith(suffix):
                s = s[: -len(suffix)]
        return s

    for x in egx:
        s = normalize_code(x["symbol"])
        if s in seen: continue
        seen.add(s)
        # The upstream feed carries a WRONG company name for some EGX securities,
        # usually a foreign company that shares part of the name: GSK plc for the
        # listed Egyptian entity, "Universal Electronics Inc" for a paper
        # company. The correction must live HERE rather than in the shipped JSON,
        # because the listing is regenerated from this feed every cycle and any
        # fix applied downstream is reverted by the next run.
        nm, sec = EGX_NAME_FIXES.get(s, (x["name"], None))
        row = {"sym": s + ".CA", "code": s, "name": nm,
               "currency": "EGP", "country": "Egypt"}
        if sec: row["sector"] = sec
        stocks["EGX"].append(row)
    print(f"  EGX: {len(stocks['EGX'])} stocks")

    # ---- NGX (Nigeria) — EOD from African Financials ----
    print("fetching NGX table…")
    ng = parse_af_table(get("https://africanfinancials.com/nigerian-stock-exchange-share-prices/"))

    # ---- NGX display names and non-session prices -------------------------------
    # The African Financials NGX table returns the CODE in its name column for a
    # number of listings, so the board printed CNIF, MOFI REIF, SFSREIT and ZICHIS
    # where the issuer has a name. Every name below was read off the Nigerian
    # Exchange own company directory
    # (ngxgroup.com/exchange/data/company-profile?symbol=<CODE>), and the pin lives
    # HERE because stocks.json, listing_<EX> and market_<EX> are all regenerated
    # from this feed, so a fix applied to the shipped JSON alone is reverted.
    NGX_NAME_FIXES = {
        "AVAIF": "AVA Infrastructure Fund",
        "CNIF": "Coronation Infrastructure Fund",
        "SFSREIT": "SFS Real Estate Investment Trust",
        "MOFI REIF": "MOFI Real Estate Investment Fund",
        "MOFIREIF": "MOFI Real Estate Investment Fund",
        "CMFC": "Critical Minerals Financing Corp Plc",
        "CONHALLPLC": "Consolidated Hallmark Holdings Plc",
        "HMCALL": "Haldane McCall Plc",
        "IMG": "Industrial & Medical Gases Nigeria Plc",
        "NCR": "NCR (Nigeria) Plc",
        "NEM": "NEM Insurance Plc",
        "NIDF": "Chapel Hill Denham Nig. Infras Debt Fund",
        "OMATEK": "Omatek Ventures Plc",
        "PRESCO": "Presco Plc",
        "SKYAVN": "Skyway Aviation Handling Company Plc",
        "UHOMREIT": "UH Real Estate Investment Trust",
        "UPDC": "UPDC Plc",
        "ZICHIS": "Zichis Agro Allied Industries Plc"
    }

    # A price the daily official list does not carry. AVA Infrastructure Fund shows
    # 1000000.0 with zero volume and zero value; the NGX price list for 18-09-2026
    # has no AVAIF row at all, and the fund directory entry lists 4,075 million
    # units, which would make that print a N4.08 quadrillion valuation. Withheld so
    # the panel shows the honest empty state instead.
    NGX_NO_SESSION_PRICE = {
        "AVAIF": "no print in the official NGX price list for 18-09-2026; the stored 1000000.0 is not a session price"
    }
    for r in ng:
        _code = str(r["name"]).strip().upper()
        _row = {"name": NGX_NAME_FIXES.get(_code, r["name"]), "price": r["price"], "chgPct": r["chgPct"],
                              "value": r["value"], "volume": r["volume"], "ytd": r["ytd"],
                              "sector": r["sector"], "date": r["date"],
                              "currency": "NGN", "country": "Nigeria"}
        if _code in NGX_NO_SESSION_PRICE:
            _row["price"] = None
            _row["priceNote"] = NGX_NO_SESSION_PRICE[_code]
        stocks["NGX"].append(_row)
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
