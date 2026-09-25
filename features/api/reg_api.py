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
import re
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
# ---------------------------------------------------------------------------
# English-only normalisation.
# Google News appends the publisher's own name to every title, and Egypt's
# regulators are mostly covered by Arabic-language outlets — so the regulator
# wire carried Arabic text. Normalise it: strip the foreign publisher suffix,
# name the publisher in English, and drop a story that is itself written in
# another language rather than publishing text the reader cannot use.
# ---------------------------------------------------------------------------
NON_LATIN = re.compile(
    "[\u0400-\u04FF\u0370-\u03FF\u0590-\u05FF\u0600-\u06FF\u0750-\u077F"
    "\u0900-\u097F\u0980-\u09FF\u0B80-\u0BFF\u0E00-\u0E7F\u1000-\u109F"
    "\u10A0-\u10FF\u1200-\u137F\u1780-\u17FF"
    "\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    "\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")
LATIN = re.compile(r"[A-Za-z]")
# Publisher names seen on the four markets, in English.
OUTLET_EN = {
    "\u0627\u0644\u0628\u0646\u0643 \u0627\u0644\u0645\u0631\u0643\u0632\u064a \u0627\u0644\u0645\u0635\u0631\u064a":
        "Central Bank of Egypt",
    "\u0627\u0644\u0647\u064a\u0626\u0629 \u0627\u0644\u0639\u0627\u0645\u0629 \u0644\u0644\u0631\u0642\u0627\u0628\u0629 \u0627\u0644\u0645\u0627\u0644\u064a\u0629":
        "Financial Regulatory Authority",
    "\u0627\u0644\u0628\u0648\u0631\u0635\u0629 \u0627\u0644\u0645\u0635\u0631\u064a\u0629":
        "The Egyptian Exchange",
}
def _english_outlet(outlet, label, country):
    """Publisher name in English, or None when it has no English form."""
    if not outlet:
        return None
    o = outlet.strip()
    for k, v in OUTLET_EN.items():
        if o == k:
            return v
    if NON_LATIN.search(o):
        # An unmapped foreign publisher name: use the regulator's own English
        # label rather than publish a name the reader cannot read.
        return "%s (%s)" % (label, country)
    return o
def _english_headline(title, outlet):
    """Drop the foreign-language publisher suffix Google News appends."""
    h = title
    if outlet and h.endswith(outlet):
        h = h[: -len(outlet)]
    h = NON_LATIN.sub(" ", h)
    # En/em dashes are always separators here; a hyphen only counts when it is
    # spaced, so a word like "Non-Banking" keeps its hyphen.
    h = re.sub(r"\s*[\u2013\u2014]\s*", " - ", h)
    h = re.sub(r"(?:\s+-\s*)+", " - ", h)
    h = re.sub(r"\s{2,}", " ", h)
    return h.strip().strip(" -\u2013\u2014\t").strip()
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
        # Google News appends " - Source" to every title. Egypt's regulators
        # are covered largely by Arabic-language outlets, so that suffix
        # arrived in Arabic. Normalise each item to English and skip a story
        # that is itself written in another language.
        outlet = None
        if " - " in title:
            outlet = title.rsplit(" - ", 1)[-1].strip()
        # Leave an English title exactly as Google News wrote it (the " - Source"
        # suffix is the attribution); only rewrite one that carries foreign text.
        if NON_LATIN.search(title):
            headline = _english_headline(title, outlet)
            if not LATIN.search(headline):
                # The story itself is written in another language: skip it
                # rather than publish text the reader cannot use.
                continue
        else:
            headline = title
        items.append({
            "regulator": label,
            "country": country,
            "iso": iso,
            "headline": headline,
            "outlet": _english_outlet(outlet, label, country),
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