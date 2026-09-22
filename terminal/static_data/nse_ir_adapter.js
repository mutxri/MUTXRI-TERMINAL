/* nse_ir_adapter.js - DATA ADAPTER for nse_heatmap_charts.js that feeds
 * REAL NSE OHLC history from the NSE's official IR data feed:
 *   GET https://ir.nse.co.ke/hist/<TICKER>?d=YYYY-MM-01;ref=tbl
 *   (referer: https://www.nse.co.ke/share-price/)
 * Returns the NSE's own monthly HTML table (Date/Open/High/Low/Close/
 * Average/Volume/Turnover/Deals) - the same feed the exchange's own
 * share-price pages use. No scraping of TradingView.
 *
 * This adapter also falls back to the terminal's deployed static history
 * files (static_data/history/NSE_<SYM>.json) when the IR feed has no page
 * for a symbol (KCB, BAT, ...) - so the chart NEVER shows "no data" for
 * symbols whose real bars were archived from the official ticker API.
 */
(function (root) {
  "use strict";

  var REF = "https://www.nse.co.ke/share-price/";

  function parseIRTable(html) {
    // rows: <td class=l>DATE</td><td>OPEN</td><td>HIGH</td><td>LOW</td><td>CLOSE</td>...
    var bars = [];
    var re = /<td class=l>(\d{4}-\d{2}-\d{2})<\/td>\s*<td>([\d,.-]+)<\/td>\s*<td>([\d,.-]+)<\/td>\s*<td>([\d,.-]+)<\/td>\s*<td>([\d,.-]+)<\/td>/g;
    var m;
    while ((m = re.exec(html)) !== null) {
      var o = parseFloat(m[2].replace(/,/g, "")), h = parseFloat(m[3].replace(/,/g, "")),
          l = parseFloat(m[4].replace(/,/g, "")), c = parseFloat(m[5].replace(/,/g, ""));
      if (isFinite(o) && isFinite(h) && isFinite(l) && isFinite(c))
        bars.push({ time: m[1], open: o, high: h, low: l, close: c });
    }
    return bars;
  }

  function fetchIRMonth(ticker, y, mo) {
    var url = "https://ir.nse.co.ke/hist/" + encodeURIComponent(ticker) +
              "?d=" + y + "-" + (mo < 10 ? "0" + mo : mo) + "-01;ref=tbl";
    return fetch(url, {
      headers: { "Referer": REF, "Origin": "https://www.nse.co.ke" }
    }).then(function (r) {
      if (!r.ok) return "";
      return r.text();
    }).catch(function () { return ""; });
  }

  var NSEIRAdapter = {
    getBars: function (ticker, opts) {
      var tf = (opts && opts.timeframe) || "1D";
      ticker = String(ticker || "").toUpperCase();
      if (!ticker) return Promise.resolve([]);

      // 1) try the terminal's static history first (fast, works on Pages)
      //    panels/ -> ../../static_data/history/NSE_<TKR>.json
      return fetch("../../static_data/history/NSE_" + ticker + ".json")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.bars && d.bars.length >= 2) {
            return d.bars.map(function (b) {
              return { time: b.t, open: b.o, high: b.h, low: b.l, close: b.c };
            });
          }
          // 2) fall back to the official IR feed (fetch last 12 months)
          var months = [];
          var now = new Date();
          var y = now.getFullYear(), mo = now.getMonth() + 1;
          for (var i = 0; i < 12; i++) {
            months.push([y, mo]);
            mo--; if (mo === 0) { mo = 12; y--; }
          }
          var chain = Promise.resolve([]);
          months.forEach(function (ym) {
            chain = chain.then(function (acc) {
              return fetchIRMonth(ticker, ym[0], ym[1]).then(function (html) {
                return acc.concat(parseIRTable(html));
              });
            });
          });
          return chain.then(function (bars) {
            // dedupe by date, ascending
            var seen = {};
            bars.forEach(function (b) { seen[b.time] = b; });
            return Object.keys(seen).sort().map(function (k) { return seen[k]; });
          });
        })
        .catch(function () { return []; });
    }
  };

  root.NSEIRAdapter = NSEIRAdapter;
  if (typeof module !== "undefined" && module.exports)
    module.exports = { NSEIRAdapter: NSEIRAdapter };
})(typeof window !== "undefined" ? window : this);
