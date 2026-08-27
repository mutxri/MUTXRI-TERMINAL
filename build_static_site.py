#!/usr/bin/env python3
"""build_static_site.py - snapshot the terminal's data into static JSON for
GitHub Pages deployment. The live app is server-backed (/api/*); this generates
flat files the static build fetches instead."""
import json, os, sys, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data")
os.makedirs(OUT, exist_ok=True)

def fetch(ep, timeout=40):
    req = urllib.request.Request("http://127.0.0.1:8081/" + ep, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def save(name, obj):
    # strict JSON (no NaN) so the browser can parse it
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, allow_nan=False)
    print(f"  {name}: {len(json.dumps(obj))} bytes")

print("Snapshotting terminal data to static_data/ ...")

# 1. listings per exchange
for ex in ["JSE", "EGX", "NGX", "NSE"]:
    try:
        d = fetch(f"api/listing?exchange={ex}")
        save(f"listing_{ex}.json", d)
    except Exception as e:
        print(f"  listing_{ex}: FAIL {str(e)[:50]}")

# 2. heatmaps per exchange
for ex in ["JSE", "EGX", "NGX", "NSE"]:
    try:
        d = fetch(f"api/heatmap?exchange={ex}")
        save(f"heatmap_{ex}.json", d)
    except Exception as e:
        print(f"  heatmap_{ex}: FAIL {str(e)[:50]}")

# 3. indices tape
try:
    d = fetch("api/indices", timeout=20)
    save("indices.json", d)
except Exception as e:
    print(f"  indices: FAIL {str(e)[:50]}")

# 4. MERGE heatmap prices into listings (JSE/EGX have no EOD price in the
#    listing itself; the heatmap snapshot carries the real quote cache).
#    This is what makes the watchlist show prices on the static site.
for ex in ["JSE", "EGX", "NGX", "NSE"]:
    lp = os.path.join(OUT, f"listing_{ex}.json")
    hp = os.path.join(OUT, f"heatmap_{ex}.json")
    if not (os.path.exists(lp) and os.path.exists(hp)):
        continue
    try:
        listing = json.load(open(lp, encoding="utf-8"))
        heat = json.load(open(hp, encoding="utf-8"))
        stocks = listing.get("stocks", [])
        cells = heat.get("stocks", []) if isinstance(heat, dict) else heat
        by_sym = {c.get("sym"): c for c in cells if c.get("sym")}
        merged = 0
        for s in stocks:
            h = by_sym.get(s.get("sym")) or by_sym.get((s.get("sym") or "").replace(".JO", "").replace(".CA", ""))
            if h and (h.get("price") is not None):
                if s.get("price") is None:
                    s["price"] = h["price"]
                    merged += 1
                if s.get("chgPct") is None and h.get("chgPct") is not None:
                    s["chgPct"] = h["chgPct"]
                if s.get("volume") is None and h.get("volume") is not None:
                    s["volume"] = h["volume"]
        # also carry the exchange label the panel expects
        listing.setdefault("exchange", ex)
        save(f"listing_{ex}.json", listing)
        print(f"  merged heatmap prices into listing_{ex}: {merged} stocks")
    except Exception as e:
        print(f"  merge listing_{ex}: FAIL {str(e)[:50]}")

# 5. MARKET INFO snapshot (per exchange): the OHLC/52W/volume fields the
#    right-rail Market panel needs. One compact row per priced security.
#    (The live /api/chart payload is too heavy to snapshot per stock; this
#    covers the panel's key stats for every security with a price.)
for ex in ["JSE", "EGX", "NGX", "NSE"]:
    lp = os.path.join(OUT, f"listing_{ex}.json")
    if not os.path.exists(lp):
        continue
    try:
        listing = json.load(open(lp, encoding="utf-8"))
        rows = []
        for s in listing.get("stocks", []):
            if s.get("price") is None:
                continue
            rows.append({
                "sym": s.get("sym"),
                "ticker": s.get("ticker"),
                "name": s.get("name"),
                "price": s.get("price"),
                "chgPct": s.get("chgPct"),
                "volume": s.get("volume"),
                "currency": s.get("currency"),
                "sector": s.get("sector"),
            })
        save(f"market_{ex}.json", {"exchange": ex, "stocks": rows})
        print(f"  market_{ex}: {len(rows)} priced rows")
    except Exception as e:
        print(f"  market_{ex}: FAIL {str(e)[:50]}")

print("\nDone. Files in static_data/")
