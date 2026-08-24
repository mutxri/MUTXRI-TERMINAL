#!/usr/bin/env python3
"""build_static_frontend.py - produce a static index.html for GitHub Pages.
Remaps /api/* fetches to static_data/*.json snapshots. Live endpoints
(chart/metrics/quotes) show an honest 'static snapshot' note.
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
# also any other listing fetch forms
t = t.replace(
    "fetch('/api/listing?exchange=' + ex)",
    "fetch('static_data/listing_' + ex + '.json')",
)

# 2. indices remap
t = t.replace(
    "fetch('/api/indices')",
    "fetch('static_data/indices.json')",
)

# 3. add a fetch shim BEFORE the app script: any remaining /api/ call that is
#    not snapshot-able gets an honest static-mode response
shim = """
// ===== STATIC BUILD SHIM (GitHub Pages) =====
// Live endpoints (chart/metrics/quotes) are NOT available in the static
// snapshot build - respond honestly instead of erroring.
const __origFetch = window.fetch;
window.fetch = function(url, opts){
  const u = String(url);
  if(u.indexOf('/api/chart') === 0 || u.indexOf('/api/metrics') === 0 || u.indexOf('/api/quotes') === 0){
    return Promise.resolve(new Response(JSON.stringify({
      error: 'static snapshot build: live market data not available on GitHub Pages',
      bars: [], rows: [], noData: true
    }), {status: 200, headers: {'Content-Type': 'application/json'}}));
  }
  return __origFetch(url, opts);
};
// ===== END STATIC SHIM =====
"""
# insert shim right after '<script>'
t = t.replace("<script>", "<script>" + shim, 1)

open(DST, "w", encoding="utf-8").write(t)
print(f"static_index.html written ({len(t)} chars)")

# verify the remaps landed
print("listing remap:", "static_data/listing_" in t)
print("indices remap:", "static_data/indices.json" in t)
print("shim present:", "STATIC BUILD SHIM" in t)
