#!/usr/bin/env python3
"""market_bot.py - MUTXRI TERMINAL market intelligence bot.

Pulls the financial state of every exchange the terminal covers (NSE, NGX, JSE,
EGX) and scans local press, global macro wires and X/Twitter for stories that
can move them, linking each story to the listed securities and macro themes it
actually touches.

Writes two files the terminal reads directly:
    static_data/bot_market_state.json   consolidated financials + cross-asset
    static_data/bot_signals.json        ranked, linked news signals

usage:
    python market_bot.py                       full run, writes both files
    python market_bot.py --brief               print the desk brief, no write
    python market_bot.py --exchange NSE        focus one exchange
    python market_bot.py --top 25              how many signals to print
    python market_bot.py --no-social           skip the X/Twitter tier
    python market_bot.py --tiers local,global  choose tiers explicitly
    python market_bot.py --min-impact 15       drop weaker signals

Social tier: X/Twitter needs X_BEARER_TOKEN in the environment (X has no free
search tier and the public Nitter mirrors are gone). Without it the bot reports
the tier as disabled rather than pretending the timeline was quiet.
"""
import argparse, datetime as dt, json, os, sys, time

from bot import impact, market, screen as screen_mod, sources, universe

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
STATE_FILE = os.path.join(SD, "bot_market_state.json")
SIGNALS_FILE = os.path.join(SD, "bot_signals.json")

RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"
GREEN, RED, YELLOW, CYAN = "\033[32m", "\033[31m", "\033[33m", "\033[36m"


def _c(s, colour, on):
    return (colour + s + RESET) if on else s


