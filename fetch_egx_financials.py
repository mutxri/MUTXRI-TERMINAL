#!/usr/bin/env python3
"""fetch_egx_financials.py - fetch financial statements for EGX securities
using the TICKER.CA format (NOT the EGS code - Yahoo doesn't recognize it).
Slow pace, targeted at the liquid/major names. Writes into
static_data/yahoo_financials.json."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data", "yahoo_financials.json")
STOCKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stocks.json")

def df_to_dict(df):
    out = {}
    if df is None or df.empty:
        return out
    try:
        for col in df.columns:
            yr = str(col.year) if hasattr(col, "year") else str(col)
            vals = {}
            for idx in df.index:
                v = df.loc[idx, col]
                if v is not None and v == v and v != 0:  # not None/NaN/zero
                    try:
                        vals[str(idx)] = float(v)
                    except Exception:
                        pass
            if vals:
                out[yr] = vals
    except Exception:
        pass
    return out

def fetch_statements(sym):
    import yfinance as yf
    t = yf.Ticker(sym)
    inc = df_to_dict(t.income_stmt)
    bal = df_to_dict(t.balance_sheet)
    cf = df_to_dict(t.cashflow)
    meta = {}
    try:
        info = t.get_info()
        meta = {"name": info.get("longName") or info.get("shortName"),
                "currency": info.get("financialCurrency"),
                "marketCap": info.get("marketCap"),
                "sharesOutstanding": info.get("sharesOutstanding")}
    except Exception:
        pass
    return inc, bal, cf, meta

def main():
    existing = {}
    if os.path.exists(OUT):
        existing = json.load(open(OUT, encoding="utf-8"))
    stocks = json.load(open(STOCKS, encoding="utf-8"))["stocks"]
    egx = stocks.get("EGX", [])
    done = fail = skip = 0
    for i, s in enumerate(egx):
        sym = s.get("sym")
        tkr = (s.get("ticker") or "").strip().upper()
        if not sym or not tkr:
            continue
        if sym in existing:
            skip += 1
            continue
        ysym = tkr + ".CA"
        try:
            inc, bal, cf, meta = fetch_statements(ysym)
            if inc or bal or cf:
                existing[sym] = {
                    "name": meta.get("name") or s.get("name"),
                    "currency": meta.get("currency"),
                    "marketCap": meta.get("marketCap"),
                    "sharesOutstanding": meta.get("sharesOutstanding"),
                    "income": inc, "balance": bal, "cashflow": cf,
                    "source": "Yahoo Finance (yfinance)",
                }
                done += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        if (i + 1) % 5 == 0:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False)
            print(f"  {i+1}/{len(egx)} (done {done}, fail {fail}, skip {skip})", flush=True)
        time.sleep(2.8)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    print(f"DONE: {done} fetched, {fail} no-data, {skip} existing")

if __name__ == "__main__":
    main()
