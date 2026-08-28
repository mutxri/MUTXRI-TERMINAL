#!/usr/bin/env python3
"""fetch_ceos_web.py - extract CEO names from company websites for the
securities still missing a CEO (using the 467+ verified logo domains).

Approach per company: fetch the homepage + common leadership paths
(/about, /about-us, /leadership, /team, /management, /board-of-directors),
scan for "chief executive officer" / "ceo" / "group ceo" / "managing
director" patterns, take the name on/near the match. Strict cleaning:
only real person names (2+ words, letters/spaces/hyphens/apostrophes),
no "cite"/"url"/"|" junk. NEVER guesses - empty string if not found.

Writes into static_data/ceos.json (merges). ~3-5s per company.
"""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
CEOS = os.path.join(BASE, "static_data", "ceos.json")
LOGOS = os.path.join(BASE, "static_data", "logos.json")
STOCKS = os.path.join(BASE, "stocks.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}

CEO_PATTERNS = [
    (r"chief\s+executive\s+officer", "ceo"),
    (r"group\s+chief\s+executive", "ceo"),
    (r"chief\s+executive\s*[^a-z]{0,20}", "ceo"),
    (r"\bceo\b", "ceo"),
    (r"managing\s+director", "md"),
    (r"president\s*(?:&|and)?\s*(?:chief\s+executive)?", "pres"),
]

NAME_CLEAN = re.compile(r"^[A-Z][A-Za-z' .\-]{4,60}$")

def fetch_text(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(2_000_000).decode(errors="replace")
        # strip tags to text
        raw = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", "\n", raw)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&#?\w+;", " ", text)
        return text
    except Exception:
        return ""

def extract_ceo_from_text(text):
    """Find a CEO name in page text. Returns name or None."""
    lines = [l.strip() for l in text.split("\n")]
    for i, l in enumerate(lines):
        ll = l.lower()
        for pat, kind in CEO_PATTERNS:
            m = re.search(pat, ll)
            if m:
                # look at this line and the next 2 for a name
                for j in range(max(0, i - 1), min(len(lines), i + 3)):
                    cand = lines[j]
                    # skip if it's the pattern itself or too long
                    if re.search(pat, cand.lower()) or len(cand) > 70:
                        continue
                    # name may be "Name, Title" -> take the part before a comma
                    name_part = cand.split(",")[0].strip()
                    # strip leading bullets/dashes
                    name_part = re.sub(r"^[\s\-•*|]+", "", name_part)
                    if NAME_CLEAN.match(name_part) and len(name_part.split()) >= 2:
                        # reject obvious non-names
                        if any(w.lower() in name_part.lower() for w in
                               ["ceo", "chief", "executive", "director", "officer", "board",
                                "group", "chairman", "chair", "founder", "contact", "phone",
                                "email", "the", "and", "for", "with", "our", "management"]):
                            continue
                        return name_part
                break
    return None

def crawl_domain(domain, name):
    """Try homepage + leadership paths for a CEO name."""
    if not domain:
        return None
    base = "https://" + domain
    paths = ["", "/about", "/about-us", "/about/", "/leadership", "/team",
             "/management", "/board-of-directors", "/our-company", "/who-we-are",
             "/the-company", "/corporate", "/our-leadership", "/executive-team"]
    seen = set()
    for p in paths:
        url = base + p
        if url in seen:
            continue
        seen.add(url)
        text = fetch_text(url)
        if not text:
            continue
        ceo = extract_ceo_from_text(text)
        if ceo:
            return ceo
        time.sleep(0.3)
    # retry with www
    if not domain.startswith("www."):
        return crawl_domain("www." + domain, name)
    return None

def load_missing():
    ceos = {}
    if os.path.exists(CEOS):
        try:
            ceos = json.load(open(CEOS, encoding="utf-8"))
        except Exception:
            ceos = {}
    logos = json.load(open(LOGOS, encoding="utf-8"))
    stocks = json.load(open(STOCKS, encoding="utf-8"))["stocks"]
    out = []
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        for s in stocks.get(ex, []):
            sym = s.get("sym") or s.get("ticker")
            tkr = s.get("ticker")
            if not sym:
                continue
            if sym in ceos or (tkr and tkr in ceos):
                continue
            dom = logos.get(sym) or logos.get(tkr)
            if dom:
                out.append((sym, dom, s.get("name")))
    return ceos, out

def main():
    ceos, targets = load_missing()
    print(f"targets: {len(targets)} (missing CEO + verified domain), existing: {len(ceos)}")
    done = fail = 0
    for i, (sym, dom, nm) in enumerate(targets):
        try:
            ceo = crawl_domain(dom, nm)
        except Exception:
            ceo = None
        if ceo:
            ceos[sym] = ceo
            done += 1
        else:
            fail += 1
        if (i + 1) % 5 == 0:
            with open(CEOS, "w", encoding="utf-8") as f:
                json.dump(ceos, f, ensure_ascii=False, indent=1)
            print(f"  {i+1}/{len(targets)} (done {done}, fail {fail})", flush=True)
    with open(CEOS, "w", encoding="utf-8") as f:
        json.dump(ceos, f, ensure_ascii=False, indent=1)
    print(f"DONE: +{done} CEOs from websites, {fail} not found")

if __name__ == "__main__":
    main()
