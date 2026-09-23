# MUTXRI TERMINAL

African markets terminal: NSE Nairobi, NGX Lagos, JSE Johannesburg, EGX Cairo.

**Live site: https://mutxriterminal.com/**

This repository holds the static build served by GitHub Pages. Data is a
**snapshot** (EOD listings, heatmaps, indices) captured from the live server -
it does not update in real time.

- Per-security candlestick history: static_data/history/<SYM>.json (JSE/EGX,
  Yahoo EOD 1y daily bars). NGX/NSE have no free historical feed.
- Live endpoints (chart/metrics/quotes) are NOT available in this static build;
  the UI shows an honest notice when clicked.

Data snapshot: 2026-09-23 20:41
