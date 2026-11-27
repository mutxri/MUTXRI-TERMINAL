/* mx_chart_tools.js - drawing tools and indicator maths for the MUTXRI
 * candlestick charts. Pure arithmetic over the OHLC bars the panel already
 * holds; this file never fetches anything and never invents a value.
 *
 * Requires Lightweight Charts v5 already loaded (window.LightweightCharts).
 *
 * WHY IT IS A SEPARATE FILE. The chart renderer lives inside a panel document.
 * Everything here is chart plumbing, so keeping it out of the panel means the
 * panel can be rewritten without losing the tools, and a second panel can use
 * the same tools by calling MXChartTools.attach once.
 *
 * PUBLIC SURFACE (window.MXChartTools)
 *   .attach(opts) -> handle
 *        opts = { chart, series, host, key, bars, times, onChange }
 *          chart   LightweightCharts chart instance (price pane is pane 0)
 *          series  the price series (candlestick/line/area) drawn in pane 0
 *          host    the element the chart fills; the SVG overlay is mounted here
 *          key     security key the drawings belong to (persistence scope)
 *          bars    the bars currently in the series: [{t,o,h,l,c,v}]
 *          times   every bar time of the active series, oldest first (the time
 *                  domain the drawings are indexed against). Optional; when it
 *                  is absent bars' own times are used, which means a drawing is
 *                  only visible while its bars are in the visible range.
 *          onChange  called after any add/remove/clear
 *   handle.setContext(opts)  re-point at a new chart/series/bars/security
 *   handle.setTool(name)     'none'|'trend'|'ray'|'hline'|'vline'|'zone'|'erase'
 *   handle.tool()            current tool name
 *   handle.redraw()          repaint the overlay
 *   handle.removeById(id)    delete one drawing
 *   handle.clearAll()        delete every drawing for the current key
 *   handle.items()           the drawing objects for the current key
 *   handle.count()           how many drawings the current key holds
 *   handle.destroy()         detach overlay, listeners and chart subscription
 *
 *   RESHAPING. A stored line (trend, ray) and a zone paint a handle on each of
 *   their two anchors, and a handle is grabbable while NO tool is armed: the
 *   anchor follows the pointer, snapped to the same bar and price the drawing
 *   was created on, and the change is saved on release. The overlay as a whole
 *   stays pointer-events:none, so the handles are the only part of it that takes
 *   the pointer and panning and zooming under them still belong to the chart.
 *   The erase tool accepts a click anywhere along a drawn line, including the
 *   part of a ray that runs past its second anchor out to the right edge.
 *
 *   .indicators = { sma, ema, bollinger, rsi, macd, volume, blankReason }
 *        Every function takes the closes (or bars) and returns an array of the
 *        same length, or a set of arrays, with null wherever the window is not
 *        yet filled. A length-50 SMA has no value for the first 49 bars and this
 *        module returns null there rather than a number built from missing bars.
 *
 * PERSISTENCE
 *   localStorage['mt_chart_drawings_v1'] = { v:1, keys:{ "<security>": [item] } }
 *   localStorage['mt_chart_inds_v1']     = { v:1, ...indicator state }
 *   Both keys are new with this feature, so no existing key is renamed and no
 *   reader's saved state is invalidated. Unknown fields on a stored item survive
 *   a load/save round trip, and a payload written by a NEWER schema version is
 *   never overwritten: the tools refuse to write and say so. If the stored value
 *   cannot be parsed it is copied to '<key>__unreadable' before anything is
 *   written, so the bytes a reader already had are never destroyed.
 */
