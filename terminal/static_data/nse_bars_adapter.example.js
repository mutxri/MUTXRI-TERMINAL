/* nse_bars_adapter.example.js  -  Reference DATA ADAPTER for nse_heatmap_charts.js
 *
 * The chart module is feed-agnostic; this shows how to supply bars from a
 * LEGITIMATE source. Two examples - pick/adapt one. Neither scrapes TradingView.
 *
 * Bars must be ascending, TradingView time format ('YYYY-MM-DD' or epoch secs),
 * and NEVER fabricated: if the source has no history, return [].
 */

/* A) Via your own backend (afri_server.py), which stores bars you have the right
 *    to serve. This is the correct route for a product you license to others. */
var BackendAdapter = {
  getBars: function (ticker, opts) {
    var tf = (opts && opts.timeframe) || "1D";
    var url = "/api/bars?symbol=" + encodeURIComponent(ticker) + "&tf=" + tf;
    return fetch(url).then(function (r) {
      var ct = (r.headers.get("content-type") || "");
      if (!r.ok || ct.indexOf("application/json") === -1) return []; // honest: no fake bars
      return r.json();
    }).then(function (d) {
      var rows = (d && d.bars) || [];
      // normalise -> {time,open,high,low,close}
      return rows.filter(function (b) { return b && b.close != null; })
                 .map(function (b) {
        return { time: b.time || b.date, open: +b.open, high: +b.high,
                 low: +b.low, close: +b.close, volume: b.volume != null ? +b.volume : undefined };
      });
    }).catch(function () { return []; });
  }
};

/* B) Via the kwayisi/afx NSE endpoint you already use for EOD data. Confirm its
 *    terms allow your use. Shape varies, so map defensively; if only a close
 *    series is available, synthesise flat OHLC = close (clearly not real intraday
 *    range) OR prefer a line chart so you don't imply candles you don't have. */
var KwayisiEODAdapter = {
  getBars: function (ticker, opts) {
    var url = "https://afx.kwayisi.org/nse/" + encodeURIComponent(ticker) + ".json";
    return fetch(url).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var hist = (d && (d.history || d.data)) || [];
        if (!hist.length) return [];
        return hist.map(function (p) {
          var close = +(p.price != null ? p.price : p.close);
          // EOD close-only source: use LINE charts. If you must draw candles,
          // do NOT invent highs/lows - leave OHLC = close so it reads honestly.
          return { time: p.date, open: close, high: close, low: close, close: close };
        }).filter(function (b) { return isFinite(b.close); });
      }).catch(function () { return []; });
  }
};

if (typeof module !== "undefined" && module.exports)
  module.exports = { BackendAdapter: BackendAdapter, KwayisiEODAdapter: KwayisiEODAdapter };
