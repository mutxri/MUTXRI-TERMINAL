#!/usr/bin/env python3
"""build_logos.py - build static_data/logos.json: ticker -> official domain.
Sources (in priority):
  1. JSE crawl: official issuer websites from clientportal.jse.co.za (246)
  2. company_domains.json curated map (172, covers EGX/NGX/NSE + JSE gaps)
The watchlist renders the domain via Google's favicon service with a
monogram fallback when no domain exists (honest - no broken images).
"""
import json, os, re
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))

def norm_domain(url):
    if not url:
        return None
    url = str(url).strip()
    if "://" not in url:
        url = "https://" + url
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return None
    return host or None

def main():
    stocks = json.load(open(os.path.join(BASE, "stocks.json"), encoding="utf-8"))["stocks"]
    jse_data = json.load(open(os.path.join(BASE, "jse_financials_data.json"), encoding="utf-8"))
    cd = json.load(open(os.path.join(BASE, "company_domains.json"), encoding="utf-8"))

    # 1. JSE official websites (code -> domain)
    jse_web = {t: norm_domain(v.get("website")) for t, v in jse_data.items() if v.get("website")}

    def jse_code_to_ticker(code):
        base = code
        for suf in ["NM", "E"]:
            if base.endswith(suf) and len(base) > 3:
                base = base[:-len(suf)]
        return base

    jse_map = {jse_code_to_ticker(c): d for c, d in jse_web.items() if d}

    # 2. company_domains: frag -> domain, applied by name
    def by_name(name):
        n = (name or "").lower()
        for frag, dom in cd.items():
            if frag.lower() in n:
                return dom
        return None

    # Build final map: for each stock, resolve ticker -> domain
    logo_map = {}
    for ex, lst in stocks.items():
        if not isinstance(lst, list):
            continue
        for s in lst:
            if not isinstance(s, dict):
                continue
            tkr = s.get("ticker") or s.get("sym") or s.get("code")
            if not tkr:
                continue
            # lookup key: strip .JO/.CA for JSE/EGX
            base = tkr.split(".")[0]
            dom = None
            if ex == "JSE":
                dom = jse_map.get(base) or jse_map.get(tkr) or by_name(s.get("name"))
            else:
                dom = by_name(s.get("name"))
            if dom:
                logo_map[tkr] = norm_domain(dom) or dom

    # save
    out = os.path.join(BASE, "static_data", "logos.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(logo_map, f, ensure_ascii=False, indent=1)

    # stats
    for ex, lst in stocks.items():
        if not isinstance(lst, list):
            continue
        n = sum(1 for s in lst if (s.get("ticker") or s.get("sym") or s.get("code")) in logo_map)
        print(f"{ex}: {n}/{len(lst)} with logo ({n/len(lst)*100:.0f}%)")
    print(f"\ntotal logos: {len(logo_map)} -> {out}")

if __name__ == "__main__":
    main()
