#!/usr/bin/env python3
"""bot/terminal_news.py - the public half of the news scan.

The scan produces two different things from the same fetch. Scored signals, with
impact, bias and linked securities, are analysis: they are for the desk, they can
be wrong in interesting ways, and they stay local. Headlines are just headlines,
and the terminal's NEWS panel has real gaps the scan already fills:

  JSE   jse_news.json has held 20 Moneyweb headlines all along, and the panel
        never wired it up - it renders "no free news feed for JSE".
  EGX   nothing at all, because no single reachable Egyptian feed exists. The
        scan reaches EGX coverage through three sources at once.

So this writes bot_news_<EX>.json: press headlines per exchange, deduped and
ordered, in the shape the panel already reads.

What deliberately does not cross over:

  * No impact, bias or direction. Those are the bot's opinion of a story, they
    belong to the analysis, and a number like "68.2 bearish" printed next to a
    company's name on a public site is a claim the terminal should not be making.
  * Ticker links only where the match was strong. The matcher is careful, but a
    wrong link is a wrong story against a real company in public, so the bar here
    is higher than the one the desk view uses.

Ordering is the one piece of the analysis that does cross over, and only as
ordering: a story the scan rated highly appears further up. No score is shown.
"""
import datetime as dt, json, os, re, time

from . import universe as U

SD = U.SD
# The panel shows a scrolling list; beyond this nobody reads and the file grows.
MAX_PER_EXCHANGE = 60
# A ticker is printed publicly only well above the matcher's internal threshold.
PUBLIC_TICKER_MIN = 0.7
# Below this a signal is a weak thematic association, not an exchange headline.
MIN_SIGNAL_IMPACT = 20.0
# A global wire with no local company named has to be genuinely large to appear
# on an exchange's page at all.
GLOBAL_MIN_IMPACT = 45.0
# ...and never more than this share of the list, so local coverage always leads.
GLOBAL_SHARE = 0.2


def _norm_title(t):
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower())[:90]


def _fmt_date(ts):
    try:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%b %-d")
    except (ValueError, OSError, TypeError):
        try:
            # %-d is not portable to Windows; %#d is the local equivalent.
            return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%b %d").replace(" 0", " ")
        except Exception:
            return ""


# Some feeds run the opening paragraph into the title field; a headline that
# wraps to four lines is the source's mistake, not something to render faithfully.
MAX_TITLE = 150


def _trim_title(t):
    t = re.sub(r"\s+", " ", (t or "")).strip()
    if len(t) <= MAX_TITLE:
        return t
    cut = t[:MAX_TITLE].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return cut + "…"


def _row(title, url, publisher, ts, tickers=None, rank=0.0):
    return {
        "id": abs(hash((url or title))) % 10 ** 9,
        "title": _trim_title(title), "publisher": publisher or "",
        "date": _fmt_date(ts), "url": url or "",
        "ts": int(ts or 0),
        "tickers": tickers or [],
        "_rank": rank,
    }


def build(items, signals):
    """Per-exchange headline lists from one scan.

    Two inputs because they cover different things: the local feeds are
    exchange-tagged by construction and carry everything those outlets published,
    including stories that matched no company; the signals add the global stories
    that reached a market through a theme. Together they cover both.
    """
    per_ex = {ex: [] for ex in U.EXCHANGES}

    # Only stories the scan actually linked to a market get in. The local feeds
    # are general outlets - Moneyweb, Daily News Egypt, Tuko - that run lifestyle
    # and politics alongside markets, so taking everything they publish put
    # "France's sacred food culture faces an existential reckoning" on the JSE
    # page. The impact engine already decides whether a story touches a market;
    # requiring a match is the filter, and it needs no new keyword list.
    #
    # Stories the scan linked to a market. A macro theme attaches to all four
    # exchanges by design, so admitting every themed signal fills "NSE NEWS" with
    # the same Fed and Middle East wires that fill the other three - and lets
    # something like "Meet the CISO: AI cybersecurity" in on a weak association.
    # A global story earns a place here only by naming a listed company on that
    # exchange, or by clearing a much higher bar than the desk view uses.
    global_pool = {ex: [] for ex in per_ex}
    for s in signals or []:
        ex = s.get("exchange")
        if ex not in per_ex or s.get("impact", 0) < MIN_SIGNAL_IMPACT:
            continue
        ticks = []
        for sec in s.get("securities", []):
            if (sec.get("match_strength") or 0) >= PUBLIC_TICKER_MIN and sec.get("ticker"):
                ticks.append(sec["ticker"])
        ticks = list(dict.fromkeys(ticks))[:3]
        row = _row(s["title"], s.get("url"), s.get("publisher"), s.get("ts"),
                   tickers=ticks, rank=s.get("impact", 0))
        names_a_local_company = bool(ticks)
        if s.get("tier") == "local" or names_a_local_company:
            per_ex[ex].append(row)
        elif s.get("impact", 0) >= GLOBAL_MIN_IMPACT:
            global_pool[ex].append(row)

    # Top up each exchange with its strongest global stories, capped so the page
    # stays predominantly about that market.
    for ex, rows in per_ex.items():
        room = max(0, int(MAX_PER_EXCHANGE * GLOBAL_SHARE))
        pool = sorted(global_pool[ex], key=lambda r: -r["_rank"])[:room]
        rows.extend(pool)

    out = {}
    for ex, rows in per_ex.items():
        # Highest-ranked copy of a story wins, so a headline that arrived from
        # both a local feed and a signal keeps the signal's ticker links.
        rows.sort(key=lambda r: -r["_rank"])
        seen_t, seen_u, keep = set(), set(), []
        for r in rows:
            t = _norm_title(r["title"])
            u = (r["url"] or "").split("?")[0]
            if (t and t in seen_t) or (u and u in seen_u):
                continue
            seen_t.add(t)
            if u:
                seen_u.add(u)
            keep.append(r)
        # The panel is a news list, so it reads newest first once curated.
        keep = keep[:MAX_PER_EXCHANGE]
        keep.sort(key=lambda r: -r["ts"])
        for r in keep:
            r.pop("_rank", None)
        out[ex] = keep
    return out


def write(items, signals, sd=None):
    """Write bot_news_<EX>.json for every exchange with headlines."""
    sd = sd or SD
    built = build(items, signals)
    written = {}
    for ex, rows in built.items():
        path = os.path.join(sd, "bot_news_%s.json" % ex)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        written[ex] = len(rows)
    return written


if __name__ == "__main__":
    from . import impact, sources
    its, _rep = sources.collect(verbose=False)
    idx = U.build_index(U.load())
    sigs = impact.score_all(its, idx)
    print(write(its, sigs))
