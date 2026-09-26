#!/usr/bin/env python3
"""merge_nse_tv_depth.py - deepen NSE candle archives from TradingView.

Why: the NSE archive was built from ir.nse.co.ke (dead for 42 of 64 tickers) and
TradingView. For most securities disk already holds TV's full depth, but a few
traded long before the first bar we recorded (Homeboyz listed 2023-06 and disk
starts 2026-08). This fetches NSEKE:<SYM>, VERIFIES identity, and merges by date.

Safety rules (all enforced here):
  * verify before writing - the freshest TV bar must agree with our own last bar
    on date (same session or one apart) and close (within 1%). A symbol match is
    not identity; a reused ticker must not be allowed to inject foreign prices.
  * MERGE, never replace. Existing bars win, TV only fills dates we lack, so a
    deeper on-disk file is never clobbered by a shallower fetch.
  * write only when the merge actually ADDS bars.
  * back up each changed file to _bak_nse_tv_<ts>/.

Usage: python3 merge_nse_tv_depth.py [--apply] [SYM ...]
"""
import datetime, json, os, random, re, shutil, string, sys, time
from websocket import create_connection

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
URL = "wss://data.tradingview.com/socket.io/websocket"
HDR = {"Origin": "https://www.tradingview.com"}
APPLY = "--apply" in sys.argv


def frame(method, params):
    body = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return "~m~%d~m~%s" % (len(body), body)


def rf():
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(12))


def tv_bars(tkr, count=20000, timeout=30):
    """Return [{t:ISO, o,h,l,c}] from TradingView for NSEKE:<tkr>."""
    ws = create_connection(URL, header=HDR, timeout=timeout)
    cs = "cs_" + rf()
    try:
        ws.send(frame("set_auth_token", ["unauthorized_user_token"]))
        ws.send(frame("chart_create_session", [cs, ""]))
        ws.send(frame("resolve_symbol", [cs, "sds_sym_1",
                  '={"symbol":"NSEKE:%s","adjustment":"splits"}' % tkr]))
        ws.send(frame("create_series", [cs, "sds_1", "s1", "sds_sym_1", "1D", count, ""]))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = ws.recv()
            for part in re.split(r"~m~\d+~m~", raw):
                if not part.strip():
                    continue
                try:
                    m = json.loads(part)
                except Exception:
                    continue
                if m.get("m") == "symbol_error":
                    return [], "symbol_error"
                if m.get("m") == "timescale_update":
                    node = m["p"][1].get("sds_1") or {}
                    out = []
                    for b in (node.get("s") or []):
                        v = b.get("v") or []
                        if len(v) >= 5:
                            d = datetime.datetime.fromtimestamp(float(v[0]), datetime.timezone.utc).strftime("%Y-%m-%d")
                            out.append({"t": d, "o": float(v[1]), "h": float(v[2]),
                                        "l": float(v[3]), "c": float(v[4]),
                                        "v": int(float(v[5])) if len(v) > 5 else 0})
                    if out:
                        return out, None
                if m.get("m") == "series_completed":
                    return [], "no bars"
        return [], "timeout"
    finally:
        try:
            ws.close()
        except Exception:
            pass


def tv_name(tkr):
    """Resolve NSEKE:<tkr>'s description via TV symbol search (identity evidence)."""
    import urllib.request
    url = "https://symbol-search.tradingview.com/symbol_search/?text=%s&type=stock" % tkr
    hdrs = {"User-Agent": "Mozilla/5.0",
            "Referer": "https://www.tradingview.com/",
            "Origin": "https://www.tradingview.com"}
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=25).read().decode("utf-8", "replace")
        for r in json.loads(raw):
            if str(r.get("symbol", "")).upper() == tkr.upper():
                return r.get("description") or ""
    except Exception:
        return ""
    return ""


def norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def name_ok(tv_desc, our_name):
    """Similarity gate: a prepend must be the same issuer, not a reused ticker."""
    import difflib
    a, b = norm(tv_desc), norm(our_name)
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.80


