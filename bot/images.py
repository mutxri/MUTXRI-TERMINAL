#!/usr/bin/env python3
"""bot/images.py - finding real, licensed pictures of real companies and people.

No image is ever generated. Everything here is a real photograph or a real logo,
fetched from a source that states who made it and on what terms, and every asset
carries that provenance with it so the card builder can print an attribution line
and the publisher can refuse anything it is not allowed to republish.

Two problems this module exists to solve, both of which bite hard:

  IDENTITY   A full-text image search for a person's name matches the *description*
             of a photo, not the person in it. Searching Commons for "Peter Ndegwa"
             returns a Nigerian civil-society photo with his name nowhere in it.
             So people are never resolved by image search. Instead: find the
             person's Wikipedia article, confirm the article is about a person and
             that it corroborates the company, and take that article's lead image.
             The picture on a person's own article is that person.

  LICENSING  Republishing a press photo under a brand's account is a copyright act.
             Wikimedia returns machine-readable licence metadata, so each asset is
             graded: CC0/public-domain and CC BY(-SA) are publishable (the last
             with attribution); anything whose terms we cannot read is marked
             `unknown` and is blocked from a published card unless a human passes
             allow_unlicensed explicitly.

When no licensed photograph of someone exists - which is common for African
executives, including Safaricom's own CEO - this module returns nothing and says
why. The card builder then falls back to a typographic initials tile. It never
substitutes a different person's face, and never invents one.
"""
import hashlib, json, os, re, time
import urllib.error, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(BASE, "static_data")
CACHE_DIR = os.path.join(SD, "media_cache")
INDEX_FILE = os.path.join(CACHE_DIR, "index.json")

# Wikimedia asks for a descriptive UA with contact details; anonymous scrapers
# get rate-limited or blocked.
UA = {"User-Agent": "MUTXRI-Terminal/1.0 (https://mutxriterminal.com; jimmy@mutxri.com)"}
TIMEOUT = 25

# Licence strings Wikimedia returns that permit republication. The two tiers
# differ only in whether a credit line is required - both are safe to publish.
LICENCE_FREE = {"cc0", "public domain", "pd", "no restrictions", "cc pd mark 1.0"}
LICENCE_ATTRIB_PREFIXES = ("cc by",)


def _get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def grade_licence(name):
    """Classify a licence string into a republication verdict."""
    n = (name or "").strip().lower()
    if not n:
        return "unknown"
    if any(k in n for k in LICENCE_FREE):
        return "permitted"
    if n.startswith(LICENCE_ATTRIB_PREFIXES):
        return "attribution"
    if "fair use" in n or "non-free" in n:
        return "blocked"
    return "unknown"


def _asset(kind, url, **kw):
    a = {"kind": kind, "url": url, "source": kw.get("source"),
         "sourcePage": kw.get("sourcePage"),
         "title": kw.get("title"), "licence": kw.get("licence"),
         "author": kw.get("author"), "width": kw.get("width"),
         "height": kw.get("height"), "confidence": kw.get("confidence", 0.0),
         "subject": kw.get("subject"), "notes": kw.get("notes")}
    a["reuse"] = grade_licence(a["licence"])
    a["attribution"] = _attribution_line(a)
    return a


def _attribution_line(a):
    if a["reuse"] == "permitted":
        return "%s (%s)" % (a.get("author") or a.get("source") or "source",
                            a.get("licence") or "public domain")
    if a["reuse"] == "attribution":
        return "%s / %s" % (a.get("author") or "unknown author",
                            a.get("licence") or "CC BY")
    return None


# ------------------------------------------------------------------- Commons
def commons_search(query, limit=6, min_width=200):
    """Search Wikimedia Commons files, returning assets with licence metadata."""
    url = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search"
           "&gsrsearch=" + urllib.parse.quote(query) +
           "&gsrlimit=%d&gsrnamespace=6&prop=imageinfo"
           "&iiprop=url|extmetadata|size|mime&iiurlwidth=900&format=json" % limit)
    try:
        d = _get_json(url)
    except Exception:
        return []
    out = []
    for p in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {}) or {}
        src = ii.get("thumburl") or ii.get("url")
        if not src:
            continue
        w = ii.get("width") or 0
        if w and w < min_width:
            continue
        out.append(_asset(
            "image", src,
            source="Wikimedia Commons",
            sourcePage=ii.get("descriptionurl"),
            title=p.get("title"),
            licence=(em.get("LicenseShortName", {}) or {}).get("value"),
            author=_strip_html((em.get("Artist", {}) or {}).get("value"))[:120],
            width=w, height=ii.get("height")))
    return out


