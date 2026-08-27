#!/usr/bin/env python3
"""build_company_info.py - build company_info.json for the Market panel.
Merges fundamentals (NGX/NSE: founded, description, dividends, statements),
ownership (all exchanges: shareholders) and listing data into one lookup:
  company_info.json = { sym_or_ticker: {name, sector, industry, country,
    founded, listed, year_end, phone, transfer_secretary, description,
    employees, revenue, dividends, shareholders, source} }
Only REAL data is included; missing fields are absent (frontend shows '—').
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "company_info.json")

def load(name):
    p = os.path.join(BASE, name)
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return {}

def main():
    fund = load("fundamentals.json").get("companies", {})
    own = load("ownership.json")
    stocks_raw = load("stocks.json")
    # stocks.json = {"meta": {...}, "stocks": {"JSE": [...], "EGX": [...], ...}}
    listing = stocks_raw.get("stocks", stocks_raw) if isinstance(stocks_raw, dict) else {}

    out = {}

    # key mapping: fundamentals keys are "NGX:ng-eterna"; listing records have
    # ticker/sym. Build lookup: ticker/sym/name -> info
    def add(key, info):
        out.setdefault(key, {}).update(info)

    # 1. fundamentals (NGX/NSE + any JSE/EGX present)
    for k, c in fund.items():
        ex = k.split(":")[0]
        slug = k.split(":", 1)[-1]
        ticker = (slug.split("-")[-1] if "-" in slug else slug).upper()
        profile = c.get("profile") or {}
        info = {
            "name": c.get("name"),
            "exchange": ex,
            "founded": profile.get("founded"),
            "listed": profile.get("listed"),
            "year_end": profile.get("year_end"),
            "phone": profile.get("phone"),
            "transfer_secretary": profile.get("transfer_secretary"),
            "indices": profile.get("indices"),
            "description": c.get("description"),
            "dividends": c.get("dividends"),
            "highlights": c.get("highlights"),
            "statements": bool((c.get("statements") or {}).get("data")),
            "source": "AfricanFinancials",
        }
        info = {kk: vv for kk, vv in info.items() if vv not in (None, "", [], {})}
        add(k, info)                       # key: NGX:ng-eterna
        add(ticker, info)                  # key: ETERNA
        add(slug, info)                    # key: ng-eterna

    # 2. ownership (shareholders) - keyed by sym like "SOL.JO"
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        d = own.get(ex, {})
        if not isinstance(d, dict):
            continue
        for sym, rec in d.items():
            sh = rec.get("shareholders") if isinstance(rec, dict) else None
            if sh:
                info = {
                    "shareholders": sh,
                    "shareholder_source": rec.get("source") if isinstance(rec, dict) else None,
                }
                info = {kk: vv for kk, vv in info.items() if vv not in (None, "")}
                add(sym, info)
                add(sym.split(".")[0], info)

    # 3. listing sector/currency/name per sym (all exchanges)
    for ex, stocks in listing.items():
        for s in stocks:
            if not isinstance(s, dict):
                continue
            sym = s.get("sym") or s.get("ticker") or s.get("code")
            if not sym:
                continue
            info = {kk: s.get(kk) for kk in ["name", "sector", "currency", "country"]}
            info = {kk: vv for kk, vv in info.items() if vv not in (None, "")}
            if info:
                add(sym, info)
                add((sym.split(".")[0] if isinstance(sym, str) else sym), info)

    # dedupe + save
    for k in list(out.keys()):
        out[k] = {kk: vv for kk, vv in out[k].items() if vv is not None}
        if not out[k]:
            del out[k]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, allow_nan=False, indent=1)
    print(f"company_info.json: {len(out)} lookup keys")

    # coverage stats
    with_shareholders = sum(1 for v in out.values() if v.get("shareholders"))
    with_founded = sum(1 for v in out.values() if v.get("founded"))
    with_desc = sum(1 for v in out.values() if v.get("description"))
    print(f"  with shareholders: {with_shareholders} | founded: {with_founded} | description: {with_desc}")

if __name__ == "__main__":
    main()
