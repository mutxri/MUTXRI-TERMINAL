#!/usr/bin/env python3
"""enrich_investor.py - fill the blank investor-sheet fields from data we
already hold (no fabrication). Computes and writes into each market_<EX>.json:

  open        last history bar open (display currency)
  prevClose   second-to-last history bar close (display currency)
  range52w    "low - high" from the 52-week high/low already in the record
  turnover    volume x price (main currency, compact)
  marketCap   from financials_index (authoritative, main currency) or price x shares
  yearEnd     fiscal year from the income statement asOf
  exchange    the exchange code (JSE/NGX/NSE/EGX)

JSE stores prices in ZAc (cents): money fields are converted to ZAR (x0.01).
EGX/NGX/NSE prices are in the main unit already.
"""
import json, os

SD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data")
HIST = os.path.join(SD, "history")
FIN = os.path.join(SD, "financials")

# load financials_index (authoritative marketCap + exchange, main currency)
fi = json.load(open(os.path.join(SD, "financials_index.json"), encoding="utf-8"))

# load fiscal year-end from income files: sym -> asOf
year_end = {}
for f in os.listdir(FIN):
    if f.endswith("__income.json"):
        sym = f[:-len("__income.json")]
        try:
            d = json.load(open(os.path.join(FIN, f), encoding="utf-8"))
            a = d.get("asOf")
            if a:
                year_end[sym] = str(a)  # "2026", "HY 2026", "Q1 2027"
        except Exception:
            pass

def money(n):
    """compact money formatter: 517_000_000_000 -> '517B'"""
    if n is None:
        return ""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if not n or abs(n) < 1:
        return "" if n == 0 else str(round(n, 2))
    a = abs(n)
    if a >= 1e12:
        v = n / 1e12
        return (f"{v:.2f}".rstrip("0").rstrip(".") + "T")
    if a >= 1e9:
        v = n / 1e9
        return (f"{v:.2f}".rstrip("0").rstrip(".") + "B")
    if a >= 1e6:
        v = n / 1e6
        return (f"{v:.2f}".rstrip("0").rstrip(".") + "M")
    return f"{n:,.0f}"

def fmt_num(n):
    if n is None:
        return ""
    try:
        return f"{float(n):,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""

def load_bars(sym):
    """return [bars] for a security's history file, or []."""
    for cand in [f"{sym}.json", f"{sym}", f"{sym}.CA.json"]:
        p = os.path.join(HIST, cand)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                return d.get("bars") or []
            except Exception:
                return []
    return []

def hist_path_for(ex, sym, ticker):
    """resolve the history filename per exchange naming convention."""
    if ex == "JSE":
        return f"{sym}.json" if os.path.exists(os.path.join(HIST, f"{sym}.json")) else None
    if ex == "EGX":
        # sym IS the ISIN (EGS...CA) OR a short ticker .CA
        for cand in [f"{sym}.json", f"{sym}", f"{ticker}.CA.json"]:
            if cand and os.path.exists(os.path.join(HIST, cand)):
                return cand
        # fallback: search by sym in filename
        for f in os.listdir(HIST):
            if f == f"{sym}.json" or f == sym:
                return f
        return None
    if ex == "NGX":
        c = f"NGX_{ticker}.json"
        return c if os.path.exists(os.path.join(HIST, c)) else None
    if ex == "NSE":
        c = f"NSE_{ticker}.json"
        return c if os.path.exists(os.path.join(HIST, c)) else None
    return None

def enrich(ex):
    mp = os.path.join(SD, f"market_{ex}.json")
    m = json.load(open(mp, encoding="utf-8"))
    factor = 0.01 if ex == "JSE" else 1.0  # JSE prices are cents
    filled = {"open": 0, "prevClose": 0, "range52w": 0, "turnover": 0,
              "marketCap": 0, "yearEnd": 0, "exchange": 0}
    for s in m["stocks"]:
        sym = s.get("sym")
        ticker = s.get("ticker") or s.get("sym")
        price = s.get("price")
        volume = s.get("volume")
        shares = s.get("sharesIssued") or s.get("sharesOutstanding")

        # exchange
        s["exchange"] = ex
        filled["exchange"] += 1

        # range52w from w52Low/w52High
        lo, hi = s.get("w52Low"), s.get("w52High")
        if lo is not None and hi is not None:
            s["range52w"] = f"{fmt_num(lo)} - {fmt_num(hi)}"
            filled["range52w"] += 1

        # marketCap: financials_index (authoritative) else price x shares
        fi_rec = fi.get(sym) or fi.get(ticker) or fi.get(sym.split(".")[0])
        if fi_rec and fi_rec.get("marketCap"):
            s["marketCap"] = money(fi_rec["marketCap"])
            filled["marketCap"] += 1
        elif price is not None and shares:
            try:
                s["marketCap"] = money(float(price) * float(shares) * factor)
                filled["marketCap"] += 1
            except (TypeError, ValueError):
                pass

        # turnover = volume x price (main currency)
        if volume is not None and price is not None:
            try:
                s["turnover"] = money(float(volume) * float(price) * factor)
                filled["turnover"] += 1
            except (TypeError, ValueError):
                pass

        # open / prevClose from history
        hf = hist_path_for(ex, sym, ticker)
        if hf:
            d = json.load(open(os.path.join(HIST, hf), encoding="utf-8"))
            bars = d.get("bars") or []
            if bars:
                s["open"] = fmt_num(bars[-1].get("o"))
                filled["open"] += 1
            if len(bars) >= 2:
                s["prevClose"] = fmt_num(bars[-2].get("c"))
                filled["prevClose"] += 1

        # yearEnd from income asOf
        ye = year_end.get(sym) or year_end.get(ticker)
        if ye:
            s["yearEnd"] = ye
            filled["yearEnd"] += 1

    json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
    n = len(m["stocks"])
    print(f"{ex}: {n} securities | " + " | ".join(f"{k}={v}" for k, v in filled.items()))

for ex in ["JSE", "EGX", "NGX", "NSE"]:
    enrich(ex)
print("done")
