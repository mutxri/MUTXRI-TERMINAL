#!/usr/bin/env python3
"""bot/screen.py - asking questions of every statement at once.

`analyse` reads one company. This reads all 557 with parsed statements and lets
you ask the questions a desk actually asks: which JSE miners are burning cash,
which NGX banks convert profit to cash worst, is this company's margin good or
merely normal for its sector.

Two capabilities, one corpus:

  SCREEN  filter the whole corpus by flag, metric threshold, exchange or sector.
  PEERS   rank one company's metrics against its sector, as a percentile.

A ratio without a peer group is close to meaningless - a 12% net margin is
excellent for a retailer and poor for a bank - so `peers` reports the sector
median alongside the company's own figure, and says how many companies the
comparison rests on. A percentile drawn from four companies is noise, and is
labelled as such rather than dressed up as a rank.

Building the corpus costs about 40 seconds, so it is cached and rebuilt only
when the underlying statement files change.
"""
import json, os, time

from . import statements as S, universe as U

CACHE = os.path.join(S.SD, "statement_corpus.json")
# Below this many peers a percentile is not a measurement, just an ordering.
MIN_PEERS = 5


def _corpus_signature():
    """Cheap fingerprint of the statement corpus: count and newest mtime."""
    if not os.path.isdir(S.FIN_DIR):
        return None
    newest, count = 0.0, 0
    for f in os.listdir(S.FIN_DIR):
        if not f.endswith(".json"):
            continue
        count += 1
        try:
            newest = max(newest, os.path.getmtime(os.path.join(S.FIN_DIR, f)))
        except OSError:
            pass
    return {"files": count, "newest": round(newest, 3)}


def build(verbose=False):
    """Analyse every company with parsed statements. Returns the corpus list."""
    sectors = {}
    for ex, secs in U.load().items():
        for s in secs:
            sectors[s["ticker"]] = {"exchange": ex,
                                    "sector": s.get("sector") or "Unclassified",
                                    "name": s.get("name"),
                                    "marketCap": s.get("marketCap")}
    out = []
    tickers = S.available_public()
    for i, t in enumerate(tickers):
        if verbose and i % 100 == 0:
            print("  %d/%d..." % (i, len(tickers)))
        try:
            doc = S.load_public(t)
            if not doc:
                continue
            a = S.analyse(doc)
        except Exception:
            continue
        latest = a["metrics"][0] if a["metrics"] else {}
        meta = sectors.get(t, {})
        # 109 statements are keyed by a symbol the listing does not carry - EGX
        # ISIN-style codes, and JSE securities that have since been renamed. The
        # suffix still identifies the exchange, which is enough to filter by even
        # when the sector is unknown, and beats dropping them into a null bucket.
        exch = meta.get("exchange")
        if not exch:
            suffix = t.rsplit(".", 1)[-1].upper() if "." in t else ""
            exch = {"CA": "EGX", "JO": "JSE"}.get(suffix)
        out.append({
            "ticker": t,
            "name": meta.get("name") or a["entity"].get("name") or t,
            # A statement can exist for a security the listing no longer carries
            # (delisted, renamed, or keyed differently). Say so rather than
            # filing it under a sector it was never in.
            "exchange": exch,
            "sector": meta.get("sector"),
            "inListing": bool(meta),
            "currency": a["entity"].get("currency"),
            "periods": a["periods"],
            "latest": dict(
                {k: latest.get(k) for k in (
                    "period", "revenue", "net_profit", "net_margin", "gross_margin",
                    "ebit_margin", "roe", "roa", "revenue_growth", "net_profit_growth",
                    "ocf", "ocf_to_net_profit", "fcf", "fcf_margin", "current_ratio",
                    "quick_ratio", "debt_to_equity", "interest_cover", "total_equity",
                    "roce", "roic", "asset_turnover", "equity_multiplier",
                    "effective_tax_rate", "inventory_days", "receivable_days")},
                # Valuation lives beside the metrics so a screen can mix them -
                # "cheap on earnings and generating cash" is one query, not two.
                **{k: (a.get("valuation") or {}).get(k) for k in
                   ("pe", "pb", "ps", "earnings_yield", "ev_ebit")}),
            "growth": a.get("growth") or {},
            # The named models, flattened so a screen can filter on them:
            # "F-Score of 7 or better, cheap on earnings" is one query.
            "models": _model_summary(a),
            "flags": [{"id": f["id"], "severity": f["severity"], "label": f["label"]}
                      for f in a["flags"]],
            "coverage": a["coverage"]["missingSections"],
        })
    return out