# ------------------------------------------------------------------- people
def _wiki_pages(titles):
    url = ("https://en.wikipedia.org/w/api.php?action=query&titles="
           + urllib.parse.quote("|".join(titles)) +
           "&prop=pageimages|categories|extracts&piprop=original"
           "&exintro=1&explaintext=1&cllimit=100&format=json&redirects=1")
    try:
        return list((_get_json(url).get("query", {}).get("pages", {}) or {}).values())
    except Exception:
        return []


def _name_similarity(query, title):
    """Loose personal-name match: surname must agree, given name may be shortened.

    "Sim Tshabalala" should match the article "Simpiwe Tshabalala"; "Peter Ndegwa"
    should not match "Peter Kenneth".
    """
    qt = re.sub(r"\([^)]*\)", "", title).strip()
    qw = [w for w in re.findall(r"[A-Za-z'-]+", query.lower()) if len(w) > 1]
    tw = [w for w in re.findall(r"[A-Za-z'-]+", qt.lower()) if len(w) > 1]
    if not qw or not tw:
        return 0.0
    if qw[-1] != tw[-1]:                      # surnames must match
        return 0.0
    score = 0.6
    a, b = qw[0], tw[0]
    if a == b:
        score += 0.4
    elif a.startswith(b[:3]) or b.startswith(a[:3]):
        score += 0.25                          # Sim / Simpiwe
    return min(score, 1.0)


def find_person(name, company=None, min_confidence=0.6):
    """Find a licensed photograph of a named person.

    Returns (asset, report). `asset` is None whenever we cannot bind a picture to
    this specific person with confidence - which is the common case, and the
    correct answer. The report always explains why.
    """
    report = {"query": name, "company": company, "candidates": [], "reason": None}
    if not name or len(name.split()) < 2:
        report["reason"] = "need a full name to identify a person"
        return None, report

    surl = ("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch="
            + urllib.parse.quote(name) + "&srlimit=5&format=json")
    try:
        hits = _get_json(surl).get("query", {}).get("search", [])
    except Exception as e:
        report["reason"] = "wikipedia search failed (%s)" % type(e).__name__
        return None, report
    if not hits:
        report["reason"] = "no Wikipedia article matches that name"
        return None, report

    pages = _wiki_pages([h["title"] for h in hits[:5]])
    best, best_conf = None, 0.0
    for p in pages:
        title = p.get("title", "")
        cats = [c.get("title", "") for c in p.get("categories", []) or []]
        is_person = any("Living people" in c or re.search(r"\b\d{4} births\b", c)
                        for c in cats)
        extract = p.get("extract") or ""
        img = (p.get("original") or {}).get("source")
        name_score = _name_similarity(name, title)
        corroborated = bool(company) and company.split()[0].lower() in extract.lower()

        cand = {"title": title, "isPerson": is_person, "nameScore": round(name_score, 2),
                "companyCorroborated": corroborated, "hasImage": bool(img)}
        report["candidates"].append(cand)

        if not is_person or name_score < 0.6:
            continue
        conf = name_score * (1.0 if corroborated else 0.8)
        if not img:
            cand["note"] = "article exists but carries no image"
            continue
        if conf > best_conf:
            best_conf, best = conf, (p, title, img, corroborated)

    if not best:
        anyone = any(c["isPerson"] and c["nameScore"] >= 0.6 for c in report["candidates"])
        report["reason"] = ("a matching article exists but has no photograph"
                            if anyone else
                            "no Wikipedia article confidently identifies this person")
        return None, report
    if best_conf < min_confidence:
        report["reason"] = "identity confidence %.2f below threshold" % best_conf
        return None, report

    p, title, img, corroborated = best
    # The article's lead image lives on Commons; fetch its licence by filename.
    lic = _commons_file_meta(img)

    # A lead image is not always a portrait. Aliko Dangote's article leads with
    # "Al Shabani at the acquisition of Dangote Cement" - an event photograph that
    # may show several people. When the filename does not name the subject, the
    # picture is still probably relevant but is no longer a confident portrait,
    # so the confidence drops and the card carries a verify-before-publishing note.
    # Both names must appear, not just the surname: "Al Shabani at the acquisition
    # of Dangote Cement" contains "Dangote" because that is the *company*, and a
    # surname-only test would wave that through as a portrait of Aliko Dangote.
    parts = re.findall(r"[A-Za-z'-]+", name)
    given, surname = parts[0].lower(), parts[-1].lower()
    fname = urllib.parse.unquote(os.path.basename(
        urllib.parse.urlparse(img).path)).lower()
    named_in_file = surname in fname and given in fname
    portrait_note = None
    if not named_in_file:
        best_conf *= 0.65
        portrait_note = ("the image filename does not name the subject - it may be "
                         "a group or event photograph; check it shows the right "
                         "person before publishing")

    asset = _asset("person", img,
                   source="Wikipedia / Wikimedia Commons",
                   sourcePage="https://en.wikipedia.org/wiki/" + urllib.parse.quote(title),
                   title=title,
                   licence=lic.get("licence"), author=lic.get("author"),
                   width=lic.get("width"), height=lic.get("height"),
                   confidence=round(best_conf, 2), subject=name,
                   notes="; ".join(filter(None, [
                       "lead image of the Wikipedia article %r" % title,
                       "company corroborated in the article intro" if corroborated else None,
                       portrait_note])))
    asset["needsVisualCheck"] = not named_in_file
    report["reason"] = "matched article %r" % title
    return asset, report


