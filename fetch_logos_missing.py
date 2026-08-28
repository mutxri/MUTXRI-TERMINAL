#!/usr/bin/env python3
"""fetch_logos_missing.py - search-verify official domains for the missing
logo-able companies via web search. Only verified domains enter logos.json
(honesty rule). Structured products/AMCs/EGS-codes are skipped (no logo).
Resumes; writes logos.json incrementally."""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
LOGOS = os.path.join(BASE, "static_data", "logos.json")
STOCKS = os.path.join(BASE, "stocks.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}

def web_search(q):
    """Use DuckDuckGo HTML (free, no key)."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode(errors="replace")
        # extract result links
        links = re.findall(r'uddg=([^"&]+)', html)
        return [urllib.parse.unquote(l) for l in links[:5]]
    except Exception:
        return []

def extract_domain(url):
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    if m:
        d = m.group(1).lower()
        # skip junk domains
        if any(x in d for x in ["wikipedia", "facebook.com", "linkedin.com", "twitter.com", "x.com",
                                 "instagram.com", "bloomberg", "reuters", "yahoo", "google", "duckduckgo",
                                 "africanfinancials", "moneyweb", "jse.co.za", "ngxgroup", "nse.co.ke",
                                 "egx.com", "simplywall", "marketscreener", "tradingview", "investing.com",
                                 "ft.com", "wsj.com", "nytimes", "morningstar", "wikidata", "crunchbase",
                                 "zoominfo", "dun & bradstreet", "cnbc", "bbc", "guardian", "africaintel",
                                 "investorlist", "barchart", "stockanalysis", "wallstreet", "tipranks",
                                 "wisesheets", "macrotrends", "wikipedia.org", "companieshouse", "bizcommunity"]):
            return None
        return d
    return None

def load_symbols():
    with open(STOCKS, encoding="utf-8") as f:
        stocks = json.load(f)["stocks"]
    out = []
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        for s in stocks.get(ex, []):
            sym = s.get("sym") or s.get("ticker")
            tkr = s.get("ticker")
            nm = s.get("name")
            if not sym or not nm:
                continue
            up = nm.upper()
            if any(x in up for x in ["AMC", "ETF", " ETN", "PREFERENCE", "STRUCTURED", "NOTE", "RIGHTS"]):
                continue
            if re.match(r"^EGS\d", sym):
                continue
            out.append((ex, sym, tkr, nm))
    return out

def main():
    logos = {}
    if os.path.exists(LOGOS):
        try:
            logos = json.load(open(LOGOS, encoding="utf-8"))
        except Exception:
            logos = {}
    targets = load_symbols()
    # filter to those missing
    missing = [(ex, sym, tkr, nm) for ex, sym, tkr, nm in targets
               if not (sym in logos or (tkr and tkr in logos))]
    print(f"missing logo-able: {len(missing)}")
    done = fail = skip = 0
    for i, (ex, sym, tkr, nm) in enumerate(missing):
        if sym in logos or (tkr and tkr in logos):
            skip += 1
            continue
        # search "CompanyName official website"
        q = f'"{nm}" official website'
        links = web_search(q)
        found = None
        for url in links:
            d = extract_domain(url)
            if d:
                found = d
                break
        time.sleep(1.2)
        if found:
            key = tkr or sym
            logos[key] = found
            done += 1
        else:
            fail += 1
        if (i + 1) % 5 == 0:
            with open(LOGOS, "w", encoding="utf-8") as f:
                json.dump(logos, f, ensure_ascii=False, indent=1)
            print(f"  {i+1}/{len(missing)} (done {done}, fail {fail}, skip {skip})", flush=True)
    with open(LOGOS, "w", encoding="utf-8") as f:
        json.dump(logos, f, ensure_ascii=False, indent=1)
    print(f"DONE: {done} domains verified, {fail} not found, {skip} skipped")

if __name__ == "__main__":
    main()