def _model_summary(a):
    """The scoring models, reduced to the few fields a screen filters on."""
    try:
        from . import models as M
        m = M.score_all(a)
    except Exception:
        return {}
    pio, z, acc = m["piotroski"], m["altmanZ"], m["accruals"]
    return {
        "fscore": pio.get("score") if pio.get("available") else None,
        "fscore_outOf": pio.get("outOf") if pio.get("available") else None,
        "altman_z": z.get("score") if z.get("available") else None,
        "altman_band": z.get("band") if z.get("available") else None,
        "accruals": acc.get("ratio") if acc.get("available") else None,
        "cost_to_income": m["costToIncome"].get("ratio"),
        "operating_leverage": m["operatingLeverage"].get("dol"),
    }


def load(rebuild=False, verbose=False):
    """Corpus from cache when the statement files have not changed."""
    sig = _corpus_signature()
    if not rebuild and os.path.exists(CACHE):
        try:
            blob = json.load(open(CACHE, encoding="utf-8"))
            if blob.get("signature") == sig:
                return blob["companies"]
        except Exception:
            pass
    rows = build(verbose=verbose)
    try:
        os.makedirs(S.SD, exist_ok=True)
        json.dump({"signature": sig, "builtAt": int(time.time()), "companies": rows},
                  open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    return rows


# -------------------------------------------------------------------- screen
COMPARATORS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "=": lambda a, b: a == b, "!=": lambda a, b: a != b,
}


def parse_condition(expr):
    """'roe>15' or 'net_margin <= 2' into (metric, comparator, value)."""
    for op in ("<=", ">=", "!=", "<", ">", "="):
        if op in expr:
            field, _, raw = expr.partition(op)
            field, raw = field.strip(), raw.strip()
            try:
                val = float(raw)
            except ValueError:
                raise ValueError("%r is not a number in %r" % (raw, expr))
            return field, op, val
    raise ValueError("no comparator in %r (use e.g. roe>15)" % expr)


def screen(companies, exchange=None, sector=None, flags=(), severity=None,
           conditions=(), require_all_flags=False):
    """Filter the corpus. Every filter is AND-ed; `flags` is OR unless told otherwise."""
    out = []
    for c in companies:
        if exchange and (c.get("exchange") or "").upper() != exchange.upper():
            continue
        if sector and sector.lower() not in (c.get("sector") or "").lower():
            continue
        ids = {f["id"] for f in c["flags"]}
        if flags:
            want = set(flags)
            if require_all_flags:
                if not want.issubset(ids):
                    continue
            elif not (want & ids):
                continue
        if severity and not any(f["severity"] == severity for f in c["flags"]):
            continue
        ok = True
        for field, op, val in conditions:
            have = c["latest"].get(field)
            if have is None:
                have = (c.get("models") or {}).get(field)
            if have is None or not COMPARATORS[op](have, val):
                ok = False
                break
        if ok:
            out.append(c)
    return out


def flag_counts(companies):
    counts = {}
    for c in companies:
        for f in c["flags"]:
            k = counts.setdefault(f["id"], {"id": f["id"], "label": f["label"],
                                            "severity": f["severity"], "count": 0})
            k["count"] += 1
    return sorted(counts.values(), key=lambda x: -x["count"])


# --------------------------------------------------------------------- peers
def _percentile(values, x):
    """Share of peers at or below x, 0-100."""
    if not values:
        return None
    below = sum(1 for v in values if v <= x)
    return round(100.0 * below / len(values), 1)


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


PEER_METRICS = ["net_margin", "gross_margin", "ebit_margin", "roe", "roa",
                "roce", "roic", "asset_turnover", "revenue_growth",
                "ocf_to_net_profit", "fcf_margin", "current_ratio",
                "quick_ratio", "debt_to_equity", "interest_cover",
                "pe", "pb", "ps"]


