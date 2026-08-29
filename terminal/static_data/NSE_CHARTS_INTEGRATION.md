# NSE heatmap charts — candlestick / line

Renders candlestick and line charts for NSE securities (heatmap cells or a detail
pane), on TradingView's **open-source Lightweight Charts** library (Apache-2.0).
`nse_heatmap_charts.js` — 9 tests passing.

## Important: data source
This module does **not** fetch from TradingView. TradingView's terms prohibit
programmatically pulling their data, and scraping it would create exactly the
redistribution liability the licensing plan is trying to avoid. The module takes
bars from a **data adapter you supply** (see `nse_bars_adapter.example.js`), so
you wire it to a legitimate NSE source:
- your own backend (`afri_server.py`) serving bars you have the right to serve,
- the kwayisi/afx EOD endpoint you already use (confirm its terms),
- a licensed NSE data vendor.

Using TradingView's charting *library* is fine and free; pulling their *data* is
not. This module keeps you on the right side of that line.

## Include
```html
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<script src="nse_heatmap_charts.js"></script>
```

## Detail chart (candles or line)
```js
const adapter = BackendAdapter; // from nse_bars_adapter.example.js
NSECharts.renderFor(document.getElementById('chart'), 'SCOM', adapter, { type:'candle', timeframe:'1D' });
// line: { type:'line' }
```

## Sparkline inside a heatmap cell
```js
adapter.getBars('SCOM', {timeframe:'1D'}).then(bars =>
  NSECharts.sparkline(cellEl, bars, { width: 120, height: 28 })
);
```

## Honesty rules baked in
- No data -> empty state (`data-empty` attribute), never fabricated candles.
- EOD close-only sources: prefer **line** charts. If you must draw candles from
  close-only data, the example adapter sets OHLC = close (a flat mark) rather than
  inventing highs/lows — so the chart never implies intraday range it doesn't have.
- Rising sparkline = mint, falling = red (Godel palette).

## Data contract
`adapter.getBars(ticker, {timeframe}) -> Promise<Array<{time,open,high,low,close,volume?}>>`
ascending by time, TradingView time format, `[]` when no history.
