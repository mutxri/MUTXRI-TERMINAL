#!/usr/bin/env python3
"""build_static_frontend.py - produce a static index.html for GitHub Pages.
Remaps /api/listing + /api/indices to static_data/*.json snapshots.
Live endpoints (chart/metrics/quotes) show an honest 'snapshot' note via the
single API_BASE shim already in index.html - NO duplicate shim is added here
(that caused a '__origFetch already declared' SyntaxError that blanked the page).
"""
import re, os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "index.html")
DST = os.path.join(BASE, "static_index.html")

t = open(SRC, encoding="utf-8").read()

# 1. listing remap: /api/listing?exchange=NGX -> static_data/listing_NGX.json
t = re.sub(
    r"fetch\('/api/listing\?exchange=' \+ ex\)",
    "fetch('static_data/listing_' + ex + '.json')",
    t,
)
t = t.replace(
    "fetch('/api/listing?exchange=' + ex)",
    "fetch('static_data/listing_' + ex + '.json')",
)

# 2. indices remap (both plain fetch and TickerFix.fetchJSONSafe forms)
t = t.replace(
    "fetch('/api/indices')",
    "fetch('static_data/indices.json')",
)
t = t.replace(
    "TickerFix.fetchJSONSafe('/api/indices')",
    "TickerFix.fetchJSONSafe('static_data/indices.json')",
)

# 3. screener snapshot (static build): /api/screener -> static_data/screener_X.json
t = t.replace(
    "fetch(ENDPOINT+\"?\"+q(f)",
    "fetch('static_data/screener_' + activeEx + '.json?' + q(f)",
)

# 4. Make the snapshot mode explicit for the static build: set API_BASE=""
#    (it already defaults to "" - ensure no accidental value)
t = re.sub(r'const API_BASE = "[^"]*";', 'const API_BASE = "";', t, count=1)

open(DST, "w", encoding="utf-8").write(t)
print(f"static_index.html written ({len(t)} chars)")

# verify: exactly ONE __origFetch declaration, remaps landed
print("listing remap:", t.count("static_data/listing_"))
print("indices remap:", t.count("static_data/indices.json"))
print("__origFetch declarations:", t.count("const __origFetch"))
print("shim blocks:", t.count("STATIC BUILD SHIM"))
