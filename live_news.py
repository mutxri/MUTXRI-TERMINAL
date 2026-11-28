#!/usr/bin/env python3
"""live_news.py - the live market wire behind the NEWS panel.

The NEWS panel used to read only the static_data snapshots, which the sweep
rebuilds every few hours, so a central-bank decision or an oil move reached the
panel hours after it reached the market. This module keeps a rolling wire in
memory instead: a background thread polls market-scoped feeds every
POLL_SECONDS and the panel asks /api/news/live for whatever arrived since.

What this module does and does not do:

  * It AGGREGATES. Every feed below is already market-scoped (a business desk,
    a markets wire, or a Google News query that names a market, a central bank
    or a commodity), so there is no relevance scoring here.
  * It does NOT score or tag. Which market, sector or holding a story reaches
    is decided in the panel (features/panels/mx_news.html, tagStory), so the
    snapshot rows and the live rows are read by one rule set, and the read of
    a reader's own holdings never leaves their browser.
  * It never invents a time. An item with no publication stamp is dropped
    rather than stamped with the moment it was seen, which would print it as
    fresh news.

Stdlib only, like the rest of the backend.
"""
import hashlib, html, json, re, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET
import datetime as _dt

POLL_SECONDS = 120          # how often the wire is re-read while the service is awake
KEEP_HOURS = 72             # a live wire is the last three days, not an archive
MAX_ITEMS = 600             # memory bound across every exchange
FUTURE_SLACK = 3600         # a stamp more than an hour ahead is a broken feed
FETCH_TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _gn(query, window="1d"):
    """Google News RSS for a query, limited to the last `window`."""
    return ("https://news.google.com/rss/search?q=" +
            urllib.parse.quote(query + " when:" + window) +
            "&hl=en-US&gl=US&ceid=US:en")


