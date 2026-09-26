#!/usr/bin/env python3
"""Repair OHLC-inconsistent candlestick bars.

Two defects show up in the history files:
  1. NSE bars where the source printed open/close but high/low = 0 (missing).
     Fix: high = max(open, close), low = min(open, close).
  2. JSE/EGX bars where high/low were read from a neighbouring bar and no
     longer bracket open/close. Fix: high = max(open, high, close),
     low = min(open, low, close).

Never touches open/close, never invents a value outside the existing four.
Usage: python3 repair_candles.py [--apply]
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
APPLY = "--apply" in sys.argv

total_fixed = 0
files_fixed = 0

for f in sorted(os.listdir(HIST)):
    if not f.endswith(".json") or f.endswith(".max.json"):
        continue
    p = os.path.join(HIST, f)
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    bars = d.get("bars") or d.get("candles") or d.get("data") or (d if isinstance(d, list) else [])
    if not isinstance(bars, list):
        continue
    file_changed = 0
    for b in bars:
        if not isinstance(b, dict):
            continue
        o = b.get("o", b.get("open"))
        c = b.get("c", b.get("close"))
        if o is None or c is None:
            continue
        try:
            o, c = float(o), float(c)
        except (TypeError, ValueError):
            continue
        h = b.get("h", b.get("high"))
        l = b.get("l", b.get("low"))
        if h is None or l is None:
            nh, nl = max(o, c), min(o, c)
        else:
            try:
                h, l = float(h), float(l)
            except (TypeError, ValueError):
                nh, nl = max(o, c), min(o, c)
            else:
                nh = max(o, c) if h == 0 else max(o, h, c)
                nl = min(o, c) if l == 0 else min(o, l, c)
        if nh == h and nl == l:
            continue
        for hk in ("h", "high"):
            if hk in b:
                b[hk] = nh
                break
        for lk in ("l", "low"):
            if lk in b:
                b[lk] = nl
                break
        file_changed += 1
    if file_changed:
        files_fixed += 1
        total_fixed += file_changed
        if APPLY:
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)

print("files repaired: %d" % files_fixed)
print("bars repaired:  %d" % total_fixed)
print("dry run" if not APPLY else "APPLIED")
