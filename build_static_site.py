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

print("\nDone. Files in static_data/")
