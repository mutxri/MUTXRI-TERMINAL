#!/usr/bin/env python3
"""bot/impact.py - deciding which story matters, to whom, and which way.

Two independent ways a headline reaches an exchange:

  1. ENTITY   the story names a listed company or its ticker. Direction comes
              from a corporate-event lexicon (profit/dividend vs loss/probe).
  2. THEME    the story is macro - oil, the Fed, a currency, a policy rate.
              Each theme carries an exposure map saying which exchange and
              sector it transmits into and with what sign, so the theme's own
              direction (up/down) is combined with the exposure sign to get
              the effect on that market.

Scores are evidence-weighted, never absolute claims: `impact` is
relevance x confidence, and confidence blends source quality with recency.
Nothing here forecasts a price - it ranks what a desk should read first.
"""
import math, re, time

from . import universe as U

# --------------------------------------------------------------- direction words
_UP = (r"(?:rise|rises|rising|rose|rally|rallies|rallied|surge|surges|jump|jumps|"
       r"climb|climbs|gain|gains|soar|soars|advance|advances|strengthen\w*|"
       r"appreciat\w+|firms?\b|firmer|higher|record high|two-year high|spike|spikes|"
       r"boost|boosts|up\b|rebound\w*|tops?\b|extend\w* gains)")
_DOWN = (r"(?:fall|falls|falling|fell|drop|drops|slump|slumps|plunge|plunges|slide|"
         r"slides|decline|declines|tumble|tumbles|sink|sinks|weaken\w*|weaker|"
         r"depreciat\w+|devalu\w+|lower|crash|crashes|sell-?off|down\b|retreat|"
         r"slips?|slid|extend\w* losses)")

# Corporate-event lexicon: (regex, direction, strength)
_CORP = [
    # Results language, in the shapes these wires actually use: "posts N45bn
    # profit", "profit rises 12%", "returns to profitability", "declares dividend".
    (r"\b(record profit|profit (?:jump|jumps|surge|surges|rise|rises|rose|up|grow|grows|grew)|"
     r"(?:posts?|posted|reports?|reported|announces?|announced|declares?|declared)\b[^.]{0,40}\b"
     r"(?:profit|earnings|revenue growth|surplus)|"
     r"returns? to profit|profit(?:abilit)?y\b[^.]{0,20}\b(?:return|recovery)|"
     r"beats? (?:estimates|expectations|forecasts?)|strong (?:results|earnings|performance)|"
     r"earnings beat|revenue (?:jump|jumps|rise|rises|grew|grow|surge|surges))\b", +1, 0.9),
    (r"\b(dividend|payout|bonus issue|buy-?back|share buyback)\b", +1, 0.7),
    (r"\b(acquisition|acquires?|merger|takeover|expansion|new plant|wins? (?:contract|licence|license)|"
     r"upgrade[ds]?|listing|ipo|rights issue)\b", +1, 0.55),
    (r"\b(loss|losses|profit (?:fall|drop|slump|decline)|misses? (?:estimates|expectations)|"
     r"earnings miss|writedown|write-down|impairment)\b", -1, 0.9),
    (r"\b(probe|investigation|fraud|scandal|lawsuit|sues?|fine[ds]?|penalt(?:y|ies)|"
     r"sanction(?:ed|s)?|default|insolvenc|liquidation|administration)\b", -1, 0.85),
    (r"\b(suspend(?:ed|s|ion)?|delist(?:ed|ing)?|halt(?:ed)?|downgrade[ds]?|"
     r"profit warning|going concern|resigns?|steps? down|retrench|strike|job cuts?)\b", -1, 0.8),
]

# Finance framing required by the currency and inflation themes, so a passing
# mention of a currency unit does not turn a sports or crime story into a signal.
_FIN_CONTEXT = (r"\b(exchange rate|forex|fx|dollar|currency|central bank|"
                r"market|markets|investor|investors|trading|traders|bond|bonds|"
                r"yield|yields|inflation|rate|rates|appreciat\w+|depreciat\w+|"
                r"devalu\w+|weaken\w*|strengthen\w*|econom\w+|imports?|exports?|"
                r"reserves|liquidity|bourse|stock|shares|equit\w+)\b")