# (source_id, url, home exchange or None for a cross-market wire)
# The local lists follow bot/sources.py LOCAL_FEEDS, trimmed to the desks that
# file market news fastest; the global list is markets wires only.
FEEDS = [
    # --- Kenya / NSE
    ("gn-nse", _gn('"Nairobi Securities Exchange" OR "NSE Kenya" OR "Nairobi bourse" OR "Kenyan shilling"'), "NSE"),
    ("gn-ke-co", _gn('("Safaricom" OR "Equity Group" OR "KCB Group" OR "EABL" OR "Co-operative Bank" '
                     'OR "Britam" OR "Kenya Power" OR "NCBA" OR "Stanbic Kenya" OR "Absa Kenya") Kenya'), "NSE"),
    ("gn-ke-macro", _gn('"Central Bank of Kenya" OR "Kenya Treasury" OR "Kenya inflation" OR '
                        '"Kenya Revenue Authority" OR "Kenya Finance Bill" OR "Kenya Eurobond"'), "NSE"),
    ("bd-ke", "https://www.businessdailyafrica.com/bd/rss.xml", "NSE"),
    ("capitalfm-biz", "https://www.capitalfm.co.ke/business/feed/", "NSE"),
    ("standard-biz", "https://www.standardmedia.co.ke/rss/business.php", "NSE"),
    ("khusoko", "https://khusoko.com/feed/", "NSE"),
    # --- Nigeria / NGX
    ("gn-ngx", _gn('"Nigerian Exchange" OR "NGX All-Share" OR naira OR "Central Bank of Nigeria"'), "NGX"),
    ("nairametrics", "https://nairametrics.com/feed/", "NGX"),
    ("businessday-ng", "https://businessday.ng/feed/", "NGX"),
    ("businessday-markets", "https://businessday.ng/category/markets/feed/", "NGX"),
    # --- South Africa / JSE
    ("gn-jse", _gn('"Johannesburg Stock Exchange" OR "JSE All Share" OR "South African Reserve Bank" OR rand'), "JSE"),
    ("moneyweb", "https://www.moneyweb.co.za/feed/", "JSE"),
    ("moneyweb-markets", "https://www.moneyweb.co.za/category/markets/feed/", "JSE"),
    ("miningmx", "https://www.miningmx.com/rss", "JSE"),
    # --- Egypt / EGX
    ("gn-egx", _gn('"EGX 30" OR "Egyptian Exchange" OR "Egyptian pound" OR "Central Bank of Egypt"'), "EGX"),
    ("enterprise-eg", "https://enterprise.news/feed/", "EGX"),
    ("dailynewsegypt-biz", "https://www.dailynewsegypt.com/category/business/feed/", "EGX"),
    # --- cross-market: the macro that moves every frontier board
    ("gn-macro", _gn('"Federal Reserve" OR FOMC OR "Treasury yields" OR "oil prices" OR Brent OR OPEC '
                     'OR "gold prices" OR "emerging markets" OR "dollar index"'), None),
    ("gn-africa-mkts", _gn('Africa (stocks OR equities OR eurobond OR IMF OR "sovereign rating") '
                           '(Kenya OR Nigeria OR "South Africa" OR Egypt)'), None),
    ("cnbc-markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", None),
    ("cnbc-world", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362", None),
    ("marketwatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", None),
    ("oilprice", "https://oilprice.com/rss/main", None),
    ("investing-com", "https://www.investing.com/rss/news_25.rss", None),
    ("allafrica-business", "https://allafrica.com/tools/headlines/rdf/business/headlines.rdf", None),
]

EXCHANGES = ("NSE", "NGX", "JSE", "EGX")

# The name printed in the SOURCE column for a direct feed (a Google News item
# names its own publisher in <source>).
PUBLISHER = {
    "bd-ke": "Business Daily", "capitalfm-biz": "Capital FM", "standard-biz": "The Standard",
    "khusoko": "Khusoko", "nairametrics": "Nairametrics",
    "businessday-ng": "BusinessDay NG", "businessday-markets": "BusinessDay NG",
    "moneyweb": "Moneyweb", "moneyweb-markets": "Moneyweb", "miningmx": "Miningmx",
    "enterprise-eg": "Enterprise", "dailynewsegypt-biz": "Daily News Egypt",
    "cnbc-markets": "CNBC", "cnbc-world": "CNBC", "marketwatch": "MarketWatch",
    "oilprice": "OilPrice.com", "investing-com": "Investing.com", "allafrica-business": "AllAfrica",
}

_lock = threading.Lock()
_items = {}                 # key -> item
_state = {"updated": 0, "sweeps": 0, "errors": {}, "started": False}
_first_sweep = threading.Event()

_DC = "{http://purl.org/dc/elements/1.1/}"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(s):
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", s or ""))).strip()


def _stamp(raw):
    """Epoch seconds from an RFC 822 or ISO 8601 stamp; 0 when unreadable."""
    raw = (raw or "").strip()
    if not raw:
        return 0
    try:
        return int(parsedate_to_datetime(raw).timestamp())
    except Exception:
        pass
    try:
        d = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return int(d.timestamp())
    except Exception:
        return 0


# The panel is an English wire. Google News answers a query with whatever
# language carried the story, so a headline whose letters are mostly outside
# Latin script is dropped, and a non-Latin publisher name falls back to the feed.
_NONLATIN = re.compile(r"[^\x00-\u024F\u2000-\u206F\u20A0-\u20CF]")


def _mostly_latin(s):
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if _NONLATIN.match(c)) <= 0.1 * len(letters)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _parse(body, source_id, home):
    root = ET.fromstring(body)
    out = []
    for it in root.iter():
        if _local(it.tag) not in ("item", "entry"):
            continue
        t = _child(it, "title")
        title = _text(t.text if t is not None else "")
        if not title:
            continue
        link_el = _child(it, "link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        ts = 0
        for nm in ("pubDate", "published", "updated", "date"):
            el = _child(it, nm)
            if el is not None and el.text:
                ts = _stamp(el.text)
                if ts:
                    break
        if not ts:
            continue                      # never stamp a story with the time it was seen
        if not _mostly_latin(title):
            continue
        src_el = _child(it, "source")
        publisher = _text(src_el.text) if src_el is not None and src_el.text else ""
        # Google News appends " - Publisher" to every headline.
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3].rstrip()
        if not publisher or not _mostly_latin(publisher):
            publisher = PUBLISHER.get(source_id, "Google News" if source_id.startswith("gn-") else source_id)
        out.append({"title": title, "url": link, "ts": ts,
                    "publisher": publisher, "home": home, "src": source_id})
    return out