def _commons_file_meta(file_url):
    """Licence metadata for a Commons file, looked up from its upload URL."""
    fname = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(file_url).path))
    fname = fname.split("?")[0]
    url = ("https://commons.wikimedia.org/w/api.php?action=query&titles="
           + urllib.parse.quote("File:" + fname) +
           "&prop=imageinfo&iiprop=extmetadata|size|url&format=json")
    try:
        pages = (_get_json(url).get("query", {}).get("pages", {}) or {}).values()
    except Exception:
        return {}
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {}) or {}
        return {"licence": (em.get("LicenseShortName", {}) or {}).get("value"),
                "author": _strip_html((em.get("Artist", {}) or {}).get("value"))[:120],
                "width": ii.get("width"), "height": ii.get("height")}
    return {}


# -------------------------------------------------------------------- logos
def _logo_domain(ticker):
    p = os.path.join(SD, "logos.json")
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p, encoding="utf-8")).get(ticker)
    except Exception:
        return None


# Words in a Commons filename that describe the file rather than the owner.
_FILE_NOISE = {
    "file", "logo", "logos", "wordmark", "icon", "symbol", "emblem", "brand",
    "vector", "svg", "png", "jpg", "jpeg", "gif", "webp", "seeklogo", "new",
    "old", "current", "official", "transparent", "black", "white", "colour",
    "color", "horizontal", "vertical", "square", "full", "text", "type", "crop",
    "cropped", "small", "large", "en", "the", "and", "of", "plc", "ltd",
    "limited", "group", "holdings", "company", "inc", "sae", "nv", "co",
}


def _title_matches_company(file_title, company_name):
    """True when every meaningful word in a file title belongs to the company.

    A Commons search for a short brand hits other organisations that share it.
    Requiring the filename to introduce no significant word of its own is a
    cheap, strict test that separates "ABSA Group Limited Logo.svg" (all words
    accounted for) from "NCBA CLUSA logo" (CLUSA is a different body).
    """
    co_words = {w for w in re.findall(r"[a-z0-9]+", (company_name or "").lower())}
    for w in re.findall(r"[a-z0-9]+", (file_title or "").lower()):
        if w in _FILE_NOISE or w.isdigit() or len(w) <= 2:
            continue
        if w in co_words:
            continue
        # Allow a longer form of a company word, e.g. "safaricomplc".
        if any(w.startswith(c) or c.startswith(w) for c in co_words if len(c) > 3):
            continue
        return False
    return True


def find_logo(company_name, ticker=None, allow_favicon=True):
    """Find a company logo, preferring a licensed Commons file over a favicon."""
    report = {"query": company_name, "ticker": ticker, "tried": []}
    stem = re.sub(r"\b(plc|limited|ltd|group|holdings|company|inc|sae)\b", "",
                  company_name or "", flags=re.I).strip()

    for q in ('%s logo' % stem, '%s logo' % (company_name or "")):
        if not stem:
            break
        report["tried"].append("commons:" + q)
        for a in commons_search(q, limit=6, min_width=120):
            title = (a.get("title") or "").lower()
            if "logo" not in title:
                continue
            first = stem.split()[0].lower() if stem.split() else ""
            if first and first not in title:
                continue
            if not _title_matches_company(title, company_name):
                # "NCBA CLUSA logo" contains NCBA but belongs to the National
                # Cooperative Business Association, not NCBA Group of Kenya.
                # A file carrying a significant word the company name does not
                # have is a different organisation.
                report.setdefault("rejected", []).append(a.get("title"))
                continue
            if a["reuse"] in ("permitted", "attribution"):
                a["kind"] = "logo"
                a["subject"] = company_name
                a["confidence"] = 0.8
                return a, report

    # Favicon fallback: a real logo, but at icon resolution and with no stated
    # licence, so it is only ever a visual aid, never the licensed centrepiece.
    domain = _logo_domain(ticker) if ticker else None
    if allow_favicon and domain:
        report["tried"].append("favicon:" + domain)
        a = _asset("logo",
                   "https://www.google.com/s2/favicons?domain=%s&sz=256" % domain,
                   source="favicon (%s)" % domain, title="%s favicon" % company_name,
                   licence=None, confidence=0.4, subject=company_name,
                   notes="site favicon at 256px; low resolution, licence not stated")
        return a, report
    report["reason"] = "no licensed logo found"
    return None, report


# ------------------------------------------------------------------ fetching
def _index():
    if os.path.exists(INDEX_FILE):
        try:
            return json.load(open(INDEX_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_index(ix):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(ix, f, ensure_ascii=False, indent=1)


def fetch(asset, max_bytes=12 * 1024 * 1024):
    """Download an asset to the local cache, recording its provenance.

    Adds `localPath`, `bytes` and `sha256` to the asset. Content type is checked
    against the bytes actually returned - a 404 HTML page must not be cached and
    later composited as if it were a logo.
    """
    if not asset or not asset.get("url"):
        return None
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = hashlib.sha256(asset["url"].encode()).hexdigest()[:20]
    ix = _index()
    hit = ix.get(key)
    if hit and os.path.exists(hit.get("localPath", "")):
        asset.update({k: hit[k] for k in ("localPath", "bytes", "sha256") if k in hit})
        return asset

    req = urllib.request.Request(asset["url"], headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip()
            data = r.read(max_bytes + 1)
    except Exception as e:
        asset["error"] = "%s: %s" % (type(e).__name__, str(e)[:80])
        return None
    if len(data) > max_bytes:
        asset["error"] = "image larger than %d bytes" % max_bytes
        return None
    if not ctype.startswith("image/"):
        asset["error"] = "not an image (content-type %r)" % ctype
        return None

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/svg+xml": ".svg",
           "image/webp": ".webp", "image/gif": ".gif"}.get(ctype, ".bin")
    path = os.path.join(CACHE_DIR, key + ext)
    with open(path, "wb") as f:
        f.write(data)
    asset["localPath"] = path
    asset["bytes"] = len(data)
    asset["sha256"] = hashlib.sha256(data).hexdigest()
    asset["contentType"] = ctype
    ix[key] = {"url": asset["url"], "localPath": path, "bytes": len(data),
               "sha256": asset["sha256"], "fetchedAt": int(time.time()),
               "source": asset.get("source"), "licence": asset.get("licence")}
    _save_index(ix)
    return asset


def publishable(assets, allow_unlicensed=False):
    """Split assets into what may be republished and what may not."""
    ok, refused = [], []
    for a in assets:
        if not a:
            continue
        if a["reuse"] in ("permitted", "attribution") or allow_unlicensed:
            ok.append(a)
        else:
            refused.append(a)
    return ok, refused


if __name__ == "__main__":
    import sys
    what = sys.argv[1] if len(sys.argv) > 1 else "person"
    arg = sys.argv[2] if len(sys.argv) > 2 else "Aliko Dangote"
    comp = sys.argv[3] if len(sys.argv) > 3 else None
    if what == "person":
        a, rep = find_person(arg, comp)
    else:
        a, rep = find_logo(arg, comp)
    print(json.dumps({"asset": a, "report": rep}, indent=1, ensure_ascii=False)[:2600])
