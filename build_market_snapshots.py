#!/usr/bin/env python3
"""build_market_snapshots.py - rebuild market_<EX>.json for ALL exchanges
from the per-security history files (max range = since IPO).

For every listing with a history file, this produces:
  sym, ticker, name, price (latest close), chgPct (vs prev close),
  volume (latest), w52High, w52Low (from bars), ipo (first bar date),
  currency, sector, instrument.

Securities with NO history file (NGX/NSE + structured notes) keep their
existing snapshot row if present, else are listed with price=null.
"""
import json, os, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static_data")
HIST = os.path.join(STATIC, "history")

# widest credible one-day move per exchange - see rebuild_heatmaps.py. A move
# past the cap means the previous close came from a different price scale
# (cents vs currency units, or an unadjusted split), not a real session.
MAX_MOVE = {"JSE": 50.0, "EGX": 25.0, "NGX": 15.0, "NSE": 15.0}


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def num(v):
    """NGX price lists carry volumes as '227,596' strings"""
    if v is None or isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def hist_base(ex, sym):
    """NGX/NSE history files are written NGX_MTNN.json / NSE_SCOM.json, not by
    the raw listing symbol - the chart panel resolves them the same way."""
    safe = sym.replace("/", "_")
    if ex in ("NGX", "NSE"):
        return f"{ex}_{safe.split('.')[0]}"
    return safe


def bar_epoch(t):
    """bars carry epoch seconds (Yahoo) or 'YYYY-MM-DD' (NGX/NSE feeds)"""
    if isinstance(t, (int, float)):
        return int(t)
    try:
        return int(datetime.datetime.strptime(str(t)[:10], "%Y-%m-%d")
                   .replace(tzinfo=datetime.timezone.utc).timestamp())
    except Exception:
        return None

def iso_date(t):
    """bar timestamp (epoch or 'YYYY-MM-DD') -> the session date it belongs to"""
    e = bar_epoch(t)
    return datetime.datetime.utcfromtimestamp(e).strftime("%Y-%m-%d") if e else None


def fmt_short(v):
    """compact display number (volume / turnover / market cap)"""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    for lim, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= lim:
            return f"{x / lim:.2f}".rstrip("0").rstrip(".") + suf
    return f"{x:,.0f}"


def parse_short(s):
    """'86.31B' / '40,350' -> float"""
    if s is None:
        return None
    x = str(s).strip()
    mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}.get(x[-1:].upper(), 1)
    if mult != 1:
        x = x[:-1]
    v = num(x)
    return None if v is None else v * mult


def reconcile(row, ex):
    """Make one row tell ONE story.

    Every field on the market panel is read by a human as describing the same
    session, so a row assembled from several fetches of different dates prints
    nonsense: EGX rows carried a price from one day next to a stale previous
    close, a market cap computed from a price two years old (CCAP showed 9.3B
    against 14.93 x 3.82B shares) and a 52-week range that EXCLUDED the printed
    price (CCAP: 2.2 - 5.91 around a 14.93 price). Values that cannot be tied to
    the row's own session are dropped, never guessed."""
    px = num(row.get("price"))
    pc = num(row.get("prevClose"))
    if pc is not None:
        # stored as a number now, so trim Yahoo's float noise (156.6300048828125)
        row["prevClose"] = round(pc, 4)

    # 1. day change is derived from the very two numbers the panel prints
    if px is not None and pc:
        row["chgPct"] = round((px - pc) / pc * 100, 4)
    elif row.get("chgPct") is not None and pc is None:
        row["chgPct"] = None          # no previous close, no day change

    # 2. an "open" that just restates the previous close is not an open print
    op = num(row.get("open"))
    if op is not None and pc is not None and abs(op - pc) < 1e-9:
        row.pop("open", None)

    # 3. market cap (and shares) must agree with the price on the row
    sh = num(row.get("sharesIssued"))
    if px is not None and sh:
        row["marketCap"] = fmt_short(px * sh)
    else:
        mc = parse_short(row.get("marketCap"))
        if mc is None or px is None or not sh or abs(mc - px * sh) / (px * sh) > 0.05:
            row.pop("marketCap", None)

    # 4. a 52-week range that does not contain today's price is not a range
    r52 = row.get("range52w")
    if r52:
        parts = [num(x) for x in str(r52).split("-")]
        if len(parts) != 2 or None in parts or px is None or not (parts[0] <= px <= parts[1]):
            hi, lo = num(row.get("w52High")), num(row.get("w52Low"))
            if hi and lo and lo <= px <= hi:
                row["range52w"] = f"{fmt_short(lo)} - {fmt_short(hi)}"
            else:
                row.pop("range52w", None)

    # 5. turnover: only when it reconciles with this row's own volume
    tv = parse_short(row.get("turnover"))
    vol = num(row.get("volume"))
    if tv is None or px is None or not vol or abs(tv - px * vol) / (px * vol) > 0.20:
        if ex in ("NGX", "EGX"):
            row.pop("turnover", None)
    return row