def peers(companies, ticker, by="sector"):
    """Rank one company's metrics against its peer group.

    `by` is "sector" (same exchange and sector) or "exchange". Metrics where the
    group is too small to mean anything are returned with `reliable: False`
    rather than omitted, so the caller can show the figure and withhold the rank.
    """
    me = next((c for c in companies if c["ticker"] == ticker), None)
    if not me:
        return None

    def _by_exchange():
        g = [c for c in companies
             if c.get("exchange") == me.get("exchange") and c["ticker"] != ticker]
        return g, "%s (all sectors)" % (me.get("exchange") or "?")

    def _by_sector():
        g = [c for c in companies
             if c.get("exchange") == me.get("exchange")
             and (c.get("sector") or None) == (me.get("sector") or None)
             and c["ticker"] != ticker]
        return g, "%s %s" % (me.get("exchange") or "?",
                             me.get("sector") or "Unclassified")

    widened = False
    if by == "exchange":
        group, label = _by_exchange()
    else:
        group, label = _by_sector()
        # Safaricom is the only telecom on the NSE, so its sector group is empty
        # and every percentile comes back blank. A cross-sector comparison on the
        # same exchange is cruder but is a real comparison; showing nothing is not.
        if len(group) < MIN_PEERS:
            wide, wlabel = _by_exchange()
            if len(wide) >= MIN_PEERS:
                group, label, widened = wide, wlabel, True

    rows = []
    for m in PEER_METRICS:
        mine = me["latest"].get(m)
        vals = [c["latest"].get(m) for c in group]
        vals = [v for v in vals if v is not None]
        if mine is None and not vals:
            continue
        rows.append({
            "metric": m,
            "value": mine,
            "peerMedian": round(_median(vals), 3) if vals else None,
            "peerCount": len(vals),
            "percentile": _percentile(vals, mine) if (mine is not None and vals) else None,
            "reliable": len(vals) >= MIN_PEERS,
        })
    return {"ticker": ticker, "name": me["name"], "group": label,
            "groupSize": len(group), "metrics": rows, "widened": widened,
            "sector": me.get("sector"),
            "flags": me["flags"], "latestPeriod": me["latest"].get("period")}


# ------------------------------------------------------------ panel export
PANEL_FILE = os.path.join(S.SD, "bot_flags.json")
# Fields the panel actually renders. The full corpus is ~490KB because it holds
# every metric for every company; a panel that only lists flagged names does not
# need to download the other 320 companies to do it.
_PANEL_METRICS = ("period", "net_margin", "roe", "revenue_growth",
                  "ocf_to_net_profit", "interest_cover")


def export_panel_digest(companies=None, path=None):
    """Write the slim, flagged-only view the BOT panel fetches."""
    companies = companies if companies is not None else load()
    rows = []
    for c in companies:
        if not c["flags"]:
            continue
        rows.append({
            "ticker": c["ticker"], "name": c["name"],
            "exchange": c.get("exchange"), "sector": c.get("sector"),
            "currency": c.get("currency"),
            "latest": {k: c["latest"].get(k) for k in _PANEL_METRICS},
            "flags": c["flags"],
            "worst": ("high" if any(f["severity"] == "high" for f in c["flags"])
                      else ("medium" if any(f["severity"] == "medium"
                                            for f in c["flags"]) else "low")),
        })
    order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (order[r["worst"]], -len(r["flags"]), r["ticker"]))
    blob = {
        "generated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "companiesAnalysed": len(companies),
        "companiesFlagged": len(rows),
        "flagCounts": flag_counts(companies),
        "companies": rows,
    }
    path = path or PANEL_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=1)
    return {"path": path, "flagged": len(rows), "analysed": len(companies),
            "bytes": os.path.getsize(path)}


# ------------------------------------------------- per-ticker analytics export
ANALYTICS_DIR = os.path.join(S.SD, "analytics")

# Ratios the FINANCIALS panel shows beneath the statement, in display order.
PANEL_RATIOS = [
    ("net_margin", "Net margin", "%"),
    ("gross_margin", "Gross margin", "%"),
    ("ebit_margin", "Operating margin", "%"),
    ("roe", "Return on equity", "%"),
    ("roce", "Return on capital employed", "%"),
    ("roic", "Return on invested capital", "%"),
    ("asset_turnover", "Asset turnover", "x"),
    ("current_ratio", "Current ratio", ""),
    ("interest_cover", "Interest cover", "x"),
    ("ocf_to_net_profit", "Cash conversion", "x"),
    ("revenue_growth", "Revenue growth", "%"),
    ("effective_tax_rate", "Effective tax rate", "%"),
]


