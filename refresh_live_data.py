#!/usr/bin/env python3
"""refresh_live_data.py - pull FRESH data from the running backend and
write it into static_data/*.json (replacing stale snapshots).

Endpoints -> files:
  /api/fx          -> fx.json
  /api/bonds       -> bonds.json
  /api/commodities -> commodities.json
  /api/reg         -> reg.json
  /api/indices     -> indices.json
  /api/ratings?ticker=... -> ratings.json (probe a few liquid names)
  /api/tas?symbol=...     -> tas.json (probe)
Also refreshes financials_all.json from yahoo_financials.json (regenerated
by the backend on demand).

Run AFTER the backend is up. Writes in place; deploy via assemble_deploy.
"""
import json, os, sys, urllib.request, time

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
API = os.environ.get("API", "http://localhost:8081")

def fetch(ep, timeout=60):
    url = API + ep
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def save(name, data):
    path = os.path.join(SD, name)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  wrote {name} ({os.path.getsize(path):,}b)", flush=True)

def main():
    jobs = [
        ("fx.json", "/api/fx"),
        ("bonds.json", "/api/bonds"),
        ("commodities.json", "/api/commodities"),
        ("reg.json", "/api/reg"),
        ("indices.json", "/api/indices"),
    ]
    # probe-based files
    probes = [
        ("ratings.json", "/api/ratings?ticker=ABG.JO"),
        ("tas.json", "/api/tas?symbol=SOL.JO"),
    ]
    for name, ep in jobs + probes:
        try:
            d = fetch(ep)
            save(name, d)
            time.sleep(0.5)
        except Exception as e:
            print(f"  FAIL {name}: {str(e)[:100]}", flush=True)

    # refresh financials_all from yahoo_financials (backend-generated source)
    try:
        yf = json.load(open(os.path.join(SD, "yahoo_financials.json"), encoding="utf-8"))
        save("financials_all.json", yf)
    except Exception as e:
        print(f"  FAIL financials_all: {str(e)[:100]}", flush=True)

    print("DONE", flush=True)

if __name__ == "__main__":
    main()