def build(ex):
    stocks = load_json(os.path.join(BASE, "stocks.json"))["stocks"].get(ex, [])
    # listings carry real prices for NGX/NSE (no Yahoo history there)
    listing = {}
    lp = os.path.join(STATIC, f"listing_{ex}.json")
    if os.path.exists(lp):
        for s in load_json(lp).get("stocks", []):
            sym = s.get("sym") or s.get("ticker")
            if sym:
                listing[sym] = s
    # the exchange-specific collectors (fetch_nse_official.py, the NGX price
    # lists) write richer rows than this builder knows about - open/high/low/
    # prevClose/turnover/marketCap. Carry those forward instead of flattening
    # market_NSE.json down to this builder's field set on every rebuild.
    prior = {}
    mp = os.path.join(STATIC, f"market_{ex}.json")
    if os.path.exists(mp):
        try:
            for r in load_json(mp).get("stocks", []):
                k = r.get("sym") or r.get("ticker")
                if k:
                    prior[k] = r
        except Exception:
            pass

    out_rows = []
    covered = 0
    for s in stocks:
        sym = s.get("sym") or s.get("ticker")
        row = {
            "sym": sym, "ticker": (s.get("ticker") or sym.split(".")[0]), "name": s.get("name"),
            "price": None, "chgPct": None, "volume": None,
            "w52High": None, "w52Low": None, "ipo": None,
            "currency": s.get("currency"), "sector": s.get("sector"),
            "instrument": s.get("instrument", "common"),
        }
        if sym:
            hb = hist_base(ex, sym)
            hf = os.path.join(HIST, hb + ".json")
            mf = os.path.join(HIST, hb + ".max.json")
            # DAILY first: the .max file holds MONTHLY bars, so deriving the
            # day change from it compares this month against last month and
            # the guard below then discards it as non-adjacent. Monthly is only
            # a fallback for securities with no daily history at all.
            src = hf if os.path.exists(hf) else (mf if os.path.exists(mf) else None)
            # 52W range MUST come from the daily file (same price scale);
            # the max file mixes scales across splits/corporate actions
            daily_src = hf if os.path.exists(hf) else None
            if src:
                try:
                    d = load_json(src)
                    bars = d.get("bars", [])
                    if bars:
                        last = bars[-1]
                        prev = bars[-2] if len(bars) > 1 else last
                        row["price"] = last["c"]
                        row["volume"] = num(last.get("v"))
                        # the session the price belongs to: shown on the panel so
                        # a frozen archive can never pass itself off as today
                        row["asOf"] = iso_date(last.get("t"))
                        # previous close from the SAME archive: the exchange's own
                        # PCLOSE column when the collector recorded it, else the
                        # exchange's reported change, else the adjacent bar
                        pc_bar = num(last.get("pc"))
                        if pc_bar is not None:
                            row["prevClose"] = pc_bar
                        elif last.get("chg") is not None:
                            try:
                                row["prevClose"] = round(last["c"] / (1 + float(last["chg"]) / 100), 4)
                            except (TypeError, ZeroDivisionError):
                                pass
                        elif prev.get("c") and len(bars) > 1:
                            t_last0, t_prev0 = bar_epoch(last.get("t")), bar_epoch(prev.get("t"))
                            if t_last0 and t_prev0 and 0 < (t_last0 - t_prev0) <= 5 * 86400:
                                row["prevClose"] = prev["c"]
                        # real opening print / value traded, when the exchange's own
                        # price list carried them (NGX); never derived from a close
                        oo = num(last.get("oo"))
                        if oo is not None:
                            row["open"] = oo
                        tv = num(last.get("tv"))
                        if tv is not None:
                            row["turnover"] = fmt_short(tv)
                        hb = num(last.get("h"))
                        lb = num(last.get("l"))
                        if hb is not None and hb > 0:
                            row["high"] = hb
                        if lb is not None and lb > 0:
                            row["low"] = lb
                        # only call it a DAY change when the two bars really are
                        # adjacent sessions - a gappy archive (NSE/NGX) would
                        # otherwise report a five-week move as today's move
                        t_last, t_prev = bar_epoch(last.get("t")), bar_epoch(prev.get("t"))
                        adjacent = (t_last is not None and t_prev is not None
                                    and 0 < (t_last - t_prev) <= 5 * 86400)
                        if last.get("chg") is not None:
                            # the session's own reported day change, recorded
                            # with the bar - correct even when the previous
                            # session is missing from the daily array
                            row["chgPct"] = last["chg"]
                        elif prev and prev.get("c") and last["c"] is not None and adjacent:
                            row["chgPct"] = round((last["c"] - prev["c"]) / prev["c"] * 100, 4)
                        t0 = bar_epoch(bars[0].get("t"))
                        if t0:
                            row["ipo"] = datetime.datetime.utcfromtimestamp(t0).strftime("%Y-%m-%d")
                        row["currency"] = d.get("currency") or row["currency"]
                        covered += 1
                    # 52W from daily bars (last 260), winsorized against
                    # Yahoo glitch bars (e.g. SBK 2025-03-31 low=227 with 109M vol)
                    if daily_src:
                        try:
                            db = load_json(daily_src).get("bars", [])
                            if db:
                                recent = db[-260:]
                                highs = [b["h"] for b in recent if b.get("h") is not None]
                                lows = [b["l"] for b in recent if b.get("l") is not None]
                                if lows:
                                    med = sorted(lows)[len(lows) // 2]
                                    lows = [x for x in lows if x > med * 0.5]
                                if highs:
                                    medh = sorted(highs)[len(highs) // 2]
                                    highs = [x for x in highs if x < medh * 2.0]
                                if highs:
                                    row["w52High"] = max(highs)
                                if lows:
                                    row["w52Low"] = min(lows)
                        except Exception:
                            pass
                except Exception:
                    pass
            # the exchange's own reported day change beats a recomputed one
            # whenever we could not prove the bars were adjacent sessions
            if row["chgPct"] is None and sym in listing and listing[sym].get("chgPct") is not None:
                row["chgPct"] = num(listing[sym].get("chgPct"))

            # NGX/NSE fallback: real prices from the listing snapshot
            if row["price"] is None and sym in listing:
                ls = listing[sym]
                # The listing's own date is the only date this price has. An
                # undated price printed under a dated board reads as today's
                # (DUNLOP, delisted Apr 2026, still showed 0.20), so it is dated
                # or dropped - never shown as current.
                ds = None
                for fmt in ("%b %d, %Y", "%Y-%m-%d"):
                    try:
                        ds = datetime.datetime.strptime(str(ls.get("date")), fmt).strftime("%Y-%m-%d")
                        break
                    except (ValueError, TypeError):
                        continue
                if ds:
                    row["price"] = ls.get("price")
                    row["chgPct"] = ls.get("chgPct")
                    row["volume"] = num(ls.get("volume"))
                    row["currency"] = ls.get("currency") or row["currency"]
                    row["asOf"] = ds
                    # the exchange's own change implies its own previous close,
                    # so the row still reconciles without a second fetch
                    try:
                        if row["price"] is not None and row.get("chgPct") is not None:
                            row["prevClose"] = round(float(row["price"]) / (1 + float(row["chgPct"]) / 100), 4)
                    except (TypeError, ZeroDivisionError):
                        pass
                    if row["price"] is not None:
                        covered += 1
                else:
                    row["priceNote"] = "no dated print in the official price list"
        cap = MAX_MOVE.get(ex, 50.0)
        if row["chgPct"] is not None and abs(row["chgPct"]) > cap:
            # honest gap beats a fabricated +9900%
            row["chgPct"] = None
            row["chgFlag"] = "suspect-baseline"
        # fresh values win; anything we could not compute keeps what the
        # exchange collector already established
        # carry forward only the fields this builder does not own. Price,
        # change and volume must come from this run's history/listing sources or
        # not at all - inheriting them resurrected a stale market-cap-as-price
        # value for UBN long after the bad bars were purged.
        OWNED = ("price", "chgPct", "volume", "w52High", "w52Low", "ipo", "chgFlag")
        if ex in ("NGX", "EGX"):
            # NGX/EGX rows were the ones assembled from several fetches at once:
            # an old previous close, an old market cap and an old turnover sat
            # next to a fresh price and read as one quote. Only this run's values
            # may survive, so a field with no fresh source simply disappears.
            OWNED = OWNED + ("asOf", "prevClose", "open", "turnover", "marketCap",
                             "range52w", "high", "low")
        merged = {k: v for k, v in prior.get(sym, {}).items() if k not in OWNED}
        merged.update({k: v for k, v in row.items() if v is not None})
        if row.get("chgPct") is None:
            merged["chgPct"] = row.get("chgPct") if "chgFlag" in row else merged.get("chgPct")
        if "chgFlag" in row:
            merged["chgFlag"] = row["chgFlag"]
        else:
            merged.pop("chgFlag", None)
        if ex in ("NGX", "EGX"):
            merged = reconcile(merged, ex)
        out_rows.append(merged)
    return out_rows, covered

def main():
    total = covered_total = 0
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        rows, covered = build(ex)
        # "asOf" is the DATA's session date, not the build time: the panel prints
        # it, and stamping a stale archive with "now" is what let the NGX board
        # show 28 Aug prices as if they were live on 10 Sep. "generated" keeps
        # the build time for the log.
        sessions = sorted({r.get("asOf") for r in rows if r.get("asOf")})
        with open(os.path.join(STATIC, f"market_{ex}.json"), "w", encoding="utf-8") as f:
            json.dump({"stocks": rows,
                       "asOf": sessions[-1] if sessions else None,
                       "sessionDays": len(sessions),
                       "generated": datetime.datetime.now().isoformat(),
                       "covered": covered}, f)
        oldest = min(sessions) if sessions else None
        print(f"{ex}: {covered}/{len(rows)} covered | sessions {oldest} .. {sessions[-1] if sessions else None} "
              f"({len(sessions)} distinct) -> market_{ex}.json")
        total += len(rows)
        covered_total += covered
    print(f"TOTAL: {covered_total}/{total}")

if __name__ == "__main__":
    main()
