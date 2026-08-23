"""
indices_api.py  -  Real market index / ticker-tape endpoint for the terminal.

WHY THIS EXISTS
---------------
The top ticker tape was showing placeholder values (AMC010, AMC012, ... with
sequential IDs and round index-like numbers). In a financial terminal a
fabricated number on the most prominent strip on screen destroys trust. This
module replaces it with REAL data only, and honestly shows nothing where a real
source does not exist.

DESIGN (same ethos as the rest of the terminal: never fabricate)
----------------------------------------------------------------
Two kinds of tape entries, both real:

1. OFFICIAL INDICES - fetched from the same upstream quote feed the server
   already uses (Yahoo). Only indices with a verified, working symbol are
   included:
       EGX 30            ^CASE30    (Egypt, EGP, delayed)
       JSE Top 40        ^J200.JO   (South Africa, ZAR)
       JSE All-Share     ^J203.JO   (South Africa, ZAR)
       JSE Top 40 USD    ^JN0U.JO   (South Africa, USD)
   Nigeria (NGX ASI) and Kenya (NSE 20 / NASI) are deliberately NOT faked:
   they are not available on the free feed. They appear only if the server is
   given a real value (see `extra_indices`), otherwise they are omitted.

2. BASKET PROXIES (optional, clearly labelled) - for markets with no free
   official index symbol, an equal-weight change-% basket can be computed from
   REAL constituent quotes the server already has. These are labelled
   kind="basket" and name suffixed " (basket)" so they are never mistaken for
   the official index.

The handler returns JSON; afri_server.py wires GET /api/indices to
`build_tape(...)`. All network fetching is injected via `quote_fn` so this
module stays pure-stdlib and unit-testable with no network.
"""

from datetime import datetime, timezone

# ---- verified official index registry -------------------------------------
# symbol -> (display name, market, currency)
OFFICIAL_INDICES = [
    {"symbol": "^CASE30",  "name": "EGX 30",        "market": "EGX", "currency": "EGP"},
    {"symbol": "^J200.JO", "name": "JSE Top 40",    "market": "JSE", "currency": "ZAR"},
    {"symbol": "^J203.JO", "name": "JSE All-Share", "market": "JSE", "currency": "ZAR"},
    {"symbol": "^JN0U.JO", "name": "JSE Top40 USD", "market": "JSE", "currency": "USD"},
]


def _round(x, n=2):
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def normalize_quote(raw):
    """Turn one upstream quote dict into a tape entry, or None if unusable.

    Expected upstream keys (Yahoo-style), all optional/defensive:
      regularMarketPrice, regularMarketChange, regularMarketChangePercent,
      regularMarketPreviousClose, marketState
    Never invents values: missing price -> None (caller drops or shows dash).
    """
    if not isinstance(raw, dict):
        return None
    price = _round(raw.get("regularMarketPrice"))
    if price is None:
        return None
    chg = _round(raw.get("regularMarketChange"))
    chg_pct = _round(raw.get("regularMarketChangePercent"))
    prev = _round(raw.get("regularMarketPreviousClose"))
    # derive change from prev close if upstream omitted it (still real, not faked)
    if chg is None and prev is not None:
        chg = _round(price - prev)
    if chg_pct is None and prev not in (None, 0):
        chg_pct = _round((price - prev) / prev * 100.0)
    return {"price": price, "change": chg, "changePct": chg_pct,
            "state": raw.get("marketState")}


def compute_basket(quotes):
    """Equal-weight average change-% across REAL constituent quotes.

    quotes: list of upstream quote dicts (constituents of one market).
    Returns changePct (float) or None if nothing usable. This is an UNOFFICIAL
    proxy - the caller must label it as a basket. We use equal-weight change%
    (not a level) precisely so we never publish a fake index *level*.
    """
    pcts = []
    for q in quotes or []:
        n = normalize_quote(q)
        if n and n["changePct"] is not None:
            pcts.append(n["changePct"])
    if not pcts:
        return None
    return _round(sum(pcts) / len(pcts))


def build_tape(quote_fn, extra_indices=None, basket_constituents=None):
    """Assemble the tape.

    quote_fn(symbols:list[str]) -> dict[symbol] = raw upstream quote dict.
                                    Injected by the server (Yahoo call). If it
                                    raises or returns partial data we degrade
                                    gracefully and never fabricate.
    extra_indices: optional list of dicts for REAL indices the server sourced
                   elsewhere, e.g. NGX ASI / NSE 20 from an official page:
                   {"name","market","currency","price","change","changePct"}.
    basket_constituents: optional dict market -> list[raw quote dicts] to build
                   clearly-labelled basket proxies for markets with no official
                   free index (e.g. {"NGX":[...], "NSE":[...]}).

    Returns: {"asOf":iso, "entries":[...], "note":str}
    """
    entries = []

    # 1) official indices via the injected feed
    symbols = [ix["symbol"] for ix in OFFICIAL_INDICES]
    fetched = {}
    try:
        fetched = quote_fn(symbols) or {}
    except Exception:
        fetched = {}  # degrade: show basket/extra only, never fake index levels

    for ix in OFFICIAL_INDICES:
        n = normalize_quote(fetched.get(ix["symbol"]))
        if not n:
            continue  # omit rather than fabricate
        entries.append({
            "label": ix["name"], "market": ix["market"], "currency": ix["currency"],
            "kind": "index", "official": True,
            "price": n["price"], "change": n["change"], "changePct": n["changePct"],
            "state": n["state"],
        })

    # 2) real indices supplied by the server from another source
    for ix in (extra_indices or []):
        if ix.get("price") is None and ix.get("changePct") is None:
            continue
        entries.append({
            "label": ix.get("name", "?"), "market": ix.get("market"),
            "currency": ix.get("currency"), "kind": "index",
            "official": bool(ix.get("official", True)),
            "price": _round(ix.get("price")), "change": _round(ix.get("change")),
            "changePct": _round(ix.get("changePct")), "state": ix.get("state"),
        })

    # 3) clearly-labelled basket proxies where no official index is available
    for market, cons in (basket_constituents or {}).items():
        pct = compute_basket(cons)
        if pct is None:
            continue
        entries.append({
            "label": market + " (basket)", "market": market, "currency": None,
            "kind": "basket", "official": False,
            "price": None, "change": None, "changePct": pct, "state": None,
        })

    note = ("Official indices via market feed; entries marked 'basket' are "
            "unofficial equal-weight proxies from real constituents. Markets "
            "without a licensed free index are omitted, never estimated.")
    return {"asOf": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entries": entries, "note": note}
