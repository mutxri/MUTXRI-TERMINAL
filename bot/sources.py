#!/usr/bin/env python3
"""bot/sources.py - where the bot reads the world.

Three tiers, each a list of adapters returning a common item shape:
    {title, summary, url, publisher, source_id, tier, ts, lang}

  local   home-market press for each exchange (what actually moves the local tape)
  global  macro/markets wires whose stories transmit into frontier markets
  social  X/Twitter, only when an API token is configured

Every feed here was reachability-checked before being added. Feeds that block,
404 or WAF-gate are left out rather than shipped broken - and a tier that
returns nothing reports nothing, it never invents filler.
"""
import calendar, concurrent.futures as cf, hashlib, html, json, os, re, time
import urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 25
MAX_AGE_DAYS = 7

ATOM = "{http://www.w3.org/2005/Atom}"


def _gnews(query, days=7):
    """Google News search RSS - the only reliable way to reach Egyptian and
    Kenyan exchange coverage, and useful for targeted macro topics."""
    q = urllib.parse.quote("%s when:%dd" % (query, days))
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % q


# ---------------------------------------------------------------- feed tables
# weight: how much a story from this source counts toward a signal's confidence.
LOCAL_FEEDS = {
    "NSE": [
        ("gnews-nse", _gnews('"Nairobi Securities Exchange" OR "NSE Kenya" OR "Kenyan shilling"'), 0.9),
        ("gnews-ke-macro", _gnews('Kenya economy OR "Central Bank of Kenya" OR Treasury bond'), 0.75),
    ],
    "NGX": [
        ("nairametrics", "https://nairametrics.com/feed/", 0.95),
        ("businessday-ng", "https://businessday.ng/feed/", 0.9),
        ("gnews-ngx", _gnews('"Nigerian Exchange" OR "NGX All-Share" OR naira'), 0.85),
    ],
    "JSE": [
        ("moneyweb", "https://www.moneyweb.co.za/feed/", 0.95),
        ("moneyweb-markets", "https://www.moneyweb.co.za/category/markets/feed/", 0.95),
        ("miningmx", "https://www.miningmx.com/feed/", 0.85),
        ("gnews-jse", _gnews('"Johannesburg Stock Exchange" OR "JSE All Share" OR rand'), 0.85),
    ],
    "EGX": [
        ("dailynewsegypt", "https://www.dailynewsegypt.com/feed/", 0.9),
        ("egyptindependent", "https://egyptindependent.com/feed/", 0.7),
        ("gnews-egx", _gnews('"EGX 30" OR "Egyptian Exchange" OR "Egyptian pound"'), 0.9),
    ],
}

