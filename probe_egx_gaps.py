#!/usr/bin/env python3
"""probe_egx_gaps.py - for every EGX security missing a statement, probe Yahoo
Finance (yfinance) to see which are actually fillable. Saves the fillable raw
data to _egx_fill_candidates.json (NOT yet written into the panel files)."""
import json, os, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
OUT = os.path.join(BASE, "_egx_fill_candidates.json")

def load(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None

audit = load(os.path.join(SD, "_gap_audit_full.json")) or {}
egx = audit.get("EGX", {})
need = {x["sym"]: x for x in egx.get("no_statement", [])}
# also the partial gaps: have balance/cashflow but no income, etc.
for typ in ("no_income", "no_balance", "no_cashflow"):
    for x in egx.get(typ, []):
        need.setdefault(x["sym"], x)

listing = load(os.path.join(SD, "listing_EGX.json")) or {}
rows = listing.get("stocks", listing if isinstance(listing, list) else [])
by_sym = {r.get("sym"): r for r in rows}

# already-fetched cache (avoid re-hitting yfinance for symbols we have raw data on)
yfcache = load(os.path.join(SD, "yahoo_financials.json")) or {}

import yfinance as yf

def df2d(df):
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    try:
        for col in df.columns:
            yr = str(col.year) if hasattr(col, "year") else str(col)
            vals = {}
            for idx in df.index:
                v = df.loc[idx, col]
                if v is None or v != v or v == 0:
                    continue
                try: vals[str(idx)] = float(v)
                except Exception: continue
            if vals: out[yr] = vals
    except Exception:
        pass
    return out

results = {}
have = 0
nofit = 0
syms = sorted(need.keys())
print(f"probing {len(syms)} EGX gaps via yfinance...", flush=True)
for i, sym in enumerate(syms, 1):
    row = by_sym.get(sym) or need[sym]
    ticker = (row.get("ticker") or "").strip().upper()
    if not ticker:
        nofit += 1
        results[sym] = {"ticker": "", "found": False, "reason": "no ticker"}
        continue
    # cache hit?
    if sym in yfcache and (yfcache[sym].get("income") or yfcache[sym].get("balance") or yfcache[sym].get("cashflow")):
        results[sym] = {"ticker": ticker, "found": True, "cache": True,
                        "data": yfcache[sym]}
        have += 1
        continue
    try:
        t = yf.Ticker(ticker + ".CA")
        inc = df2d(t.income_stmt)
        bal = df2d(t.balance_sheet)
        cf = df2d(t.cashflow)
    except Exception:
        inc = bal = cf = {}
    if inc or bal or cf:
        results[sym] = {"ticker": ticker, "found": True,
                        "data": {"name": row.get("name"), "sym": sym, "currency": "EGP",
                                 "income": inc, "balance": bal, "cashflow": cf,
                                 "source": "Yahoo Finance (yfinance)"}}
        have += 1
    else:
        results[sym] = {"ticker": ticker, "found": False}
        nofit += 1
    if i % 10 == 0:
        print(f"  {i}/{len(syms)} fillable={have} nofit={nofit}", flush=True)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"DONE: {have} fillable, {nofit} not on Yahoo -> {OUT}", flush=True)
