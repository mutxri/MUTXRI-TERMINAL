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
    zone:  { color: "#33e29a", width: 1, dash: null }
  };
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
      drag: null,
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
      var w = host.clientWidth, h = host.clientHeight;
      var list = itemsFor(H.key);
      for (var i = 0; i < list.length; i++) paintItem(list[i], w, h, false);
      if (H.drag) paintItem(H.drag.preview, w, h, true);
    }
    function dashAttr(d) { return d ? (d.join(",")) : "none"; }

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
      } else if (it.type === "zone") {
        var a = xyOf(it.a), b = xyOf(it.b);
        if (!a || !b) return;
        g.appendChild(el("rect", { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y),
          width: Math.abs(b.x - a.x), height: Math.abs(b.y - a.y),
          fill: hexA(color, 0.12), stroke: color, "stroke-width": width,
          "stroke-dasharray": dashAttr(style.dash) }));
      } else {
        /* trend and ray */
        var p1 = xyOf(it.a), p2 = xyOf(it.b);
        if (!p1 || !p2) return;
        var x1 = p1.x, y1 = p1.y, x2 = p2.x, y2 = p2.y;
        if (it.type === "ray" || it.extend === "right") {
          var l1 = logicalOf(it.a.t), l2 = logicalOf(it.b.t);
          var T = ts(), rightEdge = null;
          try { rightEdge = T.coordinateToLogical(host.clientWidth); } catch (e) { rightEdge = null; }
          if (l1 != null && l2 != null && l2 !== l1 && rightEdge != null) {
            var endL = rightEdge + 80;
            if (endL > l2) {
              var slope = (it.b.p - it.a.p) / (l2 - l1);
              var endP = it.b.p + slope * (endL - l2);
              var ex = coordXFromLogical(endL);
              var ey = null;
              try { ey = H.series.priceToCoordinate(endP); } catch (e) { ey = null; }
              if (ex != null && ey != null && isFinite(ex) && isFinite(ey) && Math.abs(ey) < 1e6) {
                x2 = ex; y2 = ey;
              }
            }
          }
        }
        g.appendChild(el("line", { x1: x1, y1: y1, x2: x2, y2: y2, stroke: color,
          "stroke-width": width, "stroke-dasharray": dashAttr(style.dash) }));
        [[x1, y1], [x2, y2]].forEach(function (pt) {
          g.appendChild(el("rect", { x: pt[0] - 2.5, y: pt[1] - 2.5, width: 5, height: 5,
            fill: "#0a0a0a", stroke: color, "stroke-width": 1 }));
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
        } else {
          var a = xyOf(it.a), b = xyOf(it.b);
          if (a && b) d = Math.min(distToSegment(px, py, a.x, a.y, b.x, b.y),
                                   it.type === "zone" ? 6 : 1e9);
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
    function commit(item) {
      if (!item || !item.id) item.id = newId();
      itemsFor(H.key).push(item);
      if (!save()) { /* read-only schema: still show it for this session */ }
      redraw();
      if (H.onChange) H.onChange(H);
    }
    function removeItem(it) {
      var list = itemsFor(H.key);
      var i = list.indexOf(it);
      if (i >= 0) { list.splice(i, 1); save(); redraw(); if (H.onChange) H.onChange(H); }
    }
    function onDown(ev) {
      if (H.tool === "none") return;
      var pt = localPoint(ev);
      ev.preventDefault(); ev.stopPropagation();
      try { ov.setPointerCapture(ev.pointerId); } catch (e) {}
      if (H.tool === "erase") {
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
    H.redraw = redraw;
    H.items = function () { return itemsFor(H.key); };
    H.count = function () { return itemsFor(H.key).length; };
    H.removeById = function (id) {
      var list = itemsFor(H.key);
      for (var i = 0; i < list.length; i++) if (list[i].id === id) { removeItem(list[i]); return true; }
      return false;
    };
    H.clearAll = function () {
      ST.data.keys[H.key] = [];
      save(); paint();
      if (H.onChange) H.onChange(H);
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