# ------------------------------------------------------------------- themes
# exposure sign = effect on that market when the THEME ITSELF moves up.
THEMES = [
    {
        "id": "fed_rates", "label": "US rates / Fed",
        "pat": r"\b(federal reserve|fomc|fed (?:rate|funds|chair|official)|"
               r"us (?:interest )?rate|treasury yield|rate (?:cut|hike)|powell)\b",
        "exposures": [{"ex": e, "sector": None, "sign": -1, "strength": 0.55}
                      for e in U.EXCHANGES],
        "note": "Higher US rates pull portfolio flows out of frontier equity and "
                "raise hard-currency funding costs.",
    },
    {
        "id": "oil", "label": "Crude oil",
        "pat": r"\b(oil price|crude|brent|wti|opec\+?|petroleum output|barrel)\b",
        "exposures": [
            {"ex": "NGX", "sector": "Energy", "sign": +1, "strength": 0.85},
            {"ex": "NGX", "sector": None, "sign": +1, "strength": 0.5},
            {"ex": "EGX", "sector": None, "sign": -1, "strength": 0.3},
            {"ex": "NSE", "sector": None, "sign": -1, "strength": 0.35},
        ],
        "note": "Nigeria is oil-funded; Kenya and Egypt are net importers, so the "
                "same move cuts opposite ways.",
    },
    {
        "id": "gold", "label": "Gold / bullion",
        "pat": r"\b(gold price|bullion|gold miner|gold futures)\b",
        "exposures": [{"ex": "JSE", "sector": "Mining", "sign": +1, "strength": 0.85},
                      {"ex": "JSE", "sector": None, "sign": +1, "strength": 0.35}],
        "note": "Gold is a heavy weight in JSE resources earnings.",
    },
    {
        "id": "pgm", "label": "Platinum group metals",
        "pat": r"\b(platinum|palladium|rhodium|pgm)\b",
        "exposures": [{"ex": "JSE", "sector": "Mining", "sign": +1, "strength": 0.8}],
        "note": "South Africa dominates global PGM supply.",
    },
    {
        "id": "china", "label": "China demand",
        "pat": r"\b(china (?:growth|economy|demand|stimulus|imports?)|chinese (?:economy|demand))\b",
        "exposures": [{"ex": "JSE", "sector": "Mining", "sign": +1, "strength": 0.6},
                      {"ex": "NGX", "sector": None, "sign": +1, "strength": 0.25}],
        "note": "China sets the marginal bid for African commodity exports.",
    },
    {
        "id": "kes", "label": "Kenyan shilling",
        "pat": r"\b(kenyan shilling|shilling)\b",
        "context": _FIN_CONTEXT,
        "exposures": [{"ex": "NSE", "sector": None, "sign": +1, "strength": 0.6}],
        "note": "A firmer shilling lifts USD-denominated returns for NSE holders.",
    },
    {
        "id": "ngn", "label": "Naira",
        "pat": r"\bnaira\b",
        "context": _FIN_CONTEXT,
        "exposures": [{"ex": "NGX", "sector": None, "sign": +1, "strength": 0.6}],
        "note": "Naira moves drive foreign-investor returns and import costs.",
    },
    {
        "id": "zar", "label": "Rand",
        "pat": r"\b(the rand|rand (?:weaken|strengthen|firm|slip|gain|fall|rise)\w*|"
               r"rand/dollar|rand exchange rate)\b",
        "context": _FIN_CONTEXT,
        "exposures": [{"ex": "JSE", "sector": "Banks", "sign": +1, "strength": 0.45},
                      {"ex": "JSE", "sector": "Mining", "sign": -1, "strength": 0.4}],
        "note": "A stronger rand helps domestic earners but squeezes rand-hedge miners.",
    },
    {
        "id": "egp", "label": "Egyptian pound",
        "pat": r"\b(egyptian pound|egp devaluation)\b",
        "context": _FIN_CONTEXT,
        "exposures": [{"ex": "EGX", "sector": None, "sign": +1, "strength": 0.6}],
        "note": "EGX returns are dominated by the pound in USD terms.",
    },
    {
        "id": "local_rates", "label": "Local policy rate",
        "pat": r"\b(central bank of kenya|cbk|monetary policy committee|mpc|"
               r"central bank of nigeria|cbn|sarb|south african reserve bank|"
               r"central bank of egypt|cbe|benchmark rate|policy rate|repo rate)\b",
        "exposures": [{"ex": e, "sector": "Banks", "sign": +1, "strength": 0.5}
                      for e in U.EXCHANGES]
                     + [{"ex": e, "sector": None, "sign": -1, "strength": 0.35}
                        for e in U.EXCHANGES],
        "note": "Higher policy rates widen bank margins but compress equity valuations.",
    },
    {
        "id": "inflation", "label": "Inflation",
        "pat": r"\b(inflation|consumer price|cpi)\b",
        "context": _FIN_CONTEXT,
        "exposures": [{"ex": e, "sector": None, "sign": -1, "strength": 0.4}
                      for e in U.EXCHANGES],
        "note": "Rising inflation pulls forward rate hikes and squeezes real returns.",
    },
    {
        "id": "imf_debt", "label": "IMF / sovereign debt",
        "pat": r"\b(imf|international monetary fund|eurobond|sovereign (?:debt|rating)|"
               r"debt restructur\w+|world bank loan|moody'?s|s&p global ratings|fitch)\b",
        "exposures": [{"ex": e, "sector": None, "sign": +1, "strength": 0.45}
                      for e in U.EXCHANGES],
        "note": "Sovereign funding and rating news resets the discount rate for the "
                "whole local market.",
    },
    {
        "id": "risk_off", "label": "Geopolitics / trade",
        "pat": r"\b(tariffs?|trade war|sanctions|recession|war|conflict|coup|"
               r"election violence|shutdown)\b",
        "exposures": [{"ex": e, "sector": None, "sign": -1, "strength": 0.35}
                      for e in U.EXCHANGES],
        "note": "Global risk aversion hits frontier liquidity first.",
    },
]

