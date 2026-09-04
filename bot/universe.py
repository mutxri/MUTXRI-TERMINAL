#!/usr/bin/env python3
"""bot/universe.py - the securities universe the bot reasons about.

Loads every listed security the terminal already tracks (static_data/listing_<EX>.json,
enriched from market_<EX>.json) and builds the lookup index used to decide which
headline is about which company.

Matching is deliberately conservative: a false ticker hit is worse than a miss,
because a wrong link puts a wrong story on a real company's tape.
"""
import json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(BASE, "static_data")

EXCHANGES = ["NSE", "NGX", "JSE", "EGX"]

EX_META = {
    "NSE": {"name": "Nairobi Securities Exchange", "country": "Kenya",
            "currency": "KES", "ccy_words": ["shilling", "kes"]},
    "NGX": {"name": "Nigerian Exchange", "country": "Nigeria",
            "currency": "NGN", "ccy_words": ["naira", "ngn"]},
    "JSE": {"name": "Johannesburg Stock Exchange", "country": "South Africa",
            "currency": "ZAR", "ccy_words": ["rand", "zar"]},
    "EGX": {"name": "Egyptian Exchange", "country": "Egypt",
            "currency": "EGP", "ccy_words": ["egyptian pound", "egp"]},
}

# Corporate-form noise stripped before name matching. Order matters (longest first).
_SUFFIXES = [
    "public limited company", "company limited", "and company", "holdings limited",
    "investments limited", "group limited", "corporation", "incorporated",
    "holdings", "holding", "limited", "company", "group", "plc.", "plc", "ltd.",
    "ltd", "inc.", "inc", "s.a.e.", "sae", "n.v.", "nv", "co.", "co",
]
# Words that carry no issuer identity on their own: articles, geography, and
# the common business nouns that half these boards share. A surface built only
# from these is not evidence - "middle east" would tag every Gulf story onto a
# glass manufacturer, and "the egyptian" would tag every Egypt story onto a
# school operator. An alias is kept only if at least one word is outside this set.
_GENERIC = {
    "the", "and", "for", "of", "el", "al", "co", "company", "companies",
    "national", "general", "international", "modern", "new", "first", "prime",
    "standard", "united", "central", "premier", "royal", "global", "universal",
    "african", "africa", "east", "eastern", "west", "western", "south",
    "southern", "north", "northern", "middle", "arab", "arabia", "arabian",
    "egypt", "egyptian", "kenya", "kenyan", "nigeria", "nigerian", "delta",
    "cairo", "lagos", "nairobi", "johannesburg", "misr", "nile",
    "development", "developments", "investment", "investments", "industries",
    "industrial", "industry", "bank", "banks", "banking", "insurance",
    "assurance", "trust", "fund", "funds", "energy", "power", "cement",
    "mining", "mines", "media", "press", "food", "foods", "sugar", "oil",
    "gas", "petroleum", "properties", "property", "real", "estate", "capital",
    "finance", "financial", "services", "service", "exchange", "market",
    "markets", "trading", "trade", "commercial", "business", "corp",
    "manufacturing", "products", "works", "projects", "contracting",
    "engineering", "technologies", "technology", "systems", "solutions",
    "education", "housing", "transport", "tourism", "hotels", "resorts",
    "agricultural", "agriculture", "chemicals", "textile", "textiles",
    "paper", "steel", "iron", "glass", "ceramics", "pharmaceutical",
    "pharmaceuticals", "medical", "health", "life", "land", "reclamation",
    "natural", "project", "projects", "holding", "cooperative", "co-operative",
    "resources", "mineral", "minerals", "water", "electric", "electricity",
}
# Kept for callers that want the older single-word notion of "too generic".
_STOPCORES = _GENERIC
# Instrument kinds that are not operating companies - no news should be pinned on them.
_SKIP_SECTORS = {"etf", "etfs & structured", "etfs", "structured"}

# Real issuers whose name is also an ordinary English word. Dropping them would
# lose major constituents (Equity Group, Zenith Bank, Discovery, Clicks), so
# they are kept but the matcher demands an exchange or country cue in the same
# text before pinning news on them - otherwise "unequal access" tags Access Corp.
AMBIGUOUS_SURFACES = {
    "access", "anchor", "austin", "champion", "clicks", "cornerstone",
    "coronation", "custodian", "discovery", "equity", "fidelity", "imperial",
    "infinity", "initiates", "jubilee", "legend", "liberty", "livestock",
    "momentum", "numeral", "prestige", "purple", "thomas", "veritas", "zenith",
    "anchor", "linkage", "sebata", "legend", "champion", "prime", "unity",
}


def _norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).strip()


def _core(name):
    """Strip corporate suffixes/qualifiers down to the distinctive part of a name."""
    n = _norm(name)
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if n.endswith(" " + suf) or n == suf:
                n = n[: len(n) - len(suf)].strip()
                changed = True
    n = re.sub(r"^the\s+", "", n)
    # Some upstream listings truncate names mid-word ("... Education S"), which
    # leaves a dangling initial. Drop trailing one-letter fragments.
    n = re.sub(r"(?:\s+[a-z])+$", "", n)
    return re.sub(r"\s+", " ", n).strip()


def _distinctive(alias):
    """True if the alias carries at least one word that identifies an issuer."""
    words = alias.split()
    if not words:
        return False
    if all(w in _GENERIC for w in words):
        return False
    # A single word must be long enough not to collide with ordinary prose.
    if len(words) == 1 and len(words[0]) < 6:
        return False
    return True


