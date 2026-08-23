#!/usr/bin/env python3
"""build_site_map.py - bulk-build a company->website map for JSE+EGX+NGX+NSE.
Uses Wikipedia infoboxes in parallel (the method that WORKS), saves
site_map.json: {exchange: {sym: {name, website, ir, pdfs}}}.
Run: python build_site_map.py [--limit N]
"""
import json, os, sys, time, re, urllib.request, urllib.parse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
BASE = os.path.dirname(os.path.abspath(__file__))
STOCKS = os.path.join(BASE, "stocks.json")
OUT = os.path.join(BASE, "site_map.json")

def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")

def wiki_site(company):
    """Wikipedia infobox website with name-similarity guard.
    Tries ALL candidate articles; rejects template values."""
    try:
        q = urllib.parse.quote(re.sub(r"\b(Ltd|Limited|Plc|PLC|Holdings|Group|Incorporated|Inc|S\.A\.|Corporation|Corp)\b|\s+", "", company, flags=re.I)[:40])
        d = json.loads(http_get(f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&format=json&srlimit=3"))
        for hit in d.get("query", {}).get("search", []):
            title = hit["title"]
            t_norm = re.sub(r"[^a-z0-9]", "", title.lower())
            c_norm = re.sub(r"[^a-z0-9]", "", company.lower())
            if not (c_norm[:6] in t_norm or t_norm[:6] in c_norm):
                continue
            try:
                d2 = json.loads(http_get(f"https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&format=json&titles={urllib.parse.quote(title)}&rvsection=0"))
            except Exception:
                continue
            for pg in d2.get("query", {}).get("pages", {}).values():
                content = pg.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
                for pat in [r"website\s*=\s*([^\n|}]+)", r"\|\s*url\s*=\s*([^\n|}]+)"]:
                    m = re.search(pat, content)
                    if m:
                        site = m.group(1).strip().replace("{{URL|", "").replace("}}", "").strip()
                        # reject templates ([[...]]) and non-http values
                        if site.startswith("http") and "wikipedia" not in site and "jse.co.za" not in site:
                            return site
    except Exception:
        pass
    return None

def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    db = json.load(open(STOCKS, encoding="utf-8"))
    out = {}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            out = {}

    lock = threading.Lock()
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        stocks = db["stocks"].get(ex, [])
        if limit:
            stocks = stocks[:limit]
        todo = [s for s in stocks if f"{ex}:{s.get('sym') or s.get('ticker')}" not in out]
        print(f"[map] {ex}: {len(todo)} to look up")
        done = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {pool.submit(wiki_site, s.get("name") or ""): s for s in todo}
            for fut in as_completed(futs):
                s = futs[fut]
                key = f"{ex}:{s.get('sym') or s.get('ticker')}"
                try:
                    site = fut.result()
                except Exception:
                    site = None
                with lock:
                    out[key] = {"name": s.get("name"), "website": site}
                    done += 1
                    if done % 25 == 0:
                        json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
                        print(f"  [{done}/{len(todo)}] found so far: {sum(1 for v in out.values() if v.get('website'))}", flush=True)
        json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        found = sum(1 for k, v in out.items() if k.startswith(ex) and v.get("website"))
        print(f"[map] {ex}: {found} websites found")

    print(f"\nDONE: {sum(1 for v in out.values() if v.get('website'))} websites total -> {OUT}")

if __name__ == "__main__":
    main()
