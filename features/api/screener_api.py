"""
/api/screener — server-side equity screener for AFRI Terminal.
Written to the Feature Expansion Spec section 4 (P0) and the architecture
note in section 13: Python stdlib ONLY, no pip installs, designed to be
wired into the existing afri_server.py routing with one line.
INTEGRATION (in afri_server.py's do_GET, alongside the other /api/* routes):
    from screener_api import handle_screener
    ...
    if parsed.path == "/api/screener":
        payload = handle_screener(
            params,                      # parsed query dict (urllib.parse.parse_qs)
            load_stocks=load_stocks,     # your existing stocks.json loader -> list[dict]
            quote_lookup=heatmap_quote_lookup,  # sym -> {price, chgPct, volume, sector} or None
        )
        return self._send_json(payload)
The two injected callables keep this module decoupled from how your
server already loads data — it doesn't re-read files or re-fetch quotes,
it reuses whatever caches afri_server.py already maintains (spec 13: the
heatmap payload already has price/chgPct/volume/sector for every stock).
Honest data-freshness labels (spec 12/13): each result row carries a
`live` flag copied from the stock record — JSE/EGX are live, NGX/NSE are
EOD — so the client can label every row truthfully.
"""
from typing import Callable, Optional
def _to_float(value, default=None):
    """Parse a query-string value to float, tolerating '', None, junk."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value in (None, "", "null", "undefined"):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
def _first(value):
    """parse_qs gives lists; take the first, tolerate scalars."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value
def _multi(value):
    """Comma-joined or repeated query param -> list of upper-case tokens."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw = ",".join(str(v) for v in value)
    else:
        raw = str(value)
    return [tok.strip().upper() for tok in raw.split(",") if tok.strip()]
def _display_ticker(stock):
    """short > ticker > sym-stripped, per the master-file rule (build spec)."""
    return (
        stock.get("short")
        or stock.get("ticker")
        or (stock.get("sym") or "").split(".")[0]
    )
def _dividend_yield(stock, price):
    """
    yield = last dividend / price, per spec 4. Dividend history lives in
    fundamentals.json keyed elsewhere; a stock record may carry a
    precomputed `last_div` (annual) — use it when present, else None.
    Never fabricate: no data -> None, and the row simply won't pass a
    dividend-yield filter.
    """
    last_div = _to_float(stock.get("last_div"))
    if last_div is None or not price or price <= 0:
        return None
    return round((last_div / price) * 100, 2)
def handle_screener(
    params: dict,
    load_stocks: Callable[[], list],
    quote_lookup: Callable[[str], Optional[dict]],
) -> dict:
    """
    Filter the full universe (768 stocks) by the spec's criteria and
    return a sortable result set. Pure function of its inputs — trivially
    testable without a running server (see test at bottom).
    """
    exchanges = set(_multi(params.get("exchange")))
    sector = _first(params.get("sector"))
    sector = sector.strip().lower() if sector else None
    currency = _first(params.get("currency"))
    currency = currency.strip().upper() if currency else None
    price_min = _to_float(params.get("price_min"))
    price_max = _to_float(params.get("price_max"))
    chg_min = _to_float(params.get("chg_min"))
    chg_max = _to_float(params.get("chg_max"))
    vol_min = _to_float(params.get("vol_min"))
    div_yield_min = _to_float(params.get("div_yield_min"))
    sort_key = (_first(params.get("sort")) or "chgPct").strip()
    sort_desc = (_first(params.get("dir")) or "desc") != "asc"
    rows = []
    for stock in load_stocks():
        sym = stock.get("sym")
        if not sym:
            continue
        stock_exchange = (stock.get("exchange") or "").upper()
        if exchanges and stock_exchange not in exchanges:
            continue
        if currency and (stock.get("currency") or "").upper() != currency:
            continue
        quote = quote_lookup(sym) or {}
        price = _to_float(quote.get("price"), _to_float(stock.get("price")))
        chg_pct = _to_float(quote.get("chgPct"))
        volume = _to_float(quote.get("volume"))
        row_sector = quote.get("sector") or stock.get("sector") or "Other"
        # guard: sector can arrive as float NaN from TradingView dumps
        if not isinstance(row_sector, str):
            row_sector = "Other"
        # Numeric filters — a None value fails a set bound (can't confirm
        # it qualifies), rather than silently passing.
        if price_min is not None and (price is None or price < price_min):
            continue
        if price_max is not None and (price is None or price > price_max):
            continue
        if chg_min is not None and (chg_pct is None or chg_pct < chg_min):
            continue
        if chg_max is not None and (chg_pct is None or chg_pct > chg_max):
            continue
        if vol_min is not None and (volume is None or volume < vol_min):
            continue
        if sector and row_sector.lower() != sector:
            continue
        dy = _dividend_yield(stock, price)
        if div_yield_min is not None and (dy is None or dy < div_yield_min):
            continue
        rows.append(
            {
                "sym": sym,
                "ticker": _display_ticker(stock),
                "name": stock.get("name") or sym,
                "exchange": stock_exchange,
                "sector": row_sector,
                "currency": stock.get("currency"),
                "price": price,
                "chgPct": chg_pct,
                "volume": volume,
                "divYield": dy,
                # Honest freshness flag (spec 13): live for JSE/EGX, EOD otherwise.
                "live": bool(stock.get("live", stock_exchange in ("JSE", "EGX"))),
            }
        )
    # Sort so that rows with a real value always come before rows with
    # no data (None), in BOTH directions — "no data" is never ranked
    # above an actual number. We can't lean on a (is_none, value) tuple
    # with reverse=True because reverse would flip the is-none grouping
    # too; instead sort the has-data rows and the no-data rows separately
    # and always append no-data last.
    def key_val(r):
        return r.get(sort_key)
    has_data = [r for r in rows if key_val(r) is not None]
    no_data = [r for r in rows if key_val(r) is None]
    has_data.sort(key=key_val, reverse=sort_desc)
    # Stable secondary order for the no-data tail: by display ticker, so
    # results are deterministic rather than dependent on scan order.
    no_data.sort(key=lambda r: r.get("ticker") or "")
    rows = has_data + no_data
    return {
        "count": len(rows),
        "filters_applied": {
            "exchange": sorted(exchanges) if exchanges else "all",
            "sector": sector or "all",
            "currency": currency or "all",
            "price_min": price_min, "price_max": price_max,
            "chg_min": chg_min, "chg_max": chg_max,
            "vol_min": vol_min, "div_yield_min": div_yield_min,
        },
        "sort": {"key": sort_key, "dir": "desc" if sort_desc else "asc"},
        "stocks": rows,
    }