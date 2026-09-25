#!/usr/bin/env python3
"""tv_backfill.py - backfill all securities' candlesticks from TradingView.

Fetches daily OHLCV (full available range) from TradingView's public websocket
for every NSE/NGX/JSE/EGX security, writes <file>.json (daily) + <file>.max.json
(monthly aggregate), matching the file naming the chart panel already reads.

The 22 NSE tickers already covered DEEPER by the official IR feed (ir.nse.co.ke,
2008+) are skipped by default so the deeper official history is not clobbered by
TradingView's shallower 2012+ range. Pass --all to override.

Resumable: a symbol whose daily file already has >= 1500 daily bars is skipped
unless --force is given.
"""
import json, os, sys, time, random, string, datetime
import websocket
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

TV_EX = {"NSE": "NSEKE", "NGX": "NSENG", "JSE": "JSE", "EGX": "EGX"}
NSE_IR_COVERED = set("SCOM EABL COOP NCBA SCBK SBIC KNRE NMG CIC FMLY AMAC KPC BKG NSE".split())
FORCE = "--force" in sys.argv
ALL = "--all" in sys.argv

def tv_symbol(ex, code):
    return TV_EX[ex] + ":" + code

def out_paths(ex, code):
    if ex == "NSE":
        daily = f"NSE_{code}.json"
    elif ex == "NGX":
        daily = f"NGX_{code}.json"
    elif ex == "JSE":
        daily = f"{code}.JO.json"
    else:
        daily = f"{code}.CA.json"
    dp = os.path.join(HIST, daily)
    return dp, dp[:-5] + ".max.json"

def fetch_tv(full_symbol, count=20000, timeout=40):
    ws = websocket.create_connection(
        "wss://data.tradingview.com/socket.io/websocket",
        timeout=25,
        header=["Origin: https://www.tradingview.com"]
    )
    session = "cs_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    def send(func, params):
        msg = json.dumps({"m": func, "p": params}, separators=(",", ":"))
        ws.send("~m~" + str(len(msg)) + "~m~" + msg)
    send("set_auth_token", ["unauthorized_user_token"])
    send("chart_create_session", [session, ""])
    send("resolve_symbol", [session, "sds_sym_1", '={"symbol":"' + full_symbol + '","adjustment":"splits"}'])
    send("create_series", [session, "sds_1", "s1", "sds_sym_1", "1D", count, ""])
    bars = []
    err = None
    buf = ""
    deadline = time.time() + timeout
    done = False
    while time.time() < deadline and not done:
        try:
            ws.settimeout(8)
            buf += ws.recv()
        except Exception:
            break
        while "~m~" in buf:
            a = buf.find("~m~")
            b = buf.find("~m~", a + 3)
            if b == -1:
                break
            try:
                ln = int(buf[a+3:b])
            except ValueError:
                buf = buf[b+3:]
                continue
            payload = buf[b+3:b+3+ln]
            if len(payload) < ln:
                break
            buf = buf[b+3+ln:]
            try:
                m = json.loads(payload)
            except Exception:
                continue
            mm = m.get("m")
            if mm == "symbol_error":
                err = "symbol_error:" + json.dumps(m.get("p", []))[:120]
                done = True
            elif mm == "timescale_update":
                p = m.get("p", [])
                if len(p) >= 2 and isinstance(p[1], dict):
                    for node in p[1].values():
                        if isinstance(node, dict) and isinstance(node.get("s"), list):
                            for item in node["s"]:
                                v = item.get("v")
                                if isinstance(v, list) and len(v) >= 6:
                                    bars.append({"t": v[0], "o": v[1], "h": v[2], "l": v[3], "c": v[4], "v": v[5]})
            elif mm == "series_completed":
                done = True
    ws.close()
    return bars, err

def to_iso(ts):
    return datetime.datetime.fromtimestamp(float(ts), datetime.UTC).strftime("%Y-%m-%d")

def clean_bar(iso, o, h, l, c, v):
    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    o, h, l, c, v = f(o), f(h), f(l), f(c), f(v)
    if None in (o, h, l, c):
        return None
    return {"t": iso, "o": o, "h": h, "l": l, "c": c, "v": v or 0}

