/* nse_heatmap_charts.js  -  Render candlestick / line charts for NSE securities,
 * inside heatmap cells or a detail pane. Built on TradingView's OPEN-SOURCE
 * Lightweight Charts library (Apache-2.0) - free to use and redistribute. This
 * module does NOT fetch from TradingView (their ToS forbid scraping their data).
 * It takes bars from a DATA ADAPTER you supply, so you can wire it to a licensed
 * or public NSE source without touching the chart code.
 *
 * INCLUDE (from the official CDN):
 *   <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
 *   <script src="nse_heatmap_charts.js"></script>
 *
 * DATA CONTRACT (what your adapter must return):
 *   getBars(ticker, { timeframe }) -> Promise<Array<{
 *       time: 'YYYY-MM-DD' | epochSeconds,   // TradingView time format
 *       open:Number, high:Number, low:Number, close:Number, volume?:Number
 *   }>>
 *   Bars MUST be ascending by time, no gaps of fabricated data. If a security
 *   has no history, return [] - the chart shows an honest empty state, never
 *   invented candles.
 *
 * WHERE THE DATA COMES FROM (legitimate NSE options - pick one, wire the adapter):
 *   - NSE official / a licensed data vendor (the correct route for a product you
 *     license on; matches your data-redistribution posture).
 *   - The kwayisi/afx NSE endpoint you already use for EOD period returns.
 *   - Your own backend (afri_server.py) that stores bars in Timescale/ClickHouse.
 *   Do NOT scrape TradingView - it breaks their ToS and creates the exact
 *   liability the licensing-protection plan is trying to avoid.
 */
(function (root) {
  "use strict";

  var GODEL = {
    up: "#33e29a", down: "#f87171", line: "#33e29a",
    bg: "transparent", grid: "#141414", text: "#6a6a6a", border: "#262626"
  };

  function _lib() {
    if (typeof LightweightCharts === "undefined")
      throw new Error("Lightweight Charts not loaded - add the CDN <script> first.");
    return LightweightCharts;
  }

  /* Full-size chart (detail pane). el = container, opts.type = 'candle'|'line'. */
  function createChart(el, opts) {
    opts = opts || {};
    var LC = _lib();
    var chart = LC.createChart(el, {
      width: el.clientWidth, height: el.clientHeight || 320,
      layout: { background: { type: "solid", color: GODEL.bg }, textColor: GODEL.text,
                fontFamily: "'Oxygen Mono', monospace", fontSize: 10 },
      grid: { vertLines: { color: GODEL.grid }, horzLines: { color: GODEL.grid } },
      rightPriceScale: { borderColor: GODEL.border },
      timeScale: { borderColor: GODEL.border, timeVisible: false },
      crosshair: { mode: LC.CrosshairMode.Normal }
    });
    var series = (opts.type === "line")
      ? chart.addLineSeries({ color: GODEL.line, lineWidth: 2, priceLineVisible: false })
      : chart.addCandlestickSeries({
          upColor: GODEL.up, downColor: GODEL.down, borderVisible: false,
          wickUpColor: GODEL.up, wickDownColor: GODEL.down });
    var ro = new ResizeObserver(function () {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight || 320 });
    });
    ro.observe(el);
    return { chart: chart, series: series, type: opts.type || "candle",
             destroy: function () { ro.disconnect(); chart.remove(); } };
  }

  /* Feed bars into a chart. For line type, maps close price. */
  function setBars(handle, bars) {
    if (!Array.isArray(bars) || !bars.length) { handle.series.setData([]); return false; }
    if (handle.type === "line")
      handle.series.setData(bars.map(function (b) { return { time: b.time, value: b.close }; }));
    else
      handle.series.setData(bars.map(function (b) {
        return { time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }; }));
    handle.chart.timeScale().fitContent();
    return true;
  }

  /* Tiny inline SPARKLINE for a heatmap cell (no axes/crosshair - lightweight).
   * Renders a mini line from closes; falls back to nothing if no data. */
  function sparkline(el, bars, opts) {
    opts = opts || {};
    if (!Array.isArray(bars) || bars.length < 2) { el.innerHTML = ""; return false; }
    var closes = bars.map(function (b) { return b.close; });
    var min = Math.min.apply(null, closes), max = Math.max.apply(null, closes);
    var w = opts.width || el.clientWidth || 120, h = opts.height || 28, pad = 2;
    var span = (max - min) || 1;
    var pts = closes.map(function (v, i) {
      var x = pad + i * (w - 2 * pad) / (closes.length - 1);
      var y = h - pad - (v - min) / span * (h - 2 * pad);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    var rising = closes[closes.length - 1] >= closes[0];
    var color = rising ? GODEL.up : GODEL.down;
    el.innerHTML =
      '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h +
      '" preserveAspectRatio="none" aria-hidden="true">' +
      '<polyline points="' + pts + '" fill="none" stroke="' + color +
      '" stroke-width="1.4"/></svg>';
    return true;
  }

  /* Convenience: resolve bars via YOUR adapter, then render.
   * adapter.getBars(ticker,{timeframe}) -> Promise<bars>. Honest on failure. */
  function renderFor(el, ticker, adapter, opts) {
    opts = opts || {};
    if (!adapter || typeof adapter.getBars !== "function")
      throw new Error("Provide a data adapter with getBars(ticker, opts).");
    return adapter.getBars(ticker, { timeframe: opts.timeframe || "1D" })
      .then(function (bars) {
        if (opts.spark) return sparkline(el, bars, opts);
        var handle = createChart(el, opts);
        var ok = setBars(handle, bars);
        if (!ok) el.setAttribute("data-empty", "no history available");
        return handle;
      })
      .catch(function (e) {
        el.setAttribute("data-empty", "chart data unavailable");
        return null;
      });
  }

  var api = { createChart: createChart, setBars: setBars, sparkline: sparkline,
              renderFor: renderFor, colors: GODEL };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.NSECharts = api;
})(typeof window !== "undefined" ? window : this);
