/* _fresh.js - read static_data at the version being served, never a cached copy.
 *
 * WHY THIS EXISTS. The shell stamps its own reads, but a panel is a document of its
 * own and does its own fetching, so the shell's wrapper never reached it. On
 * 2026-11-24 two FOCUS windows were opened with the identical URL
 * (ex=NSE&sym=QMRT) and answered differently: one painted QMRT 7.98 +3.10%, the
 * other said "NOT IN THE SNAPSHOT - Not carried by the NSE market snapshot",
 * because its market_NSE.json came out of the browser cache from before the
 * security was on the board. A panel that disagrees with the board beside it is
 * worse than a panel that is empty, because nothing on screen says which one is
 * old.
 *
 * WHAT IT DOES. Any request whose URL points into static_data gets the load time
 * appended and is sent no-store. Both request paths are covered, fetch and
 * XMLHttpRequest, because panels use both. The stamp is per document, so a long
 * lived panel re-reads a file it asks for again with the same stamp - the file is
 * re-requested each time, and the browser is told not to answer from cache.
 *
 * A panel may still set an explicit query string of its own; a URL that already
 * carries one is left exactly as it is.
 */
(function () {
  if (typeof window === "undefined") return;
  if (window.__mtFreshReads) return;
  window.__mtFreshReads = true;
  var STAMP = String(Date.now());

  function isData(u) {
    return typeof u === "string" && u.indexOf("static_data/") > -1;
  }
  function stamped(u) {
    if (!isData(u)) return u;
    if (u.indexOf("?") > -1) return u;      // the panel set its own query string
    if (u.indexOf("#") > -1) return u;      // a fragment is not ours to disturb
    return u + "?fr=" + STAMP;
  }

  // --- fetch ---
  if (window.fetch && !window.fetch.__mtWrapped) {
    var _fetch = window.fetch.bind(window);
    var wrapped = function (input, init) {
      try {
        if (typeof input === "string") {
          var u = stamped(input);
          if (u !== input) {
            var o = {};
            for (var k in (init || {})) o[k] = init[k];
            o.cache = "no-store";
            return _fetch(u, o);
          }
        }
      } catch (e) {}
      return _fetch(input, init);
    };
    wrapped.__mtWrapped = true;
    window.fetch = wrapped;
  }

  // --- XMLHttpRequest ---
  try {
    var _open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (method, url) {
      var args = Array.prototype.slice.call(arguments);
      try { args[1] = stamped(url); } catch (e) {}
      return _open.apply(this, args);
    };
  } catch (e) {}
})();