def _fmt_age(ts, now):
    mins = max(0, int((now - ts) / 60))
    if mins < 60:
        return "%dm" % mins
    if mins < 60 * 48:
        return "%dh" % (mins // 60)
    return "%dd" % (mins // 1440)


def digest(signals, state):
    """Per-exchange roll-up: what the tape did, and what the news leans."""
    out = {}
    for ex, blk in state["exchanges"].items():
        sigs = [s for s in signals if s["exchange"] == ex]
        # Bias is impact-weighted so one strong story outranks several weak ones.
        num = sum(s["direction"] * s["impact"] for s in sigs)
        den = sum(s["impact"] for s in sigs)
        lean = round(num / den, 3) if den else 0.0
        br = blk["breadth"]
        out[ex] = {
            "exchange": ex,
            "tone": br["tone"],
            "advancers": br["advancers"], "decliners": br["decliners"],
            "tradedChgPct": br["trimmedTradedChgPct"],
            "signals": len(sigs),
            "newsLean": lean,
            "newsBias": "bullish" if lean > 0.15 else ("bearish" if lean < -0.15 else "neutral"),
            "topSignal": sigs[0]["title"] if sigs else None,
        }
    return out


def print_brief(state, signals, dg, top=15, focus=None, colour=True, report=None):
    now = time.time()
    print()
    print(_c("MUTXRI MARKET BOT", BOLD, colour) + "  " +
          _c(dt.datetime.now().strftime("%a %d %b %Y %H:%M"), DIM, colour))
    print("=" * 78)

    print(_c("\nEXCHANGES", BOLD, colour))
    for ex, d in dg.items():
        if focus and ex != focus:
            continue
        chg = d["tradedChgPct"] or 0.0
        col = GREEN if chg > 0 else (RED if chg < 0 else YELLOW)
        blk = state["exchanges"][ex]
        print("  %-4s %-30s %s  adv %3d / dec %-3d  %-8s news:%-8s (%d signals)"
              % (ex, blk["name"][:30], _c("%+6.2f%%" % chg, col, colour),
                 d["advancers"], d["decliners"], d["tone"], d["newsBias"], d["signals"]))
        sus = blk["breadth"]["suspectRows"]
        if sus:
            print(_c("       note: %d row(s) excluded as bad prints (%s)"
                     % (len(sus), ", ".join(str(r["ticker"]) for r in sus[:4])), DIM, colour))

    ca = state["crossAsset"]
    if ca.get("indices"):
        print(_c("\nINDICES", BOLD, colour))
        for i in ca["indices"]:
            c = i.get("changePct") or 0
            print("  %-18s %14s  %s" % (i["label"][:18],
                                        "{:,.2f}".format(i["price"]) if i.get("price") else "-",
                                        _c("%+.2f%%" % c, GREEN if c > 0 else RED, colour)))
    if ca.get("commodities"):
        print(_c("\nCOMMODITIES", BOLD, colour))
        for c in ca["commodities"][:6]:
            p = c.get("chgPct") or 0
            print("  %-12s %10s  %s   %s" % (c["name"][:12],
                                             ("%.2f" % c["price"]) if c.get("price") else "-",
                                             _c("%+6.2f%%" % p, GREEN if p > 0 else RED, colour),
                                             _c((c.get("africa") or "")[:38], DIM, colour)))

    print(_c("\nSIGNALS", BOLD, colour) + _c("  (impact = relevance x confidence)", DIM, colour))
    shown = [s for s in signals if not focus or s["exchange"] == focus][:top]
    if not shown:
        print(_c("  no signals above threshold", DIM, colour))
    for s in shown:
        bias_col = GREEN if s["bias"] == "bullish" else (RED if s["bias"] == "bearish" else YELLOW)
        tick = ", ".join(dict.fromkeys(str(x["ticker"] or x["name"][:12])
                                       for x in s["securities"][:4]))
        # One theme can expose several sectors of the same market; show it once.
        th = ", ".join(dict.fromkeys(t["label"] for t in s["themes"]))
        tag = tick or th or "market-wide"
        print("  %s %-4s %-8s %s"
              % (_c("%5.1f" % s["impact"], CYAN, colour), s["exchange"],
                 _c(s["bias"], bias_col, colour), s["title"][:64]))
        print(_c("        %s | %s | %s ago | %s"
                 % (tag[:38], s["publisher"][:20], _fmt_age(s["ts"], now), s["tier"]),
                 DIM, colour))

    if report:
        soc = (report.get("social") or {}).get("status", "n/a")
        print(_c("\n%d sources ok, %d failed, %d items -> %d signals | social tier: %s"
                 % (len(report["sources"]), len(report["errors"]),
                    report["total_unique"], len(signals), soc), DIM, colour))
        for e in report["errors"]:
            print(_c("  source down: %s (%s)" % (e["source"], e["error"]), DIM, colour))
    print()


def main():
    ap = argparse.ArgumentParser(description="MUTXRI market intelligence bot")
    ap.add_argument("--brief", action="store_true", help="print only, do not write files")
    ap.add_argument("--exchange", help="focus one exchange (NSE/NGX/JSE/EGX)")
    ap.add_argument("--top", type=int, default=15, help="signals to print")
    ap.add_argument("--min-impact", type=float, default=10.0, help="signal cutoff")
    ap.add_argument("--no-social", action="store_true", help="skip the X/Twitter tier")
    ap.add_argument("--tiers", default="local,global,social", help="comma list of tiers")
    ap.add_argument("--json", action="store_true", help="dump signals as JSON to stdout")
    ap.add_argument("--quiet", action="store_true", help="suppress the brief")
    ap.add_argument("--no-colour", action="store_true", help="plain output")
    args = ap.parse_args()

    focus = args.exchange.upper() if args.exchange else None
    if focus and focus not in universe.EXCHANGES:
        ap.error("unknown exchange %r (choose from %s)" % (focus, ", ".join(universe.EXCHANGES)))

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    if args.no_social and "social" in tiers:
        tiers.remove("social")
    colour = not args.no_colour and sys.stdout.isatty()
    verbose = not args.quiet and not args.json

    t0 = time.time()
    if verbose:
        print("collecting market state...")
    state = market.snapshot()

    if verbose:
        print("scanning news (%s)..." % ", ".join(tiers))
    items, report = sources.collect(tiers=tuple(tiers), verbose=verbose)

    uni = universe.load()
    idx = universe.build_index(uni)
    signals = [s for s in impact.score_all(items, idx) if s["impact"] >= args.min_impact]
    dg = digest(signals, state)
    elapsed = round(time.time() - t0, 1)

    payload = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "elapsedSec": elapsed,
        "windowDays": sources.MAX_AGE_DAYS,
        "minImpact": args.min_impact,
        "counts": {"itemsFetched": report["total_fetched"],
                   "itemsUnique": report["total_unique"],
                   "signals": len(signals)},
        "sourceReport": report,
        "digest": dg,
        "signals": signals,
    }

    if not args.brief:
        os.makedirs(SD, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

    if not args.brief:
        # The BOT panel reads a slim, flagged-only digest of the statement
        # corpus. Building it here keeps it in step with each scan without the
        # panel having to download all 557 companies' full metrics.
        try:
            dg = screen_mod.export_panel_digest()
            if verbose:
                print("statement flags: %d of %d companies (%s)"
                      % (dg["flagged"], dg["analysed"],
                         os.path.relpath(dg["path"], BASE)))
        except Exception as e:
            print("statement digest skipped: %s: %s" % (type(e).__name__, str(e)[:70]))

    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=1)
        return 0

    if not args.quiet:
        print_brief(state, signals, dg, top=args.top, focus=focus,
                    colour=colour, report=report)
    if not args.brief:
        print("wrote %s and %s in %ss"
              % (os.path.relpath(STATE_FILE, BASE), os.path.relpath(SIGNALS_FILE, BASE), elapsed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