# Generic sector cues, used only alongside an exchange cue.
SECTOR_CUES = [
    (r"\b(bank|banking|lender|lenders)\b", "Banks"),
    (r"\b(telecom|mobile money|network operator)\b", "Telecommunications"),
    (r"\b(insurer|insurance|underwrit\w+)\b", "Insurance"),
    (r"\b(cement|construction|builder)\b", "Building & Associated"),
    (r"\b(miner|mining|mine)\b", "Mining"),
    (r"\b(brewer|beverage|bottler)\b", "Food & Beverage"),
    (r"\b(refiner|refinery|fuel marketer)\b", "Energy"),
]


def _ex_cue(text_l):
    """Which exchanges does this text explicitly place itself in?"""
    hits = set()
    for ex, meta in U.EX_META.items():
        pats = [ex.lower(), meta["name"].lower(), meta["country"].lower()] + meta["ccy_words"]
        for p in pats:
            if re.search(r"\b" + re.escape(p) + r"\b", text_l):
                hits.add(ex)
                break
    return hits


def _theme_direction(text_l):
    """Did the theme move up or down in this text? 0 when unstated."""
    up = len(re.findall(_UP, text_l))
    dn = len(re.findall(_DOWN, text_l))
    if up > dn:
        return +1
    if dn > up:
        return -1
    return 0


def _corp_direction(text_l):
    """(direction, strength) from the corporate-event lexicon."""
    best_d, best_s = 0, 0.0
    for pat, d, s in _CORP:
        if re.search(pat, text_l) and s > best_s:
            best_d, best_s = d, s
    return best_d, best_s


def _norm_tic(t):
    """ABG.JO -> ABG, so JSE codes match the way headlines write them."""
    return (t or "").upper().split(".")[0]


