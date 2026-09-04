#!/usr/bin/env python3
"""bot/market.py - the financial state of every exchange in the terminal.

Consolidates what the existing collectors already write to static_data into one
snapshot the bot (and the panel) can read in a single fetch: per-exchange
breadth, movers, index levels, plus the cross-asset context - FX, sovereign
yields and commodities - that explains most frontier-market moves.

This module reads only; the upstream collectors stay the single writers of
their own files. Anything missing on disk is reported as missing, not faked.
"""
import datetime as dt, json, os

from . import universe as U

SD = U.SD


def _load(name, default=None):
    p = os.path.join(SD, name)
    if not os.path.exists(p):
        return default, False
    try:
        return json.load(open(p, encoding="utf-8")), True
    except Exception:
        return default, False


def _num(v):
    """Coerce the mixed str/float shapes the collectors emit."""
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


# Daily-limit sanity bound. NSE/NGX cap moves at 10% and EGX at 20%; the JSE has
# no formal limit but real single-day moves past this are vanishingly rare. A few
# upstream rows carry a stale or zero prevClose and print moves like +9900%, so
# they are excluded from statistics and counted in `suspectRows` instead of
# quietly poisoning the average.
SANE_CHG_PCT = 35.0


def _sane_rows(stocks):
    """Split rows into usable and suspect.

    Two ways a row lands in `suspect`: it still carries an implausible move, or
    bot/universe.py already nulled one and left `chgFlag`. Reading the flag keeps
    the count honest - without it the exclusions became invisible the moment the
    sanitising moved upstream, and the panel would report a clean board while
    quietly dropping rows.
    """
    good, suspect = [], []
    for s in stocks:
        c = _num(s.get("chgPct"))
        flagged = bool(s.get("chgFlag"))
        if flagged or (c is not None and abs(c) > SANE_CHG_PCT):
            suspect.append({"ticker": s.get("ticker") or s.get("sym"),
                            "name": s.get("name"), "chgPct": c,
                            "reason": s.get("chgFlag") or "implausible one-day move",
                            "price": _num(s.get("price"))})
            if flagged and c is None:
                # The value is already withheld, so the row is still usable for
                # everything that does not depend on the day change.
                good.append(s)
        else:
            good.append(s)
    return good, suspect


def _median(xs):
    if not xs:
        return None
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _trimmed_mean(xs, trim=0.1):
    """Mean with the tails dropped.

    The plain mean is hostage to one mispriced small cap; the median is
    structurally 0 on boards where most traded lines close unchanged. Trimming
    10% off each tail keeps a statistic that both survives outliers and still
    moves when the market does.
    """
    if not xs:
        return None
    xs = sorted(xs)
    k = int(len(xs) * trim)
    core = xs[k:len(xs) - k] or xs
    return sum(core) / len(core)


def breadth(stocks):
    """Advance/decline and turnover stats - the fastest read on a session."""
    rows, suspect = _sane_rows(stocks)
    adv = dec = unch = 0
    traded, chgs, traded_chgs = 0, [], []
    for s in rows:
        c = _num(s.get("chgPct"))
        v = _num(s.get("volume")) or 0
        did_trade = v > 0
        if did_trade:
            traded += 1
        if c is None:
            continue
        chgs.append(c)
        if did_trade:
            traded_chgs.append(c)
        if c > 0:
            adv += 1
        elif c < 0:
            dec += 1
        else:
            unch += 1
    avg = round(sum(chgs) / len(chgs), 3) if chgs else None
    # These boards carry many listings that do not trade on a given day, so a
    # median across every line is structurally 0 and says nothing. Tone is read
    # off the rows that actually traded - the market that was open for business.
    med_traded = _median(traded_chgs)
    avg_traded = (round(sum(traded_chgs) / len(traded_chgs), 3)
                  if traded_chgs else None)
    trim_traded = _trimmed_mean(traded_chgs)
    ref = trim_traded if trim_traded is not None else (avg_traded or avg or 0)
    return {
        "advancers": adv, "decliners": dec, "unchanged": unch,
        "traded": traded, "listed": len(stocks),
        "avgChgPct": avg,
        "avgTradedChgPct": avg_traded,
        "medianTradedChgPct": round(med_traded, 3) if med_traded is not None else None,
        "trimmedTradedChgPct": round(trim_traded, 3) if trim_traded is not None else None,
        "advDeclRatio": round(adv / dec, 2) if dec else (float(adv) if adv else 0.0),
        "tone": "risk-on" if ref > 0.2 else ("risk-off" if ref < -0.2 else "mixed"),
        "suspectRows": suspect,
    }


