"""
/api/reg — Regulatory wire for AFRI Terminal (spec section 8, P1).
Aggregates official regulator / central-bank releases across the four
markets into one scrolling feed. Spec calls this the trust differentiator:
no African retail terminal aggregates regulators.
Python stdlib ONLY (urllib + xml.etree), matching the architecture note.
No pip installs. Designed to be wired into afri_server.py's routing:
    from reg_api import handle_reg
    ...
    if parsed.path == "/api/reg":
        return self._send_json(handle_reg(cache=self._cache))
Sources (spec 8 — all verified reachable there): Google News RSS queries
scoped to each regulator's domain + name. Google News RSS is used rather
than scraping each regulator site directly because several of those sites
block datacenter IPs or sit behind bot challenges (documented dead ends
in the build spec) — the RSS layer is the reliable path.
Honesty rules kept from the rest of the app:
- Never fabricates items. A source that returns nothing contributes
  nothing; it isn't padded.
- Each item carries its regulator, country, headline, date, link, and a
  freshness note. The feed is cached (default 5 min) like the other
  news endpoints.
"""
import concurrent.futures
import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
# (regulator label, country, ISO, Google-News query)
# Queries combine the regulator's own domain with its name so results are
# official releases and coverage of them, not unrelated noise.
REG_SOURCES = [
    ("CMA",  "Kenya",        "KE", 'Capital Markets Authority Kenya OR site:cma.or.ke'),
    ("CBK",  "Kenya",        "KE", 'Central Bank of Kenya OR site:centralbank.go.ke'),
    ("SEC",  "Nigeria",      "NG", 'Securities and Exchange Commission Nigeria OR site:sec.gov.ng'),
    ("CBN",  "Nigeria",      "NG", 'Central Bank of Nigeria OR site:cbn.gov.ng'),
    ("FSCA", "South Africa", "ZA", 'FSCA South Africa OR site:fsca.co.za'),
    ("SARB", "South Africa", "ZA", 'South African Reserve Bank OR site:resbank.co.za'),
    ("FRA",  "Egypt",        "EG", 'Financial Regulatory Authority Egypt OR site:fra.gov.eg'),
    ("CBE",  "Egypt",        "EG", 'Central Bank of Egypt OR site:cbe.org.eg'),
]
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en"
USER_AGENT = "Mozilla/5.0 (compatible; AFRITerminal/1.0)"
FETCH_TIMEOUT = 8
MAX_PER_SOURCE = 6
CACHE_TTL_SECONDS = 300
def _parse_rss_date(text):
    """RFC-822 dates from Google News -> ISO 8601, tolerant of junk."""
    if not text:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.datetime.strptime(text.strip(), fmt)
            return dt.astimezone(datetime.timezone.utc).isoformat()
        except (ValueError, OverflowError):
            continue
    return None
def _fetch_source(source):
    label, country, iso, query = source
    url = GOOGLE_NEWS_RSS.format(q=urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    items = []
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception:
        # A dead/blocked/empty source contributes nothing — never faked.
        return items
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = _parse_rss_date(item.findtext("pubDate"))
        if not title or not link:
            continue
        # Google News prefixes " - Source" on titles; keep it, it's the
        # attribution, but expose the outlet separately when present.
        outlet = None
        if " - " in title:
            outlet = title.rsplit(" - ", 1)[-1].strip()
        items.append({
            "regulator": label,
            "country": country,
            "iso": iso,
            "headline": title,
            "outlet": outlet,
            "date": pub,
            "link": link,
        })
        if len(items) >= MAX_PER_SOURCE:
            break
    return items
def _sort_key(item):
    # Newest first; undated items sort last (None -> empty string).
    return item.get("date") or ""
def handle_reg(cache=None, cache_key="reg_wire"):
    """
    Return the aggregated regulator wire. If a cache dict-like is passed
    ({key: (expires_epoch, payload)}), reuse it with CACHE_TTL_SECONDS,
    matching afri_server.py's existing caching pattern.
    """
    import time
    now = time.time()
    if cache is not None:
        hit = cache.get(cache_key)
        if hit and hit[0] > now:
            return hit[1]
    all_items = []
    # Parallel fetch, bounded — matches the spec's non-blocking posture.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for result in ex.map(_fetch_source, REG_SOURCES):
            all_items.extend(result)
    all_items.sort(key=_sort_key, reverse=True)
    payload = {
        "count": len(all_items),
        "sources": [
            {"regulator": s[0], "country": s[1], "iso": s[2]} for s in REG_SOURCES
        ],
        "freshness": "aggregated via Google News RSS · cached {}s".format(CACHE_TTL_SECONDS),
        "items": all_items,
    }
    if cache is not None:
        cache[cache_key] = (now + CACHE_TTL_SECONDS, payload)
    return payload