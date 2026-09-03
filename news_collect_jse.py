#!/usr/bin/env python3
"""news_collect_jse.py - build static_data/jse_news.json from Moneyweb's RSS
feeds (real, current South African market headlines - the JSE's home press).
Schema matches nse_news.json/ngx_news.json: [{id,title,publisher,date,url}].

EGX intentionally has no file here: no free, reachable headline feed exists
(Yahoo RSS is empty for .CA tickers; Google News RSS blocks; egx.com.eg is
WAF-gated). Honest empty beats fabricated headlines.
"""
import urllib.request, xml.etree.ElementTree as ET, hashlib, os, re, html, time, json

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
FEEDS = [
    "https://www.moneyweb.co.za/feed/",
    "https://www.moneyweb.co.za/category/markets/feed/",
]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_AGE_DAYS = 21
MAX_TOTAL = 40
MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
          "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _fresh(age_days):
    """True if the RFC822 pubDate is within MAX_AGE_DAYS of now."""
    try:
        t = time.strptime(age_days, "%a, %d %b %Y %H:%M:%S %z")
        import calendar
        ts = calendar.timegm(t)
        return (time.time() - ts) < MAX_AGE_DAYS * 86400
    except Exception:
        return False


def _fmt_date(pub):
    try:
        parts = pub.split()
        if len(parts) >= 4:
            return "%s %d" % (parts[2], int(parts[1]))   # "Sep 3"
    except Exception:
        pass
    return ""


def fetch_items(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read().decode("utf-8", "replace")
    out = []
    root = ET.fromstring(body)
    for item in root.iter("item"):
        t = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate") or ""
        if not t or not _fresh(pub):
            continue
        out.append({"title": html.unescape(t).strip(),
                    "url": link, "publisher": "Moneyweb", "date": _fmt_date(pub)})
    return out


def main():
    seen, rows = set(), []
    for url in FEEDS:
        try:
            items = fetch_items(url)
        except Exception as e:
            print("FAIL", url[:60], str(e)[:60])
            continue
        for it in items:
            key = it["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"id": int(hashlib.md5(it["url"].encode()).hexdigest()[:10], 16) % 10**9,
                         "title": it["title"], "publisher": it["publisher"],
                         "date": it["date"], "url": it["url"]})
        print(url[:60], "->", len(items), "fresh items")
    rows = rows[:MAX_TOTAL]
    json.dump(rows, open(os.path.join(SD, "jse_news.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("jse_news.json:", len(rows), "headlines")


if __name__ == "__main__":
    main()
