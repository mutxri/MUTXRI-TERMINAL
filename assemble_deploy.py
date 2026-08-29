#!/usr/bin/env python3
"""assemble_deploy.py - build the GitHub Pages deploy folder."""
import os, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(BASE, "gh_pages_deploy")

# clean
if os.path.exists(DEPLOY):
    shutil.rmtree(DEPLOY)
os.makedirs(DEPLOY)

# ================= TERMINAL (served at /terminal/) =================
TERM = os.path.join(DEPLOY, "terminal")
os.makedirs(TERM, exist_ok=True)

# index.html (static build) - terminal entry
shutil.copy(os.path.join(BASE, "static_index.html"), os.path.join(TERM, "index.html"))

# tickerfix.js (NaN/404/tape fixes - must ship with the page)
shutil.copy(os.path.join(BASE, "tickerfix.js"), os.path.join(TERM, "tickerfix.js"))

# custom domain declaration for GitHub Pages
with open(os.path.join(DEPLOY, "CNAME"), "w", encoding="utf-8") as _c:
    _c.write("mutxriterminal.com\n")

# documentation page (root-level, linked from landing)
shutil.copy(os.path.join(BASE, "docs.html"), os.path.join(DEPLOY, "docs.html"))

# 404 page
if os.path.exists(os.path.join(BASE, "404.html")):
    shutil.copy(os.path.join(BASE, "404.html"), os.path.join(DEPLOY, "404.html"))

# links hub page
shutil.copy(os.path.join(BASE, "LINKS.html"), os.path.join(DEPLOY, "LINKS.html"))

# panels (static heatmap + static screener + the shell's other panels for completeness)
os.makedirs(os.path.join(TERM, "features", "panels"), exist_ok=True)
# build the static heatmap from the LIVE panel source: remap /api/heatmap ->
# static_data/heatmap_X.json so the deployed heatmap shows the real snapshot
# (with sector drill-down) instead of falling back to SAMPLE data.
with open(os.path.join(BASE, "features", "panels", "afri_heatmap.html"), encoding="utf-8") as _f:
    _hm = _f.read()
_hm = _hm.replace(
    'fetch(ENDPOINT+"?exchange="+encodeURIComponent(activeEx))',
    "fetch('../../static_data/heatmap_' + activeEx + '.json')",
)
_hm = _hm.replace(
    'fetch(ENDPOINT + "?exchange=" + encodeURIComponent(activeEx))',
    "fetch('../../static_data/heatmap_' + activeEx + '.json')",
)
with open(os.path.join(TERM, "features", "panels", "afri_heatmap.html"), "w", encoding="utf-8") as _f:
    _f.write(_hm)
print("  static heatmap: remapped to static_data/heatmap_X.json + drill-down")
shutil.copy(os.path.join(BASE, "static_data", "afri_screener_static.html"),
            os.path.join(TERM, "features", "panels", "afri_screener.html"))
# copy the rest of the panels (static snapshot versions where they exist,
# otherwise originals - they degrade gracefully to SAMPLE data)
STATIC_PANELS = ["afri_bnd.html", "afri_reg.html", "afri_fx.html", "afri_glco.html", "afri_ratings.html", "afri_tas.html", "afri_financials.html", "afri_corp.html", "afri_news.html"]
# (all panels now have static snapshot versions; nothing extra to copy)
# static snapshot panels read static_data/*.json
for p in STATIC_PANELS:
    src = os.path.join(BASE, "static_data", p)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(TERM, "features", "panels", p))
        print(f"  static panel: {p}")

# static data
shutil.copytree(os.path.join(BASE, "static_data"),
                os.path.join(TERM, "static_data"),
                ignore=shutil.ignore_patterns("afri_heatmap_static.html"))

# ================= LANDING PAGE (served at /) =================
# landing/index.html -> root index.html
LANDING = os.path.join(BASE, "landing")
if os.path.isdir(LANDING):
    shutil.copy(os.path.join(LANDING, "index.html"), os.path.join(DEPLOY, "index.html"))
    # screenshots (assets/)
    if os.path.isdir(os.path.join(LANDING, "assets")):
        shutil.copytree(os.path.join(LANDING, "assets"),
                        os.path.join(DEPLOY, "assets"), dirs_exist_ok=True)
    print("  landing page at root + terminal at /terminal/")

# .nojekyll (critical - prevents Jekyll stripping)
open(os.path.join(DEPLOY, ".nojekyll"), "w").write("")

# README
readme = """# MUTXRI TERMINAL (static build)

Static snapshot of the MUTXRI TERMINAL African markets terminal, deployed to
GitHub Pages. Data is a **snapshot** (EOD listings, heatmaps, indices) captured
from the live server - it does not update in real time.

- Live terminal: local server (python afri_server.py) at http://127.0.0.1:8081/
- Live endpoints (chart/metrics/quotes) are NOT available in this static build;
  the UI shows an honest notice when clicked.
- Per-security candlestick history: static_data/history/<SYM>.json (JSE/EGX,
  Yahoo EOD 1y daily bars). NGX/NSE have no free historical feed.

Data snapshot: {date}
"""
open(os.path.join(DEPLOY, "README.md"), "w", encoding="utf-8").write(
    readme.format(date=__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")))

# list result
total = sum(len(f) for _, _, fs in os.walk(DEPLOY) for f in fs)
files = sum(len(fs) for _, _, fs in os.walk(DEPLOY) for f in fs)
print(f"Deploy folder ready: {DEPLOY}")
print(f"  files: {files}, total size: {total/1024:.0f} KB")
for root, dirs, fs in os.walk(DEPLOY):
    for f in fs:
        print(f"  {os.path.relpath(os.path.join(root, f), DEPLOY)}")
