# MUTXRI TERMINAL (static build)

Static snapshot of the MUTXRI TERMINAL African markets terminal, deployed to
GitHub Pages. Data is a **snapshot** (EOD listings, heatmaps, indices) captured
from the live server - it does not update in real time.

- Live terminal: local server (python afri_server.py) at http://127.0.0.1:8081/
- Live endpoints (chart/metrics/quotes) are NOT available in this static build;
  the UI shows an honest notice when clicked.
- Per-security candlestick history: static_data/history/<SYM>.json (JSE/EGX,
  Yahoo EOD 1y daily bars). NGX/NSE have no free historical feed.

Data snapshot: 2026-08-30 05:59