def aggregate_monthly(bars):
    # bars: list of {t(iso),o,h,l,c,v} sorted by date
    months, order = {}, []
    for b in bars:
        k = b["t"][:7]
        if k not in months:
            months[k] = {"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": 0}
            order.append(k)
        m = months[k]
        m["h"] = max(m["h"], b["h"])
        m["l"] = min(m["l"], b["l"])
        m["c"] = b["c"]
        m["v"] += b["v"]
        m["t"] = b["t"]  # last bar's date in the month
    return [months[k] for k in order]

def process(ex, code):
    dp, mp = out_paths(ex, code)
    if not FORCE:
        try:
            d = json.load(open(dp, encoding="utf-8"))
            if len(d.get("bars", [])) >= 1500:
                return ex, code, "skip", "already deep"
        except Exception:
            pass
    for attempt in range(2):
        try:
            bars, err = fetch_tv(tv_symbol(ex, code))
            if err:
                return ex, code, "fail", err
            if not bars:
                return ex, code, "fail", "no data"
            iso_bars = []
            seen = set()
            for b in bars:
                iso = to_iso(b["t"])
                if iso in seen:
                    continue
                seen.add(iso)
                cb = clean_bar(iso, b["o"], b["h"], b["l"], b["c"], b["v"])
                if cb:
                    iso_bars.append(cb)
            iso_bars.sort(key=lambda x: x["t"])
            if len(iso_bars) < 2:
                return ex, code, "fail", f"only {len(iso_bars)} bars"
            # safety: never clobber a deeper existing file with a shallower fetch
            try:
                prev = json.load(open(dp, encoding="utf-8")).get("bars", [])
                if len(prev) > len(iso_bars):
                    return ex, code, "skip", f"existing {len(prev)} > tv {len(iso_bars)}"
            except Exception:
                pass
            json.dump({"sym": os.path.basename(dp)[:-5], "bars": iso_bars}, open(dp, "w", encoding="utf-8"), ensure_ascii=False)
            json.dump({"sym": os.path.basename(mp)[:-5], "bars": aggregate_monthly(iso_bars)}, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
            return ex, code, "ok", f"{len(iso_bars)} bars {iso_bars[0]['t']}->{iso_bars[-1]['t']}"
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
            else:
                return ex, code, "fail", str(e)[:80]
    return ex, code, "fail", "retries"

def load_targets():
    stocks = json.load(open(os.path.join(BASE, "stocks.json"), encoding="utf-8"))["stocks"]
    targets = []
    for ex in ("NSE", "NGX", "JSE", "EGX"):
        for s in stocks.get(ex, []):
            if ex == "JSE":
                code = s.get("code") or (s.get("sym", "").split(".")[0])
                if not code:
                    continue
            elif ex == "EGX":
                # EGX frontend fetches by ISIN (sym = EGS...CA), not ticker.
                code = (s.get("sym") or "").split(".")[0] or s.get("ticker") or s.get("short")
                if not code:
                    continue
            else:
                code = s.get("ticker")
                if not code:
                    continue
            if ex == "NSE" and not ALL and code in NSE_IR_COVERED:
                continue
            targets.append((ex, code))
    return targets

def main():
    targets = load_targets()
    print(f"{len(targets)} securities to fetch (8 threads)", flush=True)
    ok = fail = skip = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(process, t[0], t[1]): t for t in targets}
        for fut in as_completed(futs):
            e, c, st, msg = fut.result()
            if st == "ok":
                ok += 1
            elif st == "skip":
                skip += 1
            else:
                fail += 1
                print(f"  FAIL {e}:{c} - {msg}", flush=True)
            if (ok + fail + skip) % 50 == 0:
                print(f"  ... progress: {ok} ok, {fail} fail, {skip} skip", flush=True)
    print(f"\nDONE: {ok} ok, {fail} fail, {skip} skip", flush=True)

if __name__ == "__main__":
    main()