(function (root) {
  "use strict";

  var DRAW_KEY = "mt_chart_drawings_v1";
  var DRAW_VER = 1;
  var INDS_KEY = "mt_chart_inds_v1";
  var INDS_VER = 1;

  /* ---------------------------------------------------------------- maths -- */

  /* Simple moving average. out[i] is null until n bars exist, and null again if
   * any bar inside the window is missing: a window that is not filled gets no
   * value rather than one assembled from fewer bars than the window asks for. */
  function sma(values, n) {
    n = Math.max(1, Math.floor(n));
    var out = new Array(values.length).fill(null);
    for (var i = n - 1; i < values.length; i++) {
      var s = 0, ok = true;
      for (var j = i - n + 1; j <= i; j++) {
        var v = values[j];
        if (v == null || !isFinite(v)) { ok = false; break; }
        s += v;
      }
      if (ok) out[i] = s / n;
    }
    return out;
  }

  /* Exponential moving average, seeded with the SMA of the first n bars, so a
   * length-n EMA has nothing at all before bar n-1. Seeding from the very first
   * close (what this used to do) draws a value that no window of n bars supports. */
  function ema(values, n) {
    n = Math.max(1, Math.floor(n));
    var out = new Array(values.length).fill(null);
    var k = 2 / (n + 1), seedSum = 0, seedCount = 0, prev = null;
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (v == null || !isFinite(v)) {
        out[i] = null; seedSum = 0; seedCount = 0; prev = null; continue;
      }
      if (prev == null) {
        seedSum += v; seedCount++;
        if (seedCount === n) { prev = seedSum / n; out[i] = prev; }
        continue;
      }
      prev = v * k + prev * (1 - k);
      out[i] = prev;
    }
    return out;
  }

  /* Bollinger bands: SMA(n) middle, +/- k population standard deviations. */
  function bollinger(values, n, k) {
    n = Math.max(1, Math.floor(n)); k = (k == null ? 2 : k);
    var mid = sma(values, n);
    var upper = new Array(values.length).fill(null);
    var lower = new Array(values.length).fill(null);
    for (var i = 0; i < values.length; i++) {
      if (mid[i] == null) continue;
      var s = 0, bad = false;
      for (var j = i - n + 1; j <= i; j++) {
        if (values[j] == null || !isFinite(values[j])) { bad = true; break; }
        s += Math.pow(values[j] - mid[i], 2);
      }
      if (bad) continue;
      var sd = Math.sqrt(s / n);
      upper[i] = mid[i] + k * sd;
      lower[i] = mid[i] - k * sd;
    }
    return { middle: mid, upper: upper, lower: lower };
  }

  /* Wilder's RSI. First value lands on bar n (it needs n changes), null before. */
  function rsi(values, n) {
    n = Math.max(1, Math.floor(n));
    var out = new Array(values.length).fill(null);
    var g = 0, l = 0, count = 0;
    for (var i = 1; i < values.length; i++) {
      var a = values[i - 1], b = values[i];
      if (a == null || b == null || !isFinite(a) || !isFinite(b)) { g = 0; l = 0; count = 0; continue; }
      var ch = b - a, up = ch > 0 ? ch : 0, dn = ch < 0 ? -ch : 0;
      count++;
      if (count <= n) {
        g += up; l += dn;
        if (count === n) out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
      } else {
        g = (g * (n - 1) + up) / n;
        l = (l * (n - 1) + dn) / n;
        out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
      }
    }
    return out;
  }

  /* MACD: EMA(fast) - EMA(slow), its EMA(signal) and the histogram. Every output
   * is null until both of its own inputs exist, which is 25 bars for the line and
   * 25 + signal - 1 for the signal on the usual 12/26/9 settings. */
  function macd(values, fast, slow, signal) {
    fast = fast || 12; slow = slow || 26; signal = signal || 9;
    var ef = ema(values, fast), es = ema(values, slow);
    var line = values.map(function (_, i) {
      return (ef[i] != null && es[i] != null) ? ef[i] - es[i] : null;
    });
    var sig = new Array(values.length).fill(null);
    var hist = new Array(values.length).fill(null);
    var seedSum = 0, seedCount = 0, prev = null, k = 2 / (signal + 1);
    for (var i = 0; i < line.length; i++) {
      var v = line[i];
      if (v == null) { seedSum = 0; seedCount = 0; prev = null; continue; }
      if (prev == null) {
        seedSum += v; seedCount++;
        if (seedCount === signal) { prev = seedSum / signal; sig[i] = prev; hist[i] = v - prev; }
        continue;
      }
      prev = v * k + prev * (1 - k);
      sig[i] = prev; hist[i] = v - prev;
    }
    return { line: line, signal: sig, hist: hist };
  }

  /* Volume bars. A bar whose volume is not published returns null, never 0:
   * a drawn zero would read as a session that traded nothing. A real 0 stays 0. */
  function volume(bars) {
    return bars.map(function (b) {
      if (!b) return null;
      var v = b.v;
      if (v == null || v === "") return null;
      var n = Number(v);
      return isFinite(n) ? n : null;
    });
  }

  /* How many bars a window still needs, for an honest "nothing plotted" note. */
  function blankReason(name, need, have) {
    return name + " needs " + need + " bars, history has " + have;
  }

  var indicators = { sma: sma, ema: ema, bollinger: bollinger, rsi: rsi,
                     macd: macd, volume: volume, blankReason: blankReason };

  /* ------------------------------------------------------------ persistence - */

  /* Never destroys what it cannot read: an unparseable payload is copied aside
   * and a payload from a newer schema version is left alone. */
  function store() {
    var state = { loaded: false, readOnly: false, unreadable: false, raw: null };
    try {
      state.raw = root.localStorage.getItem(DRAW_KEY);
    } catch (e) { state.raw = null; }
    if (state.raw == null) { state.data = { v: DRAW_VER, keys: {} }; state.loaded = true; return state; }
    var parsed = null;
    try { parsed = JSON.parse(state.raw); } catch (e) { parsed = null; }
    if (!parsed || typeof parsed !== "object") {
      state.unreadable = true;
      try { root.localStorage.setItem(DRAW_KEY + "__unreadable", state.raw); } catch (e) {}
      state.data = { v: DRAW_VER, keys: {} };
      state.loaded = true;
      return state;
    }
    var ver = Number(parsed.v);
    if (isFinite(ver) && ver > DRAW_VER) {
      /* written by a newer build: do not touch it */
      state.readOnly = true;
      state.data = parsed;
      state.loaded = true;
      return state;
    }
    var src = (parsed.keys && typeof parsed.keys === "object") ? parsed.keys : {};
    var out = {};
    Object.keys(src).forEach(function (k) { if (Array.isArray(src[k])) out[k] = src[k]; });
    /* Migration: an earlier or flatter shape that put its per-security arrays at
     * the top level is adopted as security buckets rather than ignored. Nothing
     * a reader already had is dropped on the floor. */
    Object.keys(parsed).forEach(function (k) {
      if (k === "v" || k === "keys") return;
      if (Array.isArray(parsed[k]) && !out[k]) out[k] = parsed[k];
    });
    state.data = { v: DRAW_VER, keys: out };
    /* keep any other top level fields the schema may grow */
    Object.keys(parsed).forEach(function (k) {
      if (k !== "v" && k !== "keys" && !Array.isArray(parsed[k])) state.data[k] = parsed[k];
    });
    state.loaded = true;
    return state;
  }

  var ST = store();

  function save() {
    if (ST.readOnly) return false;
    try { root.localStorage.setItem(DRAW_KEY, JSON.stringify(ST.data)); return true; }
    catch (e) { return false; }
  }

  function itemsFor(key) {
    if (!ST.data.keys[key]) ST.data.keys[key] = [];
    return ST.data.keys[key];
  }

  function loadInds() {
    var d = { v: INDS_VER };
    try {
      var raw = root.localStorage.getItem(INDS_KEY);
      if (raw) {
        var p = JSON.parse(raw);
        if (p && typeof p === "object" && !(Number(p.v) > INDS_VER)) d = p;
      }
    } catch (e) {}
    return d;
  }
  function saveInds(obj) {
    try { obj.v = INDS_VER; root.localStorage.setItem(INDS_KEY, JSON.stringify(obj)); } catch (e) {}
  }

  /* ----------------------------------------------------------------- tools -- */

  var DEFAULTS = {
    trend: { color: "#33e29a", width: 2, dash: null },
    ray:   { color: "#4da6ff", width: 2, dash: null, extend: "right" },
    hline: { color: "#e0a340", width: 1, dash: null },
    vline: { color: "#9a9a9a", width: 1, dash: [4, 4] },
    zone:  { color: "#33e29a", width: 1, dash: null },
    /* The three a reader of a chart reaches for that this had no answer to: the
     * retracement levels between a high and a low, a note pinned to a bar, and
     * the distance between two points. */
    fib:     { color: "#c48bf7", width: 1, dash: null },
    text:    { color: "#f2f2f2", width: 1, dash: null },
    measure: { color: "#4dd4e8", width: 1, dash: [5, 4] },
    brush:   { color: "#f49ac2", width: 2, dash: null }
  };
  /* The retracement ladder, as every terminal draws it. 0 and 100 are the two
   * anchors themselves; the rest are the levels between them. */
  var FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  var SVG_NS = "http://www.w3.org/2000/svg";
  var seq = 0;
  function newId() { seq++; return "d" + Date.now().toString(36) + seq.toString(36); }

  function attach(opts) {
    opts = opts || {};
    var host = opts.host;
    if (!host) throw new Error("MXChartTools.attach needs a host element");

    var H = {
      chart: opts.chart || null,
      series: opts.series || null,
      host: host,
      key: opts.key || "",
      bars: opts.bars || [],
      times: opts.times || null,
      onChange: opts.onChange || null,
      tool: "none",
      /* THREE MODES, NOT THREE TOOLS. Magnet, lock and hide do not draw
       * anything: they change what drawing, dragging and painting do. Keeping
       * them out of H.tool is what lets a reader arm the trendline AND have the
       * magnet on, which is the only way either is useful. */
      magnet: false,
      locked: false,
      hidden: false,
      drag: null,
      handle: null,
      handleFrom: null,
      overlay: null,
      svg: null,
      ro: null,
      tsHandler: null,
      destroyed: false
    };

    /* --- overlay --- */
    var ov = document.createElement("div");
    ov.className = "mxta-overlay";
    ov.style.cssText = "position:absolute;inset:0;z-index:6;pointer-events:none;";
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.style.cssText = "display:block;overflow:hidden;pointer-events:none;";
    ov.appendChild(svg);
    host.appendChild(ov);
    H.overlay = ov; H.svg = svg;

    /* --- geometry --- */
    function timeIndex(t) {
      var key = String(t);
      if (H.times) {
        var i = H.times.indexOf(key);
        return i;
      }
      for (var j = 0; j < H.bars.length; j++) if (String(H.bars[j].t) === key) return j;
      return -1;
    }
    function offset() {
      if (!H.times || !H.bars.length) return 0;
      var o = H.times.indexOf(String(H.bars[0].t));
      return o < 0 ? 0 : o;
    }
    function logicalOf(t) {
      var i = timeIndex(t);
      if (i < 0) return null;
      return i - offset();
    }
    function ts() { return H.chart ? H.chart.timeScale() : null; }
    function coordXFromLogical(li) {
      var T = ts();
      if (!T || li == null) return null;
      var x = null;
      try { x = T.logicalToCoordinate(li); } catch (e) { x = null; }
      if (x == null) { return null; }
      return x;
    }
    function xyOf(anchor) {
      if (!anchor) return null;
      var li = logicalOf(anchor.t);
      if (li == null) return null;
      var x = coordXFromLogical(li);
      var y = null;
      try { y = H.series ? H.series.priceToCoordinate(anchor.p) : null; } catch (e) { y = null; }
      if (x == null || y == null) return null;
      return { x: x, y: y };
    }
    function snap(px, py) {
      var T = ts();
      var li = null;
      try { li = T ? T.coordinateToLogical(px) : null; } catch (e) { li = null; }
      var n = H.times ? H.times.length : H.bars.length;
      var idx = (li == null) ? 0 : Math.round(li) + offset();
      if (idx < 0) idx = 0;
      if (idx > n - 1) idx = n - 1;
      var t = H.times ? H.times[idx] : (H.bars[idx] ? H.bars[idx].t : null);
      var p = null;
      try { p = H.series ? H.series.coordinateToPrice(py) : null; } catch (e) { p = null; }
      if (t == null || p == null || !isFinite(p)) return null;
      /* MAGNET. The point lands on the nearest of that bar's own open, high,
       * low or close rather than wherever the pixel fell. A level drawn off a
       * high should BE the high: eyeballing it leaves a line a few cents out,
       * which is the difference between a level that reads and one that does
       * not. The bar is the one the x already resolved to, so the snap never
       * moves the drawing sideways, only onto a price the bar actually traded. */
      if (H.magnet) {
        /* idx indexes TIMES, the whole published series. H.bars is only what is
         * on screen, and the two differ by offset(): reading H.bars[idx] picked
         * a bar from the wrong part of the series whenever the chart was not
         * showing its very start, which on any range but ALL is always. */
        var bar = H.bars && H.bars[idx - offset()];
        if (bar) {
          var cands = [bar.o, bar.h, bar.l, bar.c].filter(function (v) {
            return v != null && isFinite(v);
          });
          var bestP = null, bestD = Infinity;
          for (var ci = 0; ci < cands.length; ci++) {
            var d = Math.abs(Number(cands[ci]) - p);
            if (d < bestD) { bestD = d; bestP = Number(cands[ci]); }
          }
          if (bestP != null) p = bestP;
        }
      }
      return { t: t, p: p };
    }
    function localPoint(ev) {
      var r = host.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    }

    /* --- painting --- */
    function el(tag, attrs) {
      var n = document.createElementNS(SVG_NS, tag);
      Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
      return n;
    }
    function paint() {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      if (!H.chart || !H.series) return;
      /* HIDE. The drawings are still there and still saved; they are simply not
       * painted, so a reader can look at the bare price for a moment without
       * throwing away the work. */
      if (H.hidden) return;
      var w = host.clientWidth, h = host.clientHeight;
      var list = itemsFor(H.key);
      for (var i = 0; i < list.length; i++) paintItem(list[i], w, h, false);
      if (H.drag) paintItem(H.drag.preview, w, h, true);
    }
    function dashAttr(d) { return d ? (d.join(",")) : "none"; }

    /* The right-hand end of a ray. ONE function, used by both the painter and
     * the hit test: a ray is drawn out to the right edge, and the part that is
     * drawn has to be the part that can be clicked, or the erase tool silently
     * misses the last stretch of the line it just drew. */
    function rayEndXY(it) {
      var l1 = logicalOf(it.a.t), l2 = logicalOf(it.b.t);
      var T = ts();
      if (!T || l1 == null || l2 == null || l2 === l1) return null;
      var rightEdge = null;
      try { rightEdge = T.coordinateToLogical(host.clientWidth); } catch (e) { rightEdge = null; }
      if (rightEdge == null) return null;
      var endL = rightEdge + 80;
      if (!(endL > l2)) return null;
      var slope = (it.b.p - it.a.p) / (l2 - l1);
      var endP = it.b.p + slope * (endL - l2);
      var ex = coordXFromLogical(endL);
      var ey = null;
      try { ey = H.series ? H.series.priceToCoordinate(endP) : null; } catch (e) { ey = null; }
      if (ex == null || ey == null || !isFinite(ex) || !isFinite(ey) || Math.abs(ey) >= 1e6) return null;
      return { x: ex, y: ey };
    }

    function paintItem(it, w, h, ghost) {
      if (!it) return;
      var style = DEFAULTS[it.type] || DEFAULTS.trend;
      var color = it.color || style.color;
      var width = it.width || style.width;
      var g = el("g", { opacity: ghost ? "0.75" : "1" });
      g.setAttribute("data-id", it.id || "");

      if (it.type === "hline") {
        var y = null;
        try { y = H.series.priceToCoordinate(it.a.p); } catch (e) { y = null; }
        if (y == null) return;
        g.appendChild(el("line", { x1: 0, y1: y, x2: w, y2: y, stroke: color,
          "stroke-width": width, "stroke-dasharray": dashAttr(style.dash) }));
        var lab = el("text", { x: w - 4, y: y - 4, fill: color, "font-size": "9",
          "font-family": "Oxygen Mono, monospace", "text-anchor": "end" });
        lab.textContent = Number(it.a.p).toFixed(2);
        g.appendChild(lab);
      } else if (it.type === "vline") {
        var xv = coordXFromLogical(logicalOf(it.a.t));
        if (xv == null) return;
        g.appendChild(el("line", { x1: xv, y1: 0, x2: xv, y2: h, stroke: color,
          "stroke-width": width, "stroke-dasharray": dashAttr(style.dash) }));
      } else if (it.type === "fib") {
        /* Levels are measured from anchor a to anchor b, so dragging either end
         * re-measures the whole ladder. Each line runs the width of the chart
         * and carries its ratio and the price it sits at. */
        var fa = xyOf(it.a), fb = xyOf(it.b);
        if (!fa || !fb) return;
        var p0 = Number(it.a.p), p1 = Number(it.b.p);
        var xL = Math.min(fa.x, fb.x), xR = Math.max(fa.x, fb.x);
        FIB_LEVELS.forEach(function (lv) {
          var price = p0 + (p1 - p0) * lv;
          var yy = null;
          try { yy = H.series.priceToCoordinate(price); } catch (e) { yy = null; }
          if (yy == null) return;
          var edge = (lv === 0 || lv === 1);
          g.appendChild(el("line", { x1: xL, y1: yy, x2: w, y2: yy, stroke: color,
            "stroke-width": edge ? width + 0.5 : width,
            "stroke-dasharray": edge ? "" : "3 3", opacity: edge ? "1" : "0.75" }));
          var ft = el("text", { x: xL + 3, y: yy - 3, fill: color, "font-size": "9",
            "font-family": "Oxygen Mono, monospace" });
          ft.textContent = (lv * 100).toFixed(1).replace(/\.0$/, "") + "%  " + price.toFixed(2);
          g.appendChild(ft);
        });
        g.appendChild(el("line", { x1: fa.x, y1: fa.y, x2: fb.x, y2: fb.y, stroke: color,
          "stroke-width": 1, "stroke-dasharray": "2 3", opacity: "0.5" }));
        if (ghost) return void svg.appendChild(g);
        [[fa.x, fa.y, "a"], [fb.x, fb.y, "b"]].forEach(function (pt) {
          g.appendChild(el("rect", { x: pt[0] - 3.5, y: pt[1] - 3.5, width: 7, height: 7,
            fill: "#0a0a0a", stroke: color, "stroke-width": 1,
            "pointer-events": "auto", style: "cursor:move", class: "mxta-handle",
            "data-id": it.id || "", "data-end": pt[2] }));
        });
      } else if (it.type === "measure") {
        /* What moved, in price, in per cent, and over how many sessions. The
         * box is drawn from the two anchors so it reads like a selection. */
        var ma = xyOf(it.a), mb = xyOf(it.b);
        if (!ma || !mb) return;
        var dp = Number(it.b.p) - Number(it.a.p);
        var pct = Number(it.a.p) ? (dp / Number(it.a.p)) * 100 : 0;
        var ia = timeIndex(it.a.t), ib = timeIndex(it.b.t);
        var bars = (ia >= 0 && ib >= 0) ? Math.abs(ib - ia) : null;
        var up = dp >= 0;
        var mc = up ? "#33e29a" : "#f87171";
        g.appendChild(el("rect", { x: Math.min(ma.x, mb.x), y: Math.min(ma.y, mb.y),
          width: Math.abs(mb.x - ma.x), height: Math.abs(mb.y - ma.y),
          fill: hexA(mc, 0.10), stroke: mc, "stroke-width": 1,
          "stroke-dasharray": "5 4" }));
        g.appendChild(el("line", { x1: ma.x, y1: ma.y, x2: mb.x, y2: mb.y,
          stroke: mc, "stroke-width": 1 }));
        var mt = el("text", { x: (ma.x + mb.x) / 2, y: Math.min(ma.y, mb.y) - 5,
          fill: mc, "font-size": "10", "font-family": "Oxygen Mono, monospace",
          "text-anchor": "middle" });
        mt.textContent = (up ? "+" : "") + dp.toFixed(2) + "  " +
                         (up ? "+" : "") + pct.toFixed(2) + "%" +
                         (bars == null ? "" : "  " + bars + (bars === 1 ? " bar" : " bars"));
        g.appendChild(mt);
        if (ghost) return void svg.appendChild(g);
        [[ma.x, ma.y, "a"], [mb.x, mb.y, "b"]].forEach(function (pt) {
          g.appendChild(el("rect", { x: pt[0] - 3.5, y: pt[1] - 3.5, width: 7, height: 7,
            fill: "#0a0a0a", stroke: mc, "stroke-width": 1,
            "pointer-events": "auto", style: "cursor:move", class: "mxta-handle",
            "data-id": it.id || "", "data-end": pt[2] }));
        });
      } else if (it.type === "brush") {
        var bp = (it.pts || []).map(xyOf).filter(function (q) { return !!q; });
        if (bp.length < 2) return;
        g.appendChild(el("polyline", {
          points: bp.map(function (q) { return q.x.toFixed(1) + "," + q.y.toFixed(1); }).join(" "),
          fill: "none", stroke: color, "stroke-width": width,
          "stroke-linejoin": "round", "stroke-linecap": "round" }));
      } else if (it.type === "text") {
        /* A note pinned to a bar and a price, so it travels with the data
         * rather than with the pixels. */
        var tp = xyOf(it.a);
        if (!tp) return;
        var label = String(it.label == null ? "" : it.label);
        var tw = Math.max(18, label.length * 5.6 + 10);
        g.appendChild(el("rect", { x: tp.x, y: tp.y - 14, width: tw, height: 15,
          fill: "rgba(10,10,10,.82)", stroke: color, "stroke-width": 1, rx: 2,
          "pointer-events": "auto", style: "cursor:move", class: "mxta-handle",
          "data-id": it.id || "", "data-end": "a" }));
        var tt = el("text", { x: tp.x + 5, y: tp.y - 3.5, fill: color, "font-size": "10",
          "font-family": "Oxygen Mono, monospace" });
        tt.textContent = label;
        g.appendChild(tt);
      } else if (it.type === "zone") {
        var a = xyOf(it.a), b = xyOf(it.b);
        if (!a || !b) return;
        g.appendChild(el("rect", { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y),
          width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y),
          fill: hexA(color, 0.12), stroke: color, "stroke-width": width,
          "stroke-dasharray": dashAttr(style.dash) }));
        if (ghost) return void svg.appendChild(g);
        /* the two corners a zone is anchored on are grabbable like a line's ends */
        [[a.x, a.y, "a"], [b.x, b.y, "b"]].forEach(function (pt) {
          g.appendChild(el("rect", { x: pt[0] - 3.5, y: pt[1] - 3.5, width: 7, height: 7,
            fill: "#0a0a0a", stroke: color, "stroke-width": 1,
            "pointer-events": "auto", style: "cursor:move", class: "mxta-handle",
            "data-id": it.id || "", "data-end": pt[2] }));
        });
      } else {
        /* trend and ray: the line runs from anchor a through anchor b and, for a
         * ray, on to the right edge. The handles sit on the two ANCHORS, so
         * dragging one moves the data point the drawing is anchored on and not
         * the far end of the extension. */
        var p1 = xyOf(it.a), p2 = xyOf(it.b);
        if (!p1 || !p2) return;
        var x1 = p1.x, y1 = p1.y, x2 = p2.x, y2 = p2.y;
        if (it.type === "ray" || it.extend === "right") {
          var re = rayEndXY(it);
          if (re) { x2 = re.x; y2 = re.y; }
        }
        g.appendChild(el("line", { x1: x1, y1: y1, x2: x2, y2: y2, stroke: color,
          "stroke-width": width, "stroke-dasharray": dashAttr(style.dash) }));
        if (ghost) return void svg.appendChild(g);
        [[p1.x, p1.y, "a"], [p2.x, p2.y, "b"]].forEach(function (pt) {
          g.appendChild(el("rect", { x: pt[0] - 3.5, y: pt[1] - 3.5, width: 7, height: 7,
            fill: "#0a0a0a", stroke: color, "stroke-width": 1,
            /* the handles are the only part of the overlay that takes pointer
             * events while NO tool is armed (the overlay itself does not), so a
             * drawing can be reshaped without giving up pan and zoom */
            "pointer-events": "auto", style: "cursor:move", class: "mxta-handle",
            "data-id": it.id || "", "data-end": pt[2] }));
        });
      }
      svg.appendChild(g);
    }
    function hexA(hex, a) {
      var m = /^#([0-9a-f]{6})$/i.exec(hex);
      if (!m) return hex;
      var v = parseInt(m[1], 16);
      return "rgba(" + ((v >> 16) & 255) + "," + ((v >> 8) & 255) + "," + (v & 255) + "," + a + ")";
    }

    /* --- hit test for erase --- */
    function distToSegment(px, py, x1, y1, x2, y2) {
      var dx = x2 - x1, dy = y2 - y1;
      var len2 = dx * dx + dy * dy;
      var t = len2 ? ((px - x1) * dx + (py - y1) * dy) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      var cx = x1 + t * dx, cy = y1 + t * dy;
      return Math.hypot(px - cx, py - cy);
    }
    function hitTest(px, py) {
      var list = itemsFor(H.key), best = null, bestD = 9;
      for (var i = 0; i < list.length; i++) {
        var it = list[i], d = 1e9;
        if (it.type === "hline") {
          var y = null;
          try { y = H.series.priceToCoordinate(it.a.p); } catch (e) {}
          if (y != null) d = Math.abs(py - y);
        } else if (it.type === "vline") {
          var x = coordXFromLogical(logicalOf(it.a.t));
          if (x != null) d = Math.abs(px - x);
        } else if (it.type === "text") {
          /* A note is grabbed by its box, which hangs above and to the right of
           * the point it is pinned to. Without this the eraser could never
           * reach one, because the generic two-anchor test below reads it.b and
           * a note has no second anchor. */
          var tp = xyOf(it.a);
          if (tp) {
            var tw = Math.max(18, String(it.label || "").length * 5.6 + 10);
            d = (px >= tp.x - 3 && px <= tp.x + tw + 3 && py >= tp.y - 17 && py <= tp.y + 3) ? 0 : 1e9;
          }
        } else if (it.type === "brush") {
          /* The eraser has to reach any part of the stroke, so every segment of
           * it is tested, not just the two ends it is anchored by. */
          var bq = (it.pts || []).map(xyOf).filter(function (q) { return !!q; });
          for (var bi = 1; bi < bq.length; bi++) {
            d = Math.min(d, distToSegment(px, py, bq[bi - 1].x, bq[bi - 1].y, bq[bi].x, bq[bi].y));
          }
        } else if (it.type === "fib") {
          /* Any of its levels will do, and so will the line between the two
           * anchors: a reader aims at the band, not at one hairline. */
          var fa = xyOf(it.a), fb = xyOf(it.b);
          if (fa && fb) {
            var pA = Number(it.a.p), pB = Number(it.b.p);
            var xl = Math.min(fa.x, fb.x);
            for (var k = 0; k < FIB_LEVELS.length; k++) {
              var yy = null;
              try { yy = H.series.priceToCoordinate(pA + (pB - pA) * FIB_LEVELS[k]); } catch (e) { yy = null; }
              if (yy != null && px >= xl - 4) d = Math.min(d, Math.abs(py - yy));
            }
            d = Math.min(d, distToSegment(px, py, fa.x, fa.y, fb.x, fb.y));
          }
        } else {
          var a = xyOf(it.a), b = xyOf(it.b);
          if (a && b) {
            /* a ray is drawn out to the right edge: the clickable segment has to
             * be the drawn segment or the tail of the ray cannot be erased */
            if (it.type === "ray" || it.extend === "right") {
              var re = rayEndXY(it);
              if (re) b = re;
            }
            d = Math.min(distToSegment(px, py, a.x, a.y, b.x, b.y),
                         it.type === "zone" ? 6 : 1e9);
          }
          if (a && b && it.type === "zone") {
            /* a zone is removed by clicking inside it too */
            if (px >= Math.min(a.x, b.x) && px <= Math.max(a.x, b.x) &&
                py >= Math.min(a.y, b.y) && py <= Math.max(a.y, b.y)) d = 0;
          }
        }
        if (d < bestD) { bestD = d; best = it; }
      }
      return best;
    }

    /* --- interaction --- */
    /* The snapshot is a deep copy, because the items are mutated in place when
     * a handle is dragged: holding a reference would hand undo the same list it
     * is meant to restore. */
    var undoStack = [], redoStack = [], UNDO_MAX = 40;
    function snapshot() {
      try { return JSON.parse(JSON.stringify(itemsFor(H.key))); }
      catch (e) { return []; }
    }
    function pushUndo() {
      undoStack.push(snapshot());
      if (undoStack.length > UNDO_MAX) undoStack.shift();
      redoStack.length = 0;          // a new action ends the old redo branch
    }
    function restore(list) {
      ST.data.keys[H.key] = list || [];
      save(); paint();
      if (H.onChange) H.onChange(H);
    }

    function commit(item) {
      pushUndo();
      if (!item || !item.id) item.id = newId();
      itemsFor(H.key).push(item);
      if (!save()) { /* read-only schema: still show it for this session */ }
      redraw();
      if (H.onChange) H.onChange(H);
    }
    function removeItem(it) {
      var list = itemsFor(H.key);
      var i = list.indexOf(it);
      if (i >= 0) { pushUndo(); list.splice(i, 1); save(); redraw(); if (H.onChange) H.onChange(H); }
    }
    function onDown(ev) {
      if (H.tool === "none") return;
      var pt = localPoint(ev);
      ev.preventDefault(); ev.stopPropagation();
      try { ov.setPointerCapture(ev.pointerId); } catch (e) {}
      if (H.tool === "erase") {
        if (H.locked) return;
        var hit = hitTest(pt.x, pt.y);
        if (hit) removeItem(hit);
        return;
      }
      var a = snap(pt.x, pt.y);
      if (!a) return;
      if (H.tool === "hline" || H.tool === "vline") {
        commit({ type: H.tool, a: a, b: null });
        return;
      }
      if (H.tool === "brush") {
        /* Freehand. The stroke is kept as a list of anchors, each one a time
         * and a price, so it rides the chart when the reader pans or zooms
         * exactly as a trendline does. */
        H.drag = { start: a, startPt: pt, brush: true,
                   preview: { id: "preview", type: "brush", a: a, b: a, pts: [a] } };
        ev.preventDefault();
        redraw();
        return;
      }
      if (H.tool === "text") {
        /* The note is asked for once, where it is put. An empty answer plants
         * nothing rather than an empty box nobody can see to remove. */
        var said = null;
        try { said = window.prompt("Note for this point on the chart:", ""); } catch (e) { said = null; }
        said = (said == null ? "" : String(said)).trim().slice(0, 80);
        if (said) commit({ type: "text", a: a, b: null, label: said });
        return;
      }
      H.drag = { start: a, startPt: pt, preview: { id: "preview", type: H.tool, a: a, b: a } };
      ev.preventDefault();
      redraw();
    }
    function onMove(ev) {
      if (H.tool === "none") return;
      if (H.tool === "erase") {
        var p0 = localPoint(ev);
        ov.style.cursor = hitTest(p0.x, p0.y) ? "pointer" : "crosshair";
        return;
      }
      if (!H.drag) return;
      var pt = localPoint(ev);
      var b = snap(pt.x, pt.y);
      if (!b) return;
      if (H.drag.brush) {
        /* One point per few pixels, not one per event: a stroke recorded at
         * pointer resolution is thousands of anchors that all have to be
         * projected on every repaint. */
        var pts = H.drag.preview.pts;
        var last = pts[pts.length - 1];
        var lp = last ? xyOf(last) : null;
        if (!lp || Math.hypot(pt.x - lp.x, pt.y - lp.y) >= 4) pts.push(b);
        H.drag.preview.b = b;
        H.drag.lastPt = pt;
        redraw();
        return;
      }
      H.drag.preview.b = b;
      H.drag.lastPt = pt;
      redraw();
    }
    function onUp(ev) {
      if (H.tool === "none" || !H.drag) return;
      var d = H.drag; H.drag = null;
      try { ov.releasePointerCapture(ev.pointerId); } catch (e) {}
      var a = d.start, b = d.preview.b;
      var far = false;
      try {
        var pa = xyOf(a), pb = xyOf(b);
        far = !!(pa && pb && Math.hypot(pb.x - pa.x, pb.y - pa.y) > 4);
      } catch (e) { far = false; }
      if (d.brush) {
        var pts = d.preview.pts || [];
        if (pts.length > 1) commit({ type: "brush", a: pts[0], b: pts[pts.length - 1], pts: pts });
        else redraw();
        return;
      }
      if (far && b && (String(b.t) !== String(a.t) || Number(b.p) !== Number(a.p))) {
        commit({ type: d.preview.type, a: a, b: b });
      } else {
        redraw();
      }
    }

    function bindOverlay(on) {
      ov.style.pointerEvents = on ? "auto" : "none";
      ov.style.cursor = on ? (H.tool === "erase" ? "pointer" : "crosshair") : "default";
      if (on) {
        ov.addEventListener("pointerdown", onDown);
        ov.addEventListener("pointermove", onMove);
        ov.addEventListener("pointerup", onUp);
      } else {
        ov.removeEventListener("pointerdown", onDown);
        ov.removeEventListener("pointermove", onMove);
        ov.removeEventListener("pointerup", onUp);
        H.drag = null;
      }
    }

    /* --- reshaping a drawing -------------------------------------------------
     * The handles painted on a line's ends and a zone's corners are LIVE while
     * NO tool is armed: grab one and the anchor it belongs to follows the
     * pointer, snapped to the same bar and price a drawing is anchored on. The
     * overlay itself stays pointer-events:none, so panning and zooming under
     * the handles still belong to the chart.
     *
     * The pointer capture is taken on the SVG and not on the handle, because
     * every repaint replaces the handle elements and a capture on a replaced
     * element is released with it. */
    function handleDown(ev) {
      /* LOCK. A finished drawing stops being something the pointer can catch
       * by accident: no handle answers, so nothing moves. Erase is refused in
       * onDown for the same reason. */
      if (H.locked) return;
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      if (String(t.getAttribute("class") || "") !== "mxta-handle") return;
      var id = t.getAttribute("data-id"), end = t.getAttribute("data-end");
      var list = itemsFor(H.key), item = null;
      for (var i = 0; i < list.length; i++) if (list[i].id === id) { item = list[i]; break; }
      if (!item || !end) return;
      var pt = localPoint(ev);
      if (!snap(pt.x, pt.y)) return;
      ev.preventDefault(); ev.stopPropagation();
      H.handle = { item: item, end: end };
      H.handleFrom = { a: item.a ? { t: item.a.t, p: item.a.p } : null,
                       b: item.b ? { t: item.b.t, p: item.b.p } : null };
      try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
      ov.style.cursor = "move";
    }
    function handleMove(ev) {
      if (!H.handle) return;
      var pt = localPoint(ev), a = snap(pt.x, pt.y);
      if (!a) return;
      if (H.handle.end === "a") H.handle.item.a = a; else H.handle.item.b = a;
      ev.preventDefault();
      paint();
    }
    function handleUp(ev) {
      if (!H.handle) return;
      var it = H.handle.item, from = H.handleFrom, moved = false;
      try {
        function same(x, y) {
          if (!x && !y) return true;
          if (!x || !y) return false;
          return String(x.t) === String(y.t) && Number(x.p) === Number(y.p);
        }
        moved = !(same(it.a, from.a) && same(it.b, from.b));
      } catch (e) { moved = true; }
      H.handle = null; H.handleFrom = null;
      try { svg.releasePointerCapture(ev.pointerId); } catch (e) {}
      ov.style.cursor = H.tool === "none" ? "default" : (H.tool === "erase" ? "pointer" : "crosshair");
      paint();
      if (moved) {
        save();
        if (H.onChange) H.onChange(H);
      }
    }
    svg.addEventListener("pointerdown", handleDown);
    svg.addEventListener("pointermove", handleMove);
    svg.addEventListener("pointerup", handleUp);
    svg.addEventListener("pointercancel", handleUp);

    function onKey(ev) {
      if (ev.key === "Escape" && H.tool !== "none") {
        H.setTool("none");
        ev.stopPropagation();
      }
    }

    function tsSub() {
      if (!H.chart) return;
      if (H.tsHandler) { try { H.chart.timeScale().unsubscribeVisibleLogicalRangeChange(H.tsHandler); } catch (e) {} }
      H.tsHandler = function () { paint(); };
      try { H.chart.timeScale().subscribeVisibleLogicalRangeChange(H.tsHandler); } catch (e) {}
    }

    function redraw() { paint(); }

    H.setTool = function (name) {
      if (name === H.tool) {
        /* pressing the armed tool again disarms it */
        if (name !== "none") name = "none";
      }
      H.tool = name || "none";
      H.drag = null;
      bindOverlay(H.tool !== "none");
      paint();
      if (H.onChange) H.onChange(H);
      return H.tool;
    };
    H.toolName = function () { return H.tool; };
    /* Each returns the state it left behind, so a caller can paint its button
     * from the answer instead of keeping a second copy of the truth. */
    H.setMagnet = function (on) { H.magnet = !!on; return H.magnet; };
    H.magnetOn = function () { return !!H.magnet; };
    H.setLocked = function (on) {
      H.locked = !!on;
      if (H.locked) { H.handle = null; H.drag = null; }
      paint();
      if (H.onChange) H.onChange(H);
      return H.locked;
    };
    H.lockedOn = function () { return !!H.locked; };
    H.setHidden = function (on) {
      H.hidden = !!on;
      paint();
      if (H.onChange) H.onChange(H);
      return H.hidden;
    };
    H.hiddenOn = function () { return !!H.hidden; };
    H.redraw = redraw;
    H.items = function () { return itemsFor(H.key); };
    H.count = function () { return itemsFor(H.key).length; };
    H.removeById = function (id) {
      var list = itemsFor(H.key);
      for (var i = 0; i < list.length; i++) if (list[i].id === id) { removeItem(list[i]); return true; }
      return false;
    };
    H.clearAll = function () {
      pushUndo();
      ST.data.keys[H.key] = [];
      save(); paint();
      if (H.onChange) H.onChange(H);
    };
    /* ---- UNDO AND REDO -------------------------------------------------
     * Every drawing action was final: the only way back from a stray line was
     * to hunt it with the eraser, and the only way back from CLEAR ALL was to
     * draw the lot again. A stack of snapshots is enough here because a chart
     * holds tens of drawings, not thousands, and a snapshot is exact where
     * replaying inverse operations is a second thing to keep correct. */
    H.canUndo = function () { return undoStack.length > 0; };
    H.canRedo = function () { return redoStack.length > 0; };
    H.undo = function () {
      if (!undoStack.length) return false;
      redoStack.push(snapshot());
      restore(undoStack.pop());
      return true;
    };
    H.redo = function () {
      if (!redoStack.length) return false;
      undoStack.push(snapshot());
      restore(redoStack.pop());
      return true;
    };
    H.setContext = function (o) {
      o = o || {};
      if (o.chart) H.chart = o.chart;
      if (o.series) H.series = o.series;
      if (o.host && o.host !== H.host) {
        H.host = o.host;
        H.host.appendChild(ov);
      }
      if (o.key != null) H.key = o.key;
      if (o.bars) H.bars = o.bars;
      if (o.times !== undefined) H.times = o.times;
      if (o.onChange) H.onChange = o.onChange;
      tsSub();
      paint();
      if (H.onChange) H.onChange(H);
      return H;
    };
    H.destroy = function () {
      H.destroyed = true;
      bindOverlay(false);
      document.removeEventListener("keydown", onKey, true);
      if (H.deleted) return;
      svg.removeEventListener("pointerdown", handleDown);
      svg.removeEventListener("pointermove", handleMove);
      svg.removeEventListener("pointerup", handleUp);
      svg.removeEventListener("pointercancel", handleUp);
      H.handle = null; H.handleFrom = null;
      if (H.tsHandler && H.chart) { try { H.chart.timeScale().unsubscribeVisibleLogicalRangeChange(H.tsHandler); } catch (e) {} }
      H.tsHandler = null;
      try { if (ov.parentNode) ov.parentNode.removeChild(ov); } catch (e) {}
      if (H.ro) { try { H.ro.disconnect(); } catch (e) {} }
      H.deleted = true;
    };

    /* keep the overlay the same size as the chart box without a resize event */
    if (typeof ResizeObserver !== "undefined") {
      H.ro = new ResizeObserver(function () { paint(); });
      try { H.ro.observe(host); } catch (e) {}
    }

    tsSub();
    document.addEventListener("keydown", onKey, true);
    paint();
    return H;
  }

  var api = {
    attach: attach,
    indicators: indicators,
    DRAW_KEY: DRAW_KEY,
    INDS_KEY: INDS_KEY,
    loadInds: loadInds,
    saveInds: saveInds,
    drawingsReadOnly: function () { return !!ST.readOnly; },
    drawingsUnreadable: function () { return !!ST.unreadable; },
    reloadStore: function () { ST = store(); return ST; }
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MXChartTools = api;
})(typeof window !== "undefined" ? window : this);
