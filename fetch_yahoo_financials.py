#!/usr/bin/env python3
"""fetch_yahoo_financials.py - pull full financial statements (income,
balance, cashflow) from Yahoo Finance via yfinance for every listed security
across JSE/EGX/NGX/NSE. Writes static_data/yahoo_financials.json:
  { "SYM": {"name":..., "currency":..., "income": {year: {row: val}},
            "balance": {...}, "cashflow": {...}, "source": "Yahoo Finance"} }

Resumes (skips symbols already fetched). ~2.5s per security (3 statement
calls) - 1026 securities ≈ 45 min. Run in background.
"""
import json, os, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "yahoo_financials.json")
STOCKS = os.path.join(BASE, "stocks.json")

# map our syms to Yahoo tickers
def yahoo_sym(ex, sym, ticker):
    if ex == "JSE":
        return sym if sym.endswith(".JO") else (sym + ".JO")
    if ex == "EGX":
        # CRITICAL: EGX sym is the EGS code (EGS60121C018.CA) which Yahoo does
        # NOT recognize - use the ticker (COMI) + .CA instead
        tkr = (ticker or "").strip().upper()
        if tkr:
            return tkr + ".CA"
        return None
    if ex == "NGX":
        return None  # Yahoo has no NGX coverage (verified)
    if ex == "NSE":
        return None  # Yahoo has no NSE coverage (verified)
    return None

def df_to_dict(df):
    """DataFrame (rows=statements, cols=years) -> {year: {row: val}}"""
    out = {}
    if df is None or df.empty:
        return out
    for col in df.columns:
        year = str(col.year) if hasattr(col, "year") else str(col)
        d = {}
        for row, val in df[col].items():
            if val is not None and val == val:  # not NaN
                try:
                    d[str(row)] = float(val)
                except Exception:
                    pass
        out[year] = d
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
        meta = {
            "name": info.get("longName") or info.get("shortName"),
            "currency": info.get("financialCurrency") or info.get("currency"),
            "marketCap": info.get("marketCap"),
            "sharesOutstanding": info.get("sharesOutstanding"),
        }
    except Exception:
        pass
    return inc, bal, cf, meta

def load_symbols():
    with open(STOCKS, encoding="utf-8") as f:
        stocks = json.load(f)["stocks"]
    out = []
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        for s in stocks.get(ex, []):
            sym = s.get("sym") or s.get("ticker")
            tkr = s.get("ticker")
            ys = yahoo_sym(ex, sym, tkr)
            if ys:
                out.append((sym, ys, s.get("name")))
    return out

def main():
    existing = {}
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            existing = {}
    targets = load_symbols()
    retry = "--retry" in sys.argv
    # --retry: slow pace (3s) + treat "Quote not found" 404 as transient
    # (Yahoo returns fake 404s when throttled - COMI/ETEL verified fetchable)
    pace = 3.0 if retry else 0.4
    print(f"targets: {len(targets)} (Yahoo-covered), existing: {len(existing)}, retry={retry}")
    done = fail = skip = 0
    for i, (sym, ys, name) in enumerate(targets):
        if sym in existing:
            skip += 1
            continue
        got = False
        if retry:
            # up to 3 attempts: EMPTY result on attempt 1 is likely throttle
            # (fake 404 -> empty df), real no-data stays empty across retries
            for attempt in range(3):
                try:
                    inc, bal, cf, meta = fetch_statements(ys)
                    if inc or bal or cf:
                        existing[sym] = {
                            "name": meta.get("name") or name,
                            "currency": meta.get("currency"),
                            "marketCap": meta.get("marketCap"),
                            "sharesOutstanding": meta.get("sharesOutstanding"),
                            "income": inc, "balance": bal, "cashflow": cf,
                            "source": "Yahoo Finance (yfinance)",
                        }
                        done += 1
                        got = True
                        break
                    # empty on attempts 0-1: could be throttle - backoff + retry
                    if attempt < 2:
                        time.sleep(5 + attempt * 5)
                        continue
                    break  # 3 empty results = genuinely no data
                except Exception:
                    time.sleep(4 + attempt * 4)  # backoff, then retry
            if not got:
                fail += 1
        else:
            try:
                inc, bal, cf, meta = fetch_statements(ys)
                if inc or bal or cf:
                    existing[sym] = {
                        "name": meta.get("name") or name,
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
            print(f"  {i+1}/{len(targets)} (done {done}, fail {fail}, skip {skip})", flush=True)
        time.sleep(pace)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    print(f"DONE: {done} fetched, {fail} no-data, {skip} existing")

if __name__ == "__main__":
    main()