def match_entities(item, idx):
    """Find listed securities the item is actually about.

    Name matches need the distinctive core of the company name as a phrase.
    Ticker matches need an uppercase standalone token; short tickers (<4 chars)
    additionally need an exchange or country cue in the same text, because
    three-letter words collide with ordinary English far too often.
    """
    text = item["title"] + " " + (item.get("summary") or "")
    text_l = text.lower()
    ex_cues = _ex_cue(text_l)
    found, seen = [], set()

    # Testing all ~1.4k aliases against every headline costs ~1M regex scans a
    # run. Only aliases whose first token actually occurs in the text can match,
    # so the first-word buckets cut the candidate set to a handful.
    words = set(re.findall(r"[a-z0-9]+", text_l))
    by_first = idx.get("names_by_first")
    if by_first:
        cand = [a for w in words for a in by_first.get(w, ())]
    else:
        cand = list(idx["names"])

    for alias in cand:
        secs = idx["names"][alias]
        if re.search(r"\b" + re.escape(alias) + r"\b", text_l):
            # An alias shared by several issuers is weak evidence for any one.
            share = 1.0 if len(secs) == 1 else 0.45
            ambiguous = alias in U.AMBIGUOUS_SURFACES
            for s in secs:
                if ambiguous and s["exchange"] not in ex_cues:
                    continue  # ordinary English word; needs a market cue to count
                k = (s["exchange"], s["ticker"], s["name"])
                if k in seen:
                    continue
                seen.add(k)
                # Longer, more specific names are stronger evidence.
                strength = min(0.95, 0.5 + 0.06 * len(alias.split())) * share
                if s["exchange"] in ex_cues:
                    strength = min(0.98, strength + 0.15)
                found.append({"sec": s, "how": "name", "surface": alias,
                              "strength": round(strength, 3)})

    # Tickers are uppercase tokens, so read the uppercase words out of the text
    # rather than testing all ~900 symbols against it.
    tic_by_sym = idx.get("tickers_by_sym") or {}
    # Two-character symbols are allowed because the only ones listed are real
    # issuers (KQ, NB, PZ); the exchange-cue rule below keeps them honest.
    upper = set(re.findall(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,11})(?![A-Za-z0-9])", text))
    for short in upper:
        for tic in tic_by_sym.get(short, ()):
            for s in idx["tickers"][tic]:
                if len(short) < 4 and s["exchange"] not in ex_cues:
                    continue  # too collision-prone without an exchange cue
                k = (s["exchange"], s["ticker"], s["name"])
                if k in seen:
                    continue
                seen.add(k)
                strength = 0.7 if len(short) >= 4 else 0.55
                if s["exchange"] in ex_cues:
                    strength += 0.15
                found.append({"sec": s, "how": "ticker", "surface": short,
                              "strength": round(min(strength, 0.95), 3)})

    found.sort(key=lambda x: -x["strength"])
    return found[:8], ex_cues


def match_themes(item):
    """Macro themes present in the item, with the theme's own direction.

    A theme may declare a `context` pattern that must also be present. A bare
    currency or price word is not a market story - "a 1.8m naira reward" is
    sport - so the currency and inflation themes require finance framing before
    they fire.
    """
    text_l = (item["title"] + " " + (item.get("summary") or "")).lower()
    out = []
    for th in THEMES:
        if not re.search(th["pat"], text_l):
            continue
        ctx = th.get("context")
        if ctx and not re.search(ctx, text_l):
            continue
        out.append({"theme": th, "direction": _theme_direction(text_l)})
    return out


def _recency(ts, now=None):
    """Half-life decay: a two-day-old wire is worth about half a fresh one."""
    now = now or time.time()
    age_h = max(0.0, (now - ts) / 3600.0)
    return math.exp(-age_h / 48.0)


