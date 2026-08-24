/* tickerfix.js  -  three drop-in fixes for the deployed terminal.
 *
 * BUG 1  NaN%    : tape computed (price-prev)/prev with prev missing/0 on EOD
 *                  markets (NGX/NSE). -> use safePct(), returns null -> dash.
 * BUG 2  crash   : REG (and any /api call with no static snapshot) returns
 *                  GitHub's HTML 404 page; JSON.parse('<!DOCTYPE...') throws
 *                  "Unexpected token '<'". -> use fetchJSONSafe(), which checks
 *                  ok + content-type and never parses HTML as JSON.
 * BUG 3  mismatch: tape and watchlist were built from different sources and
 *                  drifted. -> build BOTH from the same exchange array via
 *                  buildTapeItems(stocks). One source of truth.
 *
 * Vanilla JS, no deps. Pure functions are unit-tested in test_tickerfix.js.
 */
(function (root) {
  "use strict";

  var DASH = "\u2014";

  // ---- BUG 1: never emit NaN -------------------------------------------
  // Returns a Number (percent) or null. null means "no basis to compute".
  function safePct(price, prevClose) {
    var p = Number(price), pc = Number(prevClose);
    if (!isFinite(p) || !isFinite(pc) || pc === 0) return null;
    return (p - pc) / pc * 100;
  }

  // Format a percent for display. Accepts a precomputed pct, OR (price,prev).
  // Always returns a string; missing data -> dash, never "NaN%" or a false 0.
  function fmtPct(a, b) {
    var pct = (arguments.length < 2) ? a : safePct(a, b);
    pct = (pct === null || pct === undefined) ? NaN : Number(pct);
    if (!isFinite(pct)) return DASH;
    return (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
  }

  function pctClass(a, b) {
    var pct = (arguments.length < 2) ? a : safePct(a, b);
    pct = (pct === null || pct === undefined) ? NaN : Number(pct);
    if (!isFinite(pct)) return "flat";
    return pct > 0 ? "up" : (pct < 0 ? "down" : "flat");
  }

  // ---- BUG 2: never JSON.parse an HTML error page ----------------------
  // Resolves to {ok:true,data} or {ok:false,error,status}. Never throws on a
  // 404 HTML page. Use everywhere instead of fetch(...).then(r=>r.json()).
  function fetchJSONSafe(url, opts) {
    return fetch(url, opts).then(function (r) {
      var ct = (r.headers && r.headers.get && r.headers.get("content-type")) || "";
      if (!r.ok) {
        return { ok: false, status: r.status,
                 error: "HTTP " + r.status + " for " + url };
      }
      if (ct.indexOf("application/json") === -1) {
        // got HTML (e.g. GitHub 404 page) where JSON was expected
        return { ok: false, status: r.status,
                 error: "expected JSON, got " + (ct || "unknown") +
                        " (endpoint not available on this host)" };
      }
      return r.text().then(function (t) {
        try { return { ok: true, data: JSON.parse(t) }; }
        catch (e) { return { ok: false, error: "invalid JSON from " + url }; }
      });
    }).catch(function (e) {
      return { ok: false, error: String(e && e.message || e) };
    });
  }

  // ---- BUG 3: tape and watchlist from ONE source -----------------------
  // stocks: array of {ticker, name, price, prevClose?, changePct?} for the
  // ACTIVE exchange - the same array the watchlist renders. Returns tape items
  // with a safe pct. Items with no usable price are skipped (not shown as NaN).
  function buildTapeItems(stocks) {
    if (!Array.isArray(stocks)) return [];
    var out = [];
    for (var i = 0; i < stocks.length; i++) {
      var s = stocks[i];
      if (!s || !s.ticker) continue;
      var price = Number(s.price);
      if (!isFinite(price)) continue;               // no price -> not on tape
      // prefer an explicit changePct if the feed gave one; else derive safely
      var pct = (s.changePct !== undefined && s.changePct !== null && isFinite(Number(s.changePct)))
                ? Number(s.changePct)
                : safePct(s.price, s.prevClose);      // may be null -> dash
      out.push({
        ticker: s.ticker,
        name: s.name || "",
        price: price,
        pctText: fmtPct(pct),
        cls: pctClass(pct)
      });
    }
    return out;
  }

  // Convenience DOM renderers so tape + watchlist provably use one source.
  // Pass the SAME `stocks` array to both.
  function renderTape(el, stocks) {
    if (!el) return;
    var items = buildTapeItems(stocks);
    el.innerHTML = items.map(function (it) {
      return '<span class="tick"><b>' + escapeHtml(it.ticker) + '</b> ' +
             fmtNum(it.price) + ' <span class="' + it.cls + '">' +
             it.pctText + '</span></span>';
    }).join("");
  }

  function renderWatchlist(el, stocks) {
    if (!el) return;
    var items = buildTapeItems(stocks); // same builder -> guaranteed match
    el.innerHTML = items.map(function (it) {
      return '<li><b>' + escapeHtml(it.ticker) + '</b>' +
             '<span class="nm">' + escapeHtml(it.name) + '</span>' +
             '<span>' + fmtNum(it.price) + '</span>' +
             '<span class="' + it.cls + '">' + it.pctText + '</span></li>';
    }).join("");
  }

  function fmtNum(n) {
    n = Number(n);
    if (!isFinite(n)) return DASH;
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var api = { safePct: safePct, fmtPct: fmtPct, pctClass: pctClass,
              fetchJSONSafe: fetchJSONSafe, buildTapeItems: buildTapeItems,
              renderTape: renderTape, renderWatchlist: renderWatchlist,
              DASH: DASH };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TickerFix = api;
})(typeof window !== "undefined" ? window : this);