def _aliases(name, core):
    """Surface forms worth matching: the full core plus its leading prefixes.

    Prefixes let "british american tobacco kenya" also match the way headlines
    usually write it, but every candidate must still be distinctive - otherwise
    a prefix like "middle east" becomes a magnet for unrelated news.
    """
    out = set()
    if core:
        out.add(core)
        w = core.split()
        if len(w) > 3:
            out.add(" ".join(w[:3]))
        if len(w) > 2:
            out.add(" ".join(w[:2]))
    return {a for a in out if len(a) >= 5 and _distinctive(a)}


# The widest credible one-day move per exchange, matching MAX_MOVE in
# build_market_snapshots.py. A move past the cap means the previous close came
# from a different price scale (cents vs units, or an unadjusted split), not a
# real session.
MAX_MOVE = {"JSE": 50.0, "EGX": 25.0, "NGX": 15.0, "NSE": 15.0}


def _rows(ex):
    """Merge listing_<EX>.json with market_<EX>.json for the fullest picture.

    The two files key securities differently: listing_JSE calls Absa "ABG.JO"
    while market_JSE stores ticker "ABG" with sym "ABG.JO". Indexing the market
    file under both keys matters - keying it on ticker alone matched 0 of 431 JSE
    rows, so every JSE security silently ran on listing data only, without the
    sanitising that build_market_snapshots.py applies.
    """
    listing = os.path.join(SD, f"listing_{ex}.json")
    market = os.path.join(SD, f"market_{ex}.json")
    rows = []
    if os.path.exists(listing):
        d = json.load(open(listing, encoding="utf-8"))
        rows = d.get("stocks", d if isinstance(d, list) else [])
    mkt = {}
    if os.path.exists(market):
        d = json.load(open(market, encoding="utf-8"))
        for s in d.get("stocks", d if isinstance(d, list) else []):
            for k in (s.get("ticker"), s.get("sym")):
                if k:
                    mkt.setdefault(k, s)
    for r in rows:
        # The listing's own identifier is what the terminal displays, and it
        # differs by exchange: JSE listings identify as "ABG.JO" while EGX
        # listings use the readable "INFI" rather than the ISIN-style sym. Keep
        # it through the merge so market_<EX>'s internal ticker form does not
        # rename securities.
        display = r.get("ticker") or r.get("sym")
        m = None
        for k in (r.get("ticker"), r.get("sym")):
            if k and k in mkt:
                m = mkt[k]
                break
        if m is not None:
            merged = dict(m)
            merged.update({a: b for a, b in r.items() if b not in (None, "")})
            r.clear()
            r.update(merged)
        if display:
            r["ticker"] = display

    # Same cap the upstream builder applies, enforced again here because the
    # listing file keeps the raw figure the builder deliberately nulled, and the
    # merge above lets a non-null listing value win.
    cap = MAX_MOVE.get(ex, 50.0)
    for r in rows:
        c = r.get("chgPct")
        if isinstance(c, (int, float)) and abs(c) > cap:
            r["chgPct"] = None
            r["chgFlag"] = "suspect-baseline"
    return rows


def load():
    """Return {ex: [security, ...]} for every exchange with data on disk."""
    uni = {}
    for ex in EXCHANGES:
        secs = []
        for r in _rows(ex):
            tic = r.get("ticker") or r.get("sym")
            name = r.get("name") or ""
            if not name:
                continue
            sector = r.get("sector") or ""
            if sector.strip().lower() in _SKIP_SECTORS:
                continue
            core = _core(name)
            secs.append({
                "exchange": ex,
                "ticker": tic,
                "chgFlag": r.get("chgFlag"),
                "name": name,
                "sector": sector,
                "country": r.get("country") or EX_META[ex]["country"],
                "currency": r.get("currency") or EX_META[ex]["currency"],
                "price": r.get("price", r.get("ltp")),
                "chgPct": r.get("chgPct"),
                "volume": r.get("volume"),
                "marketCap": r.get("marketCap"),
                "core": core,
                "aliases": sorted(_aliases(name, core)),
            })
        if secs:
            uni[ex] = secs
    return uni


def build_index(uni):
    """Build the matcher index.

    name_index : alias -> [security, ...]   (matched as a whole phrase)
    tic_index  : TICKER -> [security, ...]  (matched as an uppercase word)
    Ambiguous surfaces (same alias on several companies) are kept but the
    matcher downgrades them, since we cannot tell which issuer was meant.
    """
    name_index, tic_index = {}, {}
    for ex, secs in uni.items():
        for s in secs:
            for a in s["aliases"]:
                name_index.setdefault(a, []).append(s)
            t = (s.get("ticker") or "").strip().upper()
            if t and re.fullmatch(r"[A-Z][A-Z0-9.\-]{1,11}", t):
                tic_index.setdefault(t, []).append(s)
    # Testing all ~1.4k aliases against every headline is ~1M regex scans per
    # run. Bucketing aliases by their first word lets the matcher consider only
    # the handful whose opening token actually occurs in the text.
    by_first = {}
    for a in name_index:
        by_first.setdefault(a.split()[0], []).append(a)
    # Same idea for tickers, keyed on the pre-suffix symbol.
    tic_by_sym = {}
    for t in tic_index:
        tic_by_sym.setdefault(t.upper().split(".")[0], []).append(t)
    return {"names": name_index, "tickers": tic_index,
            "names_by_first": by_first, "tickers_by_sym": tic_by_sym}


if __name__ == "__main__":
    u = load()
    idx = build_index(u)
    for ex, s in u.items():
        print(f"{ex}: {len(s)} securities")
    print(f"index: {len(idx['names'])} name surfaces, {len(idx['tickers'])} tickers")
    for ex in u:
        print(" sample", ex, [(x['ticker'], x['core']) for x in u[ex][:3]])
