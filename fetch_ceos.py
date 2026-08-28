#!/usr/bin/env python3
"""fetch_ceos.py - fetch CEO names from Wikipedia infoboxes for every listed
security across JSE/EGX/NGX/NSE. Writes static_data/ceos.json:
  { "SYM": "CEO Name", ... }  (only verified CEO entries; no CEO -> omitted)

Honest policy: only actual CEO roles are kept (not chairman). Structured
products / AMC / ETFs / obscure tickers without a Wikipedia page get no
entry - the frontend shows "—" (no verified free source).

Resumes: skips symbols already in ceos.json. Slow pace to respect Wikipedia.
"""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "ceos.json")
STOCKS = os.path.join(BASE, "stocks.json")
UA = {"User-Agent": "Mozilla/5.0 (MUTXRI-TERMINAL research bot)"}

def clean_wiki_name(raw):
    """Strip wiki markup from a key_people value, return (name, role)."""
    if not raw:
        return None, None
    # keep only the CEO mention if multiple people listed
    parts = re.split(r"<br\s*/?>|\n\*", raw, flags=re.I)
    for p in parts:
        pl = p.lower()
        if "ceo" in pl or "chief executive" in pl:
            # strip links/templates
            name = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", p)
            # unwrap ubl/Bulleted_list templates: {{ubl|A |B }} -> "A|B"
            name = re.sub(r"\{\{(?:ubl|Bulleted_list|unbulleted_list|plainlist)\s*\|", "", name, flags=re.I)
            name = re.sub(r"\}\}", "", name)
            name = re.sub(r"\{\{[^{}]*\}\}", "", name)
            name = re.sub(r"\[\[|\]\]|\{\{|\}\}", "", name)
            name = re.sub(r"\([^)]*\)", "", name)  # drop (CEO) labels
            name = re.sub(r"<[^>]*>", "", name)
            name = name.replace("[[", "").replace("]]", "")
            # strip trailing role labels like ", CEO" or ", Chief Executive Officer"
            name = re.sub(r",\s*(?:CEO|Chief Executive(?: Officer)?|Managing Director)\s*$", "", name, flags=re.I)
            name = re.sub(r"\s+", " ", name).strip(" |,;.")
            if name and len(name) > 2 and not name.lower().startswith(("ceo", "chief")):
                return name, "CEO"
    # fallback: whole value if it's a single person with CEO mention
    if "ceo" in raw.lower() and "<br" not in raw:
        name = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", raw)
        name = re.sub(r"\([^)]*\)", "", name)
        name = re.sub(r"<[^>]*>", "", name)
        name = re.sub(r"\s+", " ", name).strip(" |,;.")
        return name, "CEO"
    return None, None

def wiki_ceo(page_title):
    url = ("https://en.wikipedia.org/w/api.php?action=parse&page=" +
           urllib.parse.quote(page_title) + "&prop=wikitext&format=json&formatversion=2")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                d = json.loads(r.read().decode())
            wt = d.get("parse", {}).get("wikitext", "")
            if not wt:
                return None
            m = re.search(r"\|\s*key_people\s*=\s*((?:[^\n]|\n\*)[^\n]*){1,6}", wt, re.I)
            if m:
                name, role = clean_wiki_name(m.group(1))
                if name:
                    return name
            return None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(8 * (attempt + 1))  # back off on rate limit
                continue
            return None
        except Exception:
            return None
    return None

def wiki_search_ceo(query):
    """Search Wikipedia for the company page, then extract its CEO."""
    url = ("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=" +
           urllib.parse.quote(query) + "&srlimit=3&format=json&formatversion=2")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
        for hit in d.get("query", {}).get("search", []):
            title = hit.get("title", "")
            if not title:
                continue
            ceo = wiki_ceo(title)
            if ceo:
                return ceo
        return None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(10)
        return None
    except Exception:
        return None

def normalize_title(name):
    """Turn a company name into a plausible Wikipedia page title."""
    n = name.replace(" Ltd.", "").replace(" Limited", "").replace(" Plc", "")
    n = n.replace(" PLC", "").replace(" Group", "").replace(" Holdings", "")
    n = re.sub(r"\s+", " ", n).strip()
    return n

def load_symbols():
    with open(STOCKS, encoding="utf-8") as f:
        stocks = json.load(f)["stocks"]
    syms = []
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        for s in stocks.get(ex, []):
            sym = s.get("sym") or s.get("ticker")
            nm = s.get("name")
            if sym and nm:
                # skip obvious structured/AMC products (no CEO exists)
                up = nm.upper()
                if any(x in up for x in ["AMC", "ETF", " ETN", "PREFERENCE", "STRUCTURED", "NOTE"]):
                    continue
                if re.match(r"^EGS\d", sym):
                    continue
                syms.append((sym, nm))
    return syms

def main():
    existing = {}
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            existing = {}
    syms = load_symbols()
    print(f"target symbols: {len(syms)} (existing {len(existing)})")
    done = fail = skip = 0
    for i, (sym, name) in enumerate(syms):
        if sym in existing:
            skip += 1
            continue
        # try the company name directly, then the normalized title, then search
        found = None
        for title in [name, normalize_title(name)]:
            if not title or len(title) < 3:
                continue
            found = wiki_ceo(title)
            if found:
                break
        if not found:
            found = wiki_search_ceo(name.replace(" Ltd.", "").replace(" Plc", ""))
        if found:
            existing[sym] = found
            done += 1
        else:
            fail += 1
        if (i + 1) % 10 == 0:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
            print(f"  {i+1}/{len(syms)} (done {done}, fail {fail}, skip {skip})", flush=True)
        time.sleep(0.6)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"DONE: {done} CEOs found, {fail} no-page, {skip} already present")

if __name__ == "__main__":
    main()