def verify(ours, theirs):
    """Identity + honesty check. Returns (ok, reason)."""
    if not theirs:
        return False, "no tv bars"
    if not ours:
        return True, "disk empty, tv only"
    # prepend-only: every TV bar is strictly OLDER than our first bar. Nothing on
    # disk is touched, so the close check cannot apply (different dates); the
    # caller must confirm the issuer by name instead.
    if max(b["t"] for b in theirs) < str(ours[0].get("t"))[:10]:
        return True, "prepend"
    o_last, t_last = ours[-1], theirs[-1]
    od = str(o_last.get("t"))[:10]
    td = str(t_last.get("t"))[:10]
    try:
        gap = abs((datetime.date.fromisoformat(od) - datetime.date.fromisoformat(td)).days)
    except Exception:
        return False, "unparseable dates"
    if gap > 4:
        return False, "last bar dates differ (%s vs %s)" % (od, td)
    oc, tc = o_last.get("c"), t_last.get("c")
    if oc and tc:
        diff = abs(oc - tc) / max(abs(oc), 1e-9)
        if diff > 0.01:
            return False, "last close differs %.1f%% (%s vs %s)" % (diff * 100, oc, tc)
    return True, "ok"


def main():
    syms = [a for a in sys.argv[1:] if not a.startswith("--")]
    L = json.load(open(os.path.join(BASE, "static_data", "listing_NSE.json"), encoding="utf-8"))["stocks"]
    NAMES = {}
    for r in L:
        nm = str(r.get("sym") or r.get("ticker")).strip()
        NAMES[nm] = r.get("name") or ""
    if not syms:
        syms = sorted(NAMES)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(BASE, "_bak_nse_tv_%s" % ts)
    changed = []
    print("%-9s %6s %6s %6s  %-11s %-11s  %s" % ("SYM", "disk", "tv", "merged", "tv_first", "our_first", "verdict"))
    for s in syms:
        path = os.path.join(HIST, "NSE_%s.json" % s)
        ours = []
        if os.path.exists(path):
            try:
                ours = json.load(open(path, encoding="utf-8")).get("bars") or []
            except Exception:
                ours = []
        try:
            theirs, err = tv_bars(s)
        except Exception as e:
            print("%-9s %6d %6s %6s  %-11s %-11s  FETCH_ERR %s" % (s, len(ours), "-", "-", "-", "-", str(e)[:40]))
            continue
        if not theirs:
            print("%-9s %6d %6s %6s  %-11s %-11s  no tv data (%s)" % (s, len(ours), 0, "-", "-",
                  str(ours[0]['t'])[:10] if ours else "-", err))
            time.sleep(0.5)
            continue
        ok, why = verify(ours, theirs)
        if ok and why == "prepend":
            desc = tv_name(s)
            if not name_ok(desc, NAMES.get(s, "")):
                ok, why = False, "prepend unverified by name (tv=%r vs %r)" % (desc, NAMES.get(s, ""))
        if not ok:
            print("%-9s %6d %6d %6s  %-11s %-11s  REJECTED: %s" % (s, len(ours), len(theirs), "-",
                  theirs[0]["t"], str(ours[0]['t'])[:10] if ours else "-", why))
            time.sleep(0.5)
            continue
        merged = {str(b.get("t"))[:10]: b for b in ours if b.get("t")}
        before_n = len(merged)
        added = 0
        for b in theirs:
            if b["t"] not in merged:
                merged[b["t"]] = b
                added += 1
        bars = [merged[k] for k in sorted(merged)]
        verdict = "ok"
        if len(bars) > before_n:
            verdict = "DEEPENED +%d" % added
            if APPLY:
                os.makedirs(bak, exist_ok=True)
                shutil.copy2(path, os.path.join(bak, os.path.basename(path)))
                json.dump({"sym": s, "currency": "KES",
                           "source": "NSE official board snapshot + TradingView NSEKE",
                           "bars": bars},
                          open(path, "w", encoding="utf-8"), ensure_ascii=False)
        else:
            verdict = "already >= tv"
        print("%-9s %6d %6d %6d  %-11s %-11s  %s" % (s, len(ours), len(theirs), len(bars),
              theirs[0]["t"], str(ours[0]['t'])[:10] if ours else "-", verdict))
        if len(bars) > before_n:
            changed.append(s)
        time.sleep(0.6)
    print()
    print("series deepened: %d %s" % (len(changed), changed if changed else ""))
    if changed and not APPLY:
        print("DRY RUN - nothing written")
    elif changed and APPLY:
        print("backup dir: %s" % bak)


if __name__ == "__main__":
    main()