def _fetch(feed):
    source_id, url, home = feed
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
            body = r.read()
        return source_id, _parse(body, source_id, home), None
    except Exception as e:
        return source_id, [], str(e)[:120]


def _key(it):
    t = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())
    return re.sub(r"\s+", " ", t)[:90]


def sweep():
    """Read every feed once and fold the results into the wire."""
    now = time.time()
    cutoff = now - KEEP_HOURS * 3600
    fresh, errors = [], {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sid, rows, err in ex.map(_fetch, FEEDS):
            if err:
                errors[sid] = err
            fresh.extend(rows)
    with _lock:
        for it in fresh:
            if it["ts"] < cutoff or it["ts"] > now + FUTURE_SLACK:
                continue
            k = _key(it)
            if not k:
                continue
            prev = _items.get(k)
            if prev:
                # the same story from a local desk and from a cross-market wire:
                # keep the local filing, it carries the home market
                if not prev.get("home") and it.get("home"):
                    prev["home"] = it["home"]
                continue
            it["id"] = hashlib.sha1(k.encode("utf-8")).hexdigest()[:12]
            it["seen"] = int(now)
            _items[k] = it
        # prune by AGE, never by what one sweep happened to fetch
        for k in [k for k, v in _items.items() if v["ts"] < cutoff]:
            del _items[k]
        if len(_items) > MAX_ITEMS:
            keep = sorted(_items.items(), key=lambda kv: -kv[1]["ts"])[:MAX_ITEMS]
            _items.clear()
            _items.update(keep)
        _state["updated"] = int(now)
        _state["sweeps"] += 1
        _state["errors"] = errors
    _first_sweep.set()


def _loop():
    while True:
        try:
            sweep()
        except Exception as e:
            _state["errors"] = {"sweep": str(e)[:120]}
            _first_sweep.set()
        time.sleep(POLL_SECONDS)


def ensure_started():
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
    threading.Thread(target=_loop, name="live-news", daemon=True).start()


def live(ex="", since=0, limit=250, wait=20):
    """The wire for one exchange: its own desks plus the cross-market wires.

    `since` returns only items first seen after that epoch, so a panel polling
    every minute downloads only what is new. The first call after a cold start
    waits up to `wait` seconds for the first sweep instead of answering empty.
    """
    ensure_started()
    if not _first_sweep.is_set():
        _first_sweep.wait(wait)
    ex = (ex or "").upper()
    if ex and ex not in EXCHANGES:
        return {"ok": False, "error": "unknown exchange"}
    try:
        since = int(since or 0)
    except Exception:
        since = 0
    try:
        limit = max(1, min(400, int(limit or 250)))
    except Exception:
        limit = 250
    with _lock:
        rows = [dict(v) for v in _items.values()
                if (not ex or v.get("home") in (None, ex)) and v["seen"] > since]
        updated, sweeps = _state["updated"], _state["sweeps"]
        n_err = len(_state["errors"])
    rows.sort(key=lambda r: -r["ts"])
    return {"ok": True, "exchange": ex or None, "updated": updated,
            "poll": POLL_SECONDS, "sweeps": sweeps, "feeds": len(FEEDS),
            "feeds_down": n_err, "warming": not _first_sweep.is_set(),
            "items": rows[:limit]}


if __name__ == "__main__":
    # one sweep, printed - for checking the feeds from a terminal
    sweep()
    out = live("NSE", wait=0)
    print(json.dumps({k: v for k, v in out.items() if k != "items"}, indent=1))
    print("errors:", json.dumps(_state["errors"], indent=1))
    for r in out["items"][:15]:
        print(time.strftime("%m-%d %H:%M", time.gmtime(r["ts"])), r["home"] or "GLB", r["publisher"][:18], "|", r["title"][:90])