GLOBAL_FEEDS = [
    ("cnbc-world", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362", 0.9),
    ("cnbc-markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", 0.9),
    ("yahoo-finance", "https://finance.yahoo.com/news/rssindex", 0.8),
    ("bbc-business", "https://feeds.bbci.co.uk/news/business/rss.xml", 0.85),
    ("aljazeera", "https://www.aljazeera.com/xml/rss/all.xml", 0.7),
    ("ft-world", "https://www.ft.com/world?format=rss", 0.9),
    ("marketwatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", 0.85),
    ("investing-com", "https://www.investing.com/rss/news_25.rss", 0.75),
    ("oilprice", "https://oilprice.com/rss/main", 0.8),
    ("theafricareport", "https://www.theafricareport.com/feed/", 0.75),
]

# Macro themes that transmit into frontier/African markets.
GLOBAL_QUERIES = [
    ("gnews-fed", _gnews("Federal Reserve interest rate decision OR FOMC", 3), 0.85),
    ("gnews-em", _gnews("emerging markets capital flows OR frontier markets", 5), 0.75),
    ("gnews-imf-africa", _gnews("IMF Africa loan OR debt restructuring", 7), 0.8),
    ("gnews-commodities", _gnews("oil price OR gold price OR OPEC output", 3), 0.8),
]


# ------------------------------------------------------------------ utilities
def _parse_date(s):
    """Return epoch seconds from the date formats these feeds actually emit."""
    s = (s or "").strip()
    if not s:
        return None
    fmts = ["%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
            "%a, %d %b %Y %H:%M %z"]
    for f in fmts:
        try:
            t = time.strptime(re.sub(r"\s+", " ", s), f)
        except Exception:
            continue
        base = calendar.timegm(t)
        return base - t.tm_gmtoff if t.tm_gmtoff else base
    return None


def _clean(s):
    """Strip tags/entities from feed text."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _iid(url, title):
    return hashlib.md5((url or title or "").encode("utf-8")).hexdigest()[:16]


def fetch_rss(source_id, url, weight, tier, exchange=None):
    """Fetch and normalise one RSS/Atom feed. Raises on transport failure."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read()
    root = ET.fromstring(body)
    nodes = list(root.iter("item")) or list(root.iter(ATOM + "entry"))
    out, now = [], time.time()
    for n in nodes:
        title = _clean(n.findtext("title") or n.findtext(ATOM + "title") or "")
        if not title:
            continue
        link = (n.findtext("link") or "").strip()
        if not link:
            le = n.find(ATOM + "link")
            link = le.get("href", "") if le is not None else ""
        summary = _clean(n.findtext("description") or n.findtext(ATOM + "summary") or "")[:400]
        pub = (n.findtext("pubDate") or n.findtext("published")
               or n.findtext(ATOM + "published") or n.findtext(ATOM + "updated") or "")
        ts = _parse_date(pub)
        if ts and (now - ts) > MAX_AGE_DAYS * 86400:
            continue
        # Google News titles carry a " - Publisher" tail; lift it into publisher.
        publisher = source_id
        m = re.match(r"^(.*)\s+-\s+([^-]{2,40})$", title)
        if source_id.startswith("gnews") and m:
            title, publisher = m.group(1).strip(), m.group(2).strip()
        out.append({
            "id": _iid(link, title), "title": title, "summary": summary,
            "url": link, "publisher": publisher, "source_id": source_id,
            "weight": weight, "tier": tier, "exchange": exchange,
            "ts": ts or now, "lang": "en",
        })
    return out


# -------------------------------------------------------------- X/Twitter tier
X_ACCOUNTS = [
    "NSEKenya", "ngxgroup", "JSE_Group", "TheEGX", "CBKKenya", "cenbank",
    "SAReserveBank", "ReutersAfrica", "TheAfricaReport", "nairametrics",
    "Moneyweb", "BD_Africa",
]
X_TERMS = ['"Nairobi Securities Exchange"', '"Nigerian Exchange"',
           '"Johannesburg Stock Exchange"', '"EGX 30"']


def fetch_x(max_results=60):
    """X/Twitter recent search via API v2.

    Requires X_BEARER_TOKEN (a paid X API tier - there is no free search
    endpoint, and the public Nitter mirrors are gone). Without a token this
    returns an explicit 'disabled' status rather than a silent empty list, so
    the terminal can say the social tier is off instead of implying it is quiet.
    """
    tok = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not tok:
        return [], {"status": "disabled", "reason": "X_BEARER_TOKEN not set"}
    frm = " OR ".join("from:" + a for a in X_ACCOUNTS)
    query = "(%s OR %s) -is:retweet lang:en" % (frm, " OR ".join(X_TERMS))
    url = ("https://api.twitter.com/2/tweets/search/recent?"
           + urllib.parse.urlencode({
               "query": query, "max_results": min(max(max_results, 10), 100),
               "tweet.fields": "created_at,public_metrics,author_id",
               "expansions": "author_id", "user.fields": "username,verified",
           }))
    req = urllib.request.Request(url, headers=dict(UA, Authorization="Bearer " + tok))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return [], {"status": "error", "reason": "HTTP %d" % e.code}
    except Exception as e:
        return [], {"status": "error", "reason": type(e).__name__}
    users = {u["id"]: u.get("username", "") for u in data.get("includes", {}).get("users", [])}
    out = []
    for t in data.get("data", []):
        handle = users.get(t.get("author_id", ""), "x")
        m = t.get("public_metrics", {}) or {}
        # Engagement nudges weight: a widely-shared post is more likely to matter.
        eng = m.get("retweet_count", 0) + m.get("like_count", 0)
        out.append({
            "id": "x" + str(t.get("id")), "title": _clean(t.get("text", ""))[:300],
            "summary": "", "url": "https://x.com/%s/status/%s" % (handle, t.get("id")),
            "publisher": "@" + handle, "source_id": "x-search",
            "weight": min(0.85, 0.5 + min(eng, 2000) / 4000.0),
            "tier": "social", "exchange": None,
            "ts": _parse_date(t.get("created_at")) or time.time(), "lang": "en",
        })
    return out, {"status": "ok", "count": len(out)}


# ------------------------------------------------------------------ collector
def collect(tiers=("local", "global", "social"), workers=10, verbose=True):
    """Fetch every configured source in parallel.

    Returns (items, report). The report records per-source outcomes so a failing
    feed is visible in the output instead of silently shrinking coverage.
    """
    jobs, report, items = [], {"sources": [], "errors": []}, []
    if "local" in tiers:
        for ex, feeds in LOCAL_FEEDS.items():
            for sid, url, w in feeds:
                jobs.append((sid, url, w, "local", ex))
    if "global" in tiers:
        for sid, url, w in GLOBAL_FEEDS + GLOBAL_QUERIES:
            jobs.append((sid, url, w, "global", None))

    def _run(j):
        # One retry: these feeds time out intermittently under load, and losing
        # a whole market's local press to a transient blip is worse than the wait.
        sid, url, w, tier, ex = j
        last = None
        for attempt in range(2):
            try:
                return j, fetch_rss(sid, url, w, tier, ex), None
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, str(e)[:70])
                if attempt == 0:
                    time.sleep(1.5)
        return j, [], last

    with cf.ThreadPoolExecutor(workers) as pool:
        for j, got, err in pool.map(_run, jobs):
            sid, _u, _w, tier, ex = j
            if err:
                report["errors"].append({"source": sid, "tier": tier, "error": err})
                if verbose:
                    print("  FAIL %-22s %s" % (sid, err))
            else:
                items.extend(got)
                report["sources"].append({"source": sid, "tier": tier,
                                          "exchange": ex, "items": len(got)})
                if verbose:
                    print("  ok   %-22s %3d items" % (sid, len(got)))

    if "social" in tiers:
        xs, xrep = fetch_x()
        report["social"] = xrep
        items.extend(xs)
        if verbose:
            print("  x/twitter: %s (%s)" % (xrep.get("status"),
                                            xrep.get("reason", xrep.get("count", ""))))

    # De-duplicate: same URL, or same headline from a syndicating partner.
    seen_url, seen_title, uniq = set(), set(), []
    for it in sorted(items, key=lambda x: (-x["weight"], -x["ts"])):
        u = (it["url"] or "").split("?")[0]
        t = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())[:90]
        if (u and u in seen_url) or (t and t in seen_title):
            continue
        seen_url.add(u)
        seen_title.add(t)
        uniq.append(it)
    report["total_fetched"] = len(items)
    report["total_unique"] = len(uniq)
    return uniq, report


if __name__ == "__main__":
    its, rep = collect()
    print("\n%d unique of %d fetched; %d source errors"
          % (rep["total_unique"], rep["total_fetched"], len(rep["errors"])))
    for i in its[:6]:
        print("  [%-6s] %-18s %s" % (i["tier"], i["publisher"][:18], i["title"][:70]))