def export_per_ticker(companies=None, out_dir=None, verbose=False):
    """Write static_data/analytics/<TICKER>.json, one small file per security.

    The terminal's FINANCIALS panel shows filed statements and nothing else,
    while the engine computes thirty-odd metrics and six models that no reader
    can see. Per-ticker files match how statements already ship: the panel
    fetches one small file for the security on screen rather than a corpus.
    """
    from . import models as M
    out_dir = out_dir or ANALYTICS_DIR
    os.makedirs(out_dir, exist_ok=True)
    written, skipped = 0, 0
    tickers = S.available_public()
    for t in tickers:
        try:
            doc = S.load_public(t)
            if not doc:
                skipped += 1
                continue
            a = S.analyse(doc)
        except Exception:
            skipped += 1
            continue
        rows = a.get("metrics") or []
        if not rows:
            skipped += 1
            continue
        cur = rows[0]
        mods = M.score_all(a)
        pio, alt, acc = mods["piotroski"], mods["altmanZ"], mods["accruals"]
        v = a.get("verification") or {}
        blob = {
            "ticker": t,
            "name": a["entity"].get("name"),
            "currency": a["entity"].get("currency"),
            "period": cur.get("period"),
            "periods": a.get("periods", []),
            "ratios": [{"key": k, "label": lbl, "unit": u, "value": cur.get(k)}
                       for k, lbl, u in PANEL_RATIOS if cur.get(k) is not None],
            "valuation": {k: (a.get("valuation") or {}).get(k)
                          for k in ("pe", "pb", "ps", "earnings_yield", "ev_ebit",
                                    "asOfPeriod", "peCrossCheck", "note")},
            "growth": {k: (a.get("growth") or {}).get(k)
                       for k in ("revenue_cagr", "net_profit_cagr",
                                 "contiguousYears", "from", "to")},
            "models": {
                "fscore": pio.get("score") if pio.get("available") else None,
                "fscoreOutOf": pio.get("outOf") if pio.get("available") else None,
                "fscoreReading": pio.get("reading") if pio.get("available") else None,
                "altmanZ": alt.get("score") if alt.get("available") else None,
                "altmanBand": alt.get("band") if alt.get("available") else None,
                "altmanMissing": None if alt.get("available") else alt.get("missing"),
                "accruals": acc.get("ratio") if acc.get("available") else None,
                "accrualsReading": acc.get("reading") if acc.get("available") else None,
                "costToIncome": mods["costToIncome"].get("ratio"),
            },
            "flags": a.get("flags", []),
            # The audit result travels with the numbers, so a reader can see
            # that the statement reconciles rather than assuming it.
            "audit": {"passed": v.get("passed"), "total": v.get("total"),
                      "failed": len(v.get("failed") or [])},
            "derived": {
                "currentSplit": bool(cur.get("current_split_derived")),
                "ebit": bool(cur.get("ebit_derived")),
                "capitalEmployedBasis": cur.get("capital_employed_basis"),
            },
        }
        with open(os.path.join(out_dir, "%s.json" % t), "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, separators=(",", ":"))
        written += 1
        if verbose and written % 200 == 0:
            print("  %d/%d..." % (written, len(tickers)))
    return {"dir": out_dir, "written": written, "skipped": skipped}


if __name__ == "__main__":
    import sys
    cs = load(verbose=True)
    print("corpus: %d companies" % len(cs))
    print("\ntop flags:")
    for f in flag_counts(cs)[:8]:
        print("  %-26s %-8s %d" % (f["id"], f["severity"], f["count"]))
    t = sys.argv[1] if len(sys.argv) > 1 else "ABG.JO"
    p = peers(cs, t)
    if p:
        print("\npeers for %s (%s, %d in group):" % (p["ticker"], p["group"], p["groupSize"]))
        for r in p["metrics"]:
            print("  %-20s %10s  median %10s  pct %-6s %s"
                  % (r["metric"], r["value"], r["peerMedian"], r["percentile"],
                     "" if r["reliable"] else "(too few peers)"))
