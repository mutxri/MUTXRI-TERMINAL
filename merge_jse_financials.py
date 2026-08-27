#!/usr/bin/env python3
"""merge_jse_financials.py - merge the JSE crawl figures into
static_data/financials_all.json (same format as the AF-sourced entries).

Normalizes all units to absolute ZAR: value * mult (Rm=1e6, R'000/R000=1e3).
Keyed by 'JSE:<code>' (e.g. 'JSE:SBK'). Preserves the AF entries.
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
CRAWL = os.path.join(BASE, "jse_financials_data.json")
OUT = os.path.join(BASE, "static_data", "financials_all.json")

# field mapping: crawl key -> financials_all key
FIELD_MAP = {
    "revenue": "revenue",
    "net_interest_income": "net_interest_income",
    "profit_before_tax": "profit_before_tax",
    "profit_after_tax": "profit_after_tax",
    "operating_profit": "operating_profit",
    "total_assets": "total_assets",
    "total_equity": "total_equity",
    "total_liabilities": "total_liabilities",
    "cash_and_equivalents": "cash_and_equivalents",
    "operating_cash_flow": "operating_cash_flow",
    "investing_cash_flow": "investing_cash_flow",
    "financing_cash_flow": "financing_cash_flow",
    "dividends_paid": "dividends_paid",
    "basic_eps": "eps",
}

def main():
    crawl = json.load(open(CRAWL, encoding="utf-8"))
    fa = json.load(open(OUT, encoding="utf-8"))

    merged = 0
    for code, rec in crawl.items():
        figs = rec.get("figures") or {}
        if not figs:
            continue
        data = {}
        for sec, items in figs.items():
            for k, f in items.items():
                target = FIELD_MAP.get(k)
                if not target:
                    continue
                v = f.get("value")
                if v is None:
                    continue
                mult = f.get("mult")
                if not mult:
                    # derive from the unit label
                    unit = (f.get("unit") or "").lower().replace(" ", "")
                    if "rm" == unit or unit == "rm":
                        mult = 1_000_000.0
                    elif "r'000" in unit or "r000" in unit or unit == "r'000":
                        mult = 1_000.0
                    elif "million" in unit:
                        mult = 1_000_000.0
                    elif "billion" in unit:
                        mult = 1_000_000_000.0
                    else:
                        mult = 1.0
                data[target] = v * mult  # absolute ZAR
        if not data:
            continue
        key = f"JSE:{code}"
        fa[key] = {
            "ticker": code,
            "name": (rec.get("name") or code).title(),
            "currency": "ZAR",
            "source": "JSE official AFS (clientportal.jse.co.za)",
            "year": rec.get("year"),
            "data": data,
        }
        merged += 1

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(fa, f, ensure_ascii=False, indent=1)

    print(f"merged {merged} JSE companies into financials_all.json")
    print(f"total entries: {len(fa)}")

    # verify a sample
    for code in ["SBK", "NPN", "CPI"]:
        e = fa.get(f"JSE:{code}")
        if e:
            d = e["data"]
            print(f"  {code}: revenue={d.get('revenue')} assets={d.get('total_assets')} PAT={d.get('profit_after_tax')}")

if __name__ == "__main__":
    main()