def movers(stocks, n=5):
    """Top gainers/losers and most active, computed from the merged board."""
    sane, _suspect = _sane_rows(stocks)
    rows = [s for s in sane if _num(s.get("chgPct")) is not None]
    rows.sort(key=lambda s: -_num(s["chgPct"]))

    def slim(s):
        return {"ticker": s.get("ticker") or s.get("sym"), "name": s.get("name"),
                "sector": s.get("sector"), "price": _num(s.get("price")),
                "chgPct": _num(s.get("chgPct")), "volume": _num(s.get("volume"))}

    active = sorted(rows, key=lambda s: -(_num(s.get("volume")) or 0))
    return {"gainers": [slim(s) for s in rows[:n]],
            "losers": [slim(s) for s in rows[::-1][:n]],
            "mostActive": [slim(s) for s in active[:n]]}


def sector_table(stocks):
    """Equal-weight sector performance - where the money actually moved."""
    agg = {}
    sane, _suspect = _sane_rows(stocks)
    for s in sane:
        c = _num(s.get("chgPct"))
        sec = s.get("sector") or "Unclassified"
        if c is None:
            continue
        a = agg.setdefault(sec, {"sector": sec, "n": 0, "sum": 0.0})
        a["n"] += 1
        a["sum"] += c
    out = [{"sector": a["sector"], "count": a["n"], "avgChgPct": round(a["sum"] / a["n"], 3)}
           for a in agg.values() if a["n"]]
    out.sort(key=lambda x: -x["avgChgPct"])
    return out


def cross_asset():
    """FX, sovereign yields and commodities that frame the local markets."""
    out = {"missing": []}

    idx, ok = _load("indices.json")
    if ok and idx:
        out["asOf"] = idx.get("asOf")
        out["indices"] = [{"label": e.get("label"), "market": e.get("market"),
                           "price": _num(e.get("price")), "changePct": _num(e.get("changePct")),
                           "currency": e.get("currency")}
                          for e in idx.get("entries", []) if e.get("kind") == "index"]
    else:
        out["missing"].append("indices.json")

    com, ok = _load("commodities.json")
    if ok and com:
        out["commodities"] = [{"name": c.get("name"), "sym": c.get("sym"),
                               "price": _num(c.get("price")), "chgPct": _num(c.get("chgPct")),
                               "unit": c.get("unit"), "africa": c.get("africa")}
                              for c in com.get("commodities", [])]
    else:
        out["missing"].append("commodities.json")

    bnd, ok = _load("bonds.json")
    if ok and bnd:
        rows = []
        for c in bnd.get("countries", []):
            for i in c.get("instruments", []):
                rows.append({"country": c.get("country"), "iso": c.get("iso"),
                             "name": i.get("name"), "tenor": i.get("tenor"),
                             "yield": _num(i.get("yield")), "asOf": i.get("as_of"),
                             "stale": bool(i.get("stale"))})
        out["yields"] = rows
    else:
        out["missing"].append("bonds.json")

    fx, ok = _load("fx.json")
    if ok and fx:
        out["fx"] = {"currencies": [c.get("code") for c in fx.get("currencies", [])],
                     "matrix": fx.get("matrix", [])[:12]}
    else:
        out["missing"].append("fx.json")
    return out


def snapshot():
    """Full financial state across all four exchanges plus cross-asset context."""
    uni = U.load()
    exchanges, missing = {}, []
    for ex in U.EXCHANGES:
        secs = uni.get(ex)
        if not secs:
            missing.append(ex)
            continue
        summ, _ok = _load("ex_%s_summary.json" % ex, {})
        block = {
            "exchange": ex,
            "name": U.EX_META[ex]["name"],
            "country": U.EX_META[ex]["country"],
            "currency": U.EX_META[ex]["currency"],
            "asOf": (summ or {}).get("asOf"),
            "breadth": breadth(secs),
            "movers": movers(secs),
            "sectors": sector_table(secs),
        }
        exchanges[ex] = block
    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "exchanges": exchanges,
        "missingExchanges": missing,
        "crossAsset": cross_asset(),
    }


if __name__ == "__main__":
    s = snapshot()
    for ex, b in s["exchanges"].items():
        br = b["breadth"]
        print("%s %-28s adv %3d / dec %3d | traded %3d avg %+0.2f%% med %+0.2f%% -> %-8s (suspect %d)"
              % (ex, b["name"], br["advancers"], br["decliners"], br["traded"],
                 br["avgTradedChgPct"] or 0, br["trimmedTradedChgPct"] or 0,
                 br["tone"], len(br["suspectRows"])))
        print("   top:", ", ".join("%s %+0.1f%%" % (g["ticker"], g["chgPct"] or 0)
                                   for g in b["movers"]["gainers"][:3]))
    ca = s["crossAsset"]
    print("cross-asset: %d indices, %d commodities, %d yield points; missing=%s"
          % (len(ca.get("indices", [])), len(ca.get("commodities", [])),
             len(ca.get("yields", [])), ca["missing"] or "none"))
