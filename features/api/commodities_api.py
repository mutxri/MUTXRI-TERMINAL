"""
/api/commodities — Global Commodities board for AFRI Terminal (spec 9.1, P2).
African angle, per spec: gold & platinum (South Africa), cocoa (Ghana /
Cote d'Ivoire), coffee & tea (Kenya / Ethiopia / Uganda). The board shows
the globally-priced commodity plus a note on why it matters to African
markets — a genuine differentiator over a generic commodity ticker.
Python stdlib ONLY (urllib + json), matching the architecture note.
Wired into afri_server.py:
    from commodities_api import handle_commodities
    ...
    if parsed.path == "/api/commodities":
        return self._send_json(handle_commodities(cache=self._cache))
Data source: Yahoo chart API on commodity futures symbols (spec 9.1 /
section 12 — verified working, no auth). Same fetch discipline as the
rest of the app: parallel, short timeouts, cached, and a commodity that
fails to fetch is returned with nulls + a flag, never faked.
"""
import concurrent.futures
import json
import time
import urllib.request
# (symbol, display, unit, African relevance) — spec 9.1 list + the
# explicit African-angle note the spec calls for.
COMMODITIES = [
    ("GC=F", "Gold",     "USD/oz",  "South Africa — major producer/exporter"),
    ("PL=F", "Platinum", "USD/oz",  "South Africa — ~70% of world supply"),
    ("SI=F", "Silver",   "USD/oz",  "Precious-metals complex"),
    ("BZ=F", "Brent",    "USD/bbl", "Nigeria/Angola crude benchmark"),
    ("CL=F", "WTI",      "USD/bbl", "Global oil reference"),
    ("CC=F", "Cocoa",    "USD/t",   "Ghana & Cote d'Ivoire — ~60% of world supply"),
    ("KC=F", "Coffee",   "USd/lb",  "Ethiopia, Kenya, Uganda — key exporters"),
    ("SB=F", "Sugar",    "USd/lb",  "Widely produced across the continent"),
    ("ZC=F", "Corn",     "USd/bu",  "Staple; SA a regional exporter"),
    ("ZW=F", "Wheat",    "USd/bu",  "Major African import — food-security signal"),
]
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d"
USER_AGENT = "Mozilla/5.0 (compatible; AFRITerminal/1.0)"
FETCH_TIMEOUT = 8
CACHE_TTL_SECONDS = 120
def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
def _fetch_one(spec):
    sym, name, unit, note = spec
    row = {
        "sym": sym, "name": name, "unit": unit, "africa": note,
        "price": None, "prevClose": None, "chgPct": None,
        "spark": [], "ok": False,
    }
    url = YAHOO_CHART.format(sym=sym)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception:
        # Failed fetch: nulls + ok:false, never a fabricated price.
        return row
    try:
        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        price = _safe_float(meta.get("regularMarketPrice"))
        prev = _safe_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        closes = []
        try:
            raw_closes = result["indicators"]["quote"][0]["close"]
            closes = [c for c in raw_closes if c is not None]
        except (KeyError, IndexError, TypeError):
            closes = []
        if price is None and closes:
            price = _safe_float(closes[-1])
        if prev is None and len(closes) >= 2:
            prev = _safe_float(closes[-2])
        chg = None
        if price is not None and prev not in (None, 0):
            chg = round((price - prev) / prev * 100, 2)
        row.update({
            "price": price,
            "prevClose": prev,
            "chgPct": chg,
            # Downsample the month of closes to a compact sparkline (<=30).
            "spark": [round(c, 4) for c in closes][-30:],
            "ok": price is not None,
        })
    except (KeyError, IndexError, TypeError):
        return row  # malformed payload -> nulls, still no fabrication
    return row
def handle_commodities(cache=None, cache_key="commodities"):
    now = time.time()
    if cache is not None:
        hit = cache.get(cache_key)
        if hit and hit[0] > now:
            return hit[1]
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_fetch_one, COMMODITIES))
    ok_count = sum(1 for r in rows if r["ok"])
    payload = {
        "count": len(rows),
        "live": ok_count,
        "freshness": "Yahoo futures · cached {}s · {}/{} live".format(
            CACHE_TTL_SECONDS, ok_count, len(rows)
        ),
        "commodities": rows,
    }
    if cache is not None:
        cache[cache_key] = (now + CACHE_TTL_SECONDS, payload)
    return payload