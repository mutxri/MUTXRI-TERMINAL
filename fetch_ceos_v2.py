#!/usr/bin/env python3
"""fetch_ceos_v2.py - slow, robust CEO fetcher (Wikidata P169 -> Wikipedia
key_people fallback). Writes static_data/ceos.json with ONLY clean single
CEO names. Resumes; 5s pace to respect rate limits. Run in background for
hours; quality over speed."""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "ceos.json")
STOCKS = os.path.join(BASE, "stocks.json")
UA = {"User-Agent": "Mozilla/5.0 (MUTXRI-TERMINAL research bot; contact j@mutxriterminal.com)"}

def api_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def wikidata_ceo(company):
    """CEO via Wikidata P169 (structured, reliable)."""
    try:
        s = ("https://www.wikidata.org/w/api.php?action=wbsearchentities&search=" +
             urllib.parse.quote(company) + "&language=en&format=json&limit=3")
        d = api_get(s)
        for hit in d.get("search", []):
            qid = hit.get("id")
            if not qid:
                continue
            c = ("https://www.wikidata.org/w/api.php?action=wbgetentities&ids=" +
                 qid + "&props=claims&format=json")
            d2 = api_get(c)
            claims = d2.get("entities", {}).get(qid, {}).get("claims", {})
            ceos = claims.get("P169", [])
            for cl in ceos[:1]:
                ms = cl.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(ms, dict) and ms.get("id"):
                    c2 = ("https://www.wikidata.org/w/api.php?action=wbgetentities&ids=" +
                          ms["id"] + "&props=labels&languages=en&format=json")
                    d3 = api_get(c2)
                    lab = d3.get("entities", {}).get(ms["id"], {}).get("labels", {}).get("en", {}).get("value")
                    if lab:
                        return lab
        return None
    except Exception:
        return None

def clean_ceo(raw):
    """Return a clean CEO name or None."""
    if not raw:
        return None
    v = raw.strip()
    if len(v) < 4 or len(v) > 50:
        return None
    if re.search(r"[|{}\[\]<>=\"']", v):
        return None
    if re.search(r"\d", v):
        return None
    if any(b in v.lower() for b in ["cite", "url=", "web ", "access", "dead link", "unbulleted", "ubl", "bulleted"]):
        return None
    words = v.split()
    if len(words) < 2:
        return None
    # must be letters/spaces/hyphens/apostrophes only (a real person name)
    if not re.match(r"^[A-Za-z][A-Za-z' .-]+$", v):
        return None
    return v

def wiki_ceo(page_title):
    """Wikipedia key_people fallback (strict)."""
    try:
        url = ("https://en.wikipedia.org/w/api.php?action=parse&page=" +
               urllib.parse.quote(page_title) + "&prop=wikitext&format=json&formatversion=2")
        d = api_get(url)
        wt = d.get("parse", {}).get("wikitext", "")
        if not wt:
            return None
        # capture multi-line key_people
        m = re.search(r"\|\s*key_people\s*=\s*((?:[^\n]|\n\*)[^\n]*){1,6}", wt, re.I)
        if not m:
            return None
        raw = m.group(1)
        # split people, find the CEO line
        for part in re.split(r"<br\s*/?>|\n\*", raw, flags=re.I):
            pl = part.lower()
            if "ceo" in pl or "chief executive" in pl:
                name = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", part)
                name = re.sub(r"\{\{[^{}]*\}\}", "", name)
                name = re.sub(r"<[^>]*>", "", name)
                name = re.sub(r"\([^)]*\)", "", name)
                name = re.sub(r",\s*(?:CEO|Chief Executive(?: Officer)?|Managing Director)\s*$", "", name, flags=re.I)
                name = re.sub(r"\s+", " ", name).strip(" |,;.")
                c = clean_ceo(name)
                if c:
                    return c
        return None
    except Exception:
        return None

def load_symbols():
    with open(STOCKS, encoding="utf-8") as f:
        stocks = json.load(f)["stocks"]
    syms = []
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        for s in stocks.get(ex, []):
            sym = s.get("sym") or s.get("ticker")
            nm = s.get("name")
            if sym and nm:
                up = nm.upper()
                if any(x in up for x in ["AMC", "ETF", " ETN", "PREFERENCE", "STRUCTURED", "NOTE"]):
                    continue
                if re.match(r"^EGS\d", sym):
                    continue
                syms.append((sym, nm))
    return syms

def wiki_search_ceo(query):
    """Search Wikipedia for the page, then extract CEO."""
    try:
        url = ("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=" +
               urllib.parse.quote(query) + "&srlimit=3&format=json&formatversion=2")
        d = api_get(url)
        for hit in d.get("query", {}).get("search", []):
            title = hit.get("title", "")
            if title:
                c = wiki_ceo(title)
                if c:
                    return c
        return None
    except Exception:
        return None

def main():
    existing = {}
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            existing = {}
    syms = load_symbols()
    print(f"targets: {len(syms)}, existing: {len(existing)}")
    done = fail = skip = 0
    for i, (sym, name) in enumerate(syms):
        if sym in existing:
            skip += 1
            continue
        found = None
        # Wikidata first (structured + reliable)
        base = re.sub(r"\s+(Ltd|Limited|Plc|PLC|Group|Holdings|S\.A\.E\.|Corp\.?|Inc\.?|ASA|S\.A\.)\s*$", "", name)
        found = wikidata_ceo(base)
        time.sleep(2.5)
        # Wikipedia fallback
        if not found:
            found = wiki_ceo(base)
            time.sleep(2.5)
        if not found:
            found = wiki_search_ceo(base)
            time.sleep(2.5)
        if found:
            existing[sym] = found
            done += 1
        else:
            fail += 1
        if (i + 1) % 5 == 0:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
            print(f"  {i+1}/{len(syms)} (done {done}, fail {fail}, skip {skip})", flush=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"DONE: {done} CEOs, {fail} not found, {skip} existing")

if __name__ == "__main__":
    main()
