#!/usr/bin/env python3
"""expand_logos_wiki.py - expand static_data/logos.json by looking up the
official website for every stock missing a domain, via Wikipedia's API
(infobox website field). Skips tickers already resolved. Caches progress.

Usage: python expand_logos_wiki.py [start_index]
"""
import json, os, sys, re, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
LOGOS = os.path.join(BASE, "static_data", "logos.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"

def wiki_fetch(title):
    q = urllib.parse.quote(title)
    url = f"https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&format=json&titles={q}&redirects=1"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
    for pid, p in d.get("query", {}).get("pages", {}).items():
        if pid == "-1":
            return None
        revs = p.get("revisions", [])
        if revs:
            return revs[0].get("slots", {}).get("main", {}).get("*", "")
    return None

def wiki_search_website(name):
    """Search Wikipedia for the company, then extract website from the hit."""
    q = urllib.parse.quote(name + " company")
    url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&srlimit=1&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
    hits = d.get("query", {}).get("search", [])
    if not hits:
        return None
    title = hits[0]["title"]
    content = wiki_fetch(title)
    if not content:
        return None
    m = re.search(r"website\s*=\s*\{?\{?URL\s*\|\s*([^}\s|]+)", content, re.I)
    if not m:
        m = re.search(r"website\s*=\s*(https?://[^\s|}]+)", content, re.I)
    if not m:
        m = re.search(r"website\s*=\s*([a-z0-9][a-z0-9.-]+\.[a-z]{2,})", content, re.I)
    if m:
        v = m.group(1).strip().replace("https://", "").replace("http://", "").replace("www.", "")
        v = v.split("/")[0].lower()
        if "." in v:
            return v
    return None

def wiki_website(name):
    """Try direct title first, then search-based lookup."""
    if not name:
        return None
    # direct attempt with the full name
    for variant in [name, name.replace(" PLC", "").replace(" Plc", "").replace(" Ltd", "").replace(" Limited", "").replace(" Group", "")]:
        content = wiki_fetch(variant)
        if content:
            m = re.search(r"website\s*=\s*\{?\{?URL\s*\|\s*([^}\s|]+)", content, re.I)
            if not m:
                m = re.search(r"website\s*=\s*(https?://[^\s|}]+)", content, re.I)
            if not m:
                m = re.search(r"website\s*=\s*([a-z0-9][a-z0-9.-]+\.[a-z]{2,})", content, re.I)
            if m:
                v = m.group(1).strip().replace("https://", "").replace("http://", "").replace("www.", "")
                v = v.split("/")[0].lower()
                if "." in v:
                    return v
    # fallback: search
    return wiki_search_website(name)

def main():
    logos = json.load(open(LOGOS, encoding="utf-8"))
    stocks = json.load(open(os.path.join(BASE, "stocks.json"), encoding="utf-8"))["stocks"]

    # build list of (ticker, name) missing a domain
    missing = []
    for ex, lst in stocks.items():
        if not isinstance(lst, list):
            continue
        for s in lst:
            if not isinstance(s, dict):
                continue
            tkr = s.get("ticker") or s.get("sym") or s.get("code")
            if not tkr or tkr in logos:
                continue
            missing.append((tkr, s.get("name") or "", ex))

    print(f"missing domains: {len(missing)}")
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    found = 0
    for i in range(start, len(missing)):
        tkr, name, ex = missing[i]
        dom = wiki_website(name)
        if dom:
            logos[tkr] = dom
            found += 1
        if (i + 1) % 20 == 0:
            json.dump(logos, open(LOGOS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"  {i+1}/{len(missing)} (found {found} so far)")
        time.sleep(0.15)  # be polite to the API

    json.dump(logos, open(LOGOS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nDONE: found {found} new domains, total {len(logos)}")

if __name__ == "__main__":
    main()