def score_item(item, idx, now=None):
    """Turn one news item into zero or more per-exchange impact signals."""
    now = now or time.time()
    ents, ex_cues = match_entities(item, idx)
    themes = match_themes(item)
    if not ents and not themes:
        return []

    rec = _recency(item["ts"], now)
    conf = round(min(1.0, item["weight"] * (0.35 + 0.65 * rec)), 3)
    text_l = (item["title"] + " " + (item.get("summary") or "")).lower()
    corp_d, corp_s = _corp_direction(text_l)

    # exchange -> accumulating signal
    per_ex = {}

    def _bucket(ex):
        return per_ex.setdefault(ex, {
            "exchange": ex, "relevance": 0.0, "dir_num": 0.0, "dir_den": 0.0,
            "securities": [], "themes": [], "sectors": set(), "reasons": [],
        })

    for e in ents:
        s = e["sec"]
        b = _bucket(s["exchange"])
        b["relevance"] = max(b["relevance"], e["strength"])
        if s.get("sector"):
            b["sectors"].add(s["sector"])
        b["securities"].append({
            "ticker": s["ticker"], "name": s["name"], "sector": s["sector"],
            "matched_on": e["how"], "surface": e["surface"],
            "match_strength": e["strength"],
            "price": s.get("price"), "chgPct": s.get("chgPct"),
        })
        if corp_d:
            b["dir_num"] += corp_d * corp_s * e["strength"]
            b["dir_den"] += corp_s * e["strength"]

    for t in themes:
        th, tdir = t["theme"], t["direction"]
        for exp in th["exposures"]:
            ex = exp["ex"]
            # A macro theme only reaches a market that the story is plausibly
            # about: either the exposure is inherent (commodity/global) or the
            # text names that market.
            inherent = th["id"] in ("fed_rates", "oil", "gold", "pgm", "china", "risk_off")
            if not inherent and ex not in ex_cues:
                continue
            b = _bucket(ex)
            strength = exp["strength"] * (1.0 if ex in ex_cues else 0.7)
            b["relevance"] = max(b["relevance"], strength)
            if exp.get("sector"):
                b["sectors"].add(exp["sector"])
            if tdir:
                b["dir_num"] += tdir * exp["sign"] * strength
                b["dir_den"] += strength
            key = th["id"] + "|" + (exp.get("sector") or "")
            if key not in [x["_k"] for x in b["themes"]]:
                b["themes"].append({"_k": key, "id": th["id"], "label": th["label"],
                                    "sector": exp.get("sector"),
                                    "theme_direction": tdir, "note": th["note"]})

    # Generic sector cues sharpen a market-level signal into a sector one.
    for pat, sector in SECTOR_CUES:
        if re.search(pat, text_l):
            for ex in ex_cues:
                if ex in per_ex:
                    per_ex[ex]["sectors"].add(sector)

    out = []
    for ex, b in per_ex.items():
        direction = 0.0
        if b["dir_den"] > 0:
            direction = max(-1.0, min(1.0, b["dir_num"] / b["dir_den"]))
        impact = round(100.0 * b["relevance"] * conf, 1)
        if impact < 8:
            continue  # below this it is noise, not a signal
        for t in b["themes"]:
            t.pop("_k", None)
        out.append({
            "id": item["id"] + "-" + ex,
            "exchange": ex,
            "title": item["title"],
            "url": item["url"],
            "publisher": item["publisher"],
            "source_id": item["source_id"],
            "tier": item["tier"],
            "ts": int(item["ts"]),
            "impact": impact,
            "relevance": round(b["relevance"], 3),
            "confidence": conf,
            "direction": round(direction, 3),
            "bias": "bullish" if direction > 0.15 else ("bearish" if direction < -0.15 else "neutral"),
            "securities": b["securities"][:6],
            "sectors": sorted(b["sectors"]),
            "themes": b["themes"],
        })
    out.sort(key=lambda x: -x["impact"])
    return out


def score_all(items, idx, now=None):
    """Score every item; returns signals sorted by impact, highest first."""
    now = now or time.time()
    sigs = []
    for it in items:
        sigs.extend(score_item(it, idx, now))
    sigs.sort(key=lambda x: -x["impact"])
    return sigs
