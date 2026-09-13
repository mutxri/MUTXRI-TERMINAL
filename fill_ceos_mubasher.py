#!/usr/bin/env python3
"""fill_ceos_mubasher.py - fill EGX chief executives from Mubasher company profiles.

Yahoo has no profile for any of the EGX securities missing a CEO (0 of 208), and
Wikipedia infoboxes for African companies returned parent-company CEOs, chairs
and outright wrong companies. Mubasher publishes a board-of-directors block on
every EGX company profile, in a consistent structure:

    <span class="company-profile__management__text1">NAME</span>
    <span class="company-profile__management__text2">ROLE</span>

Rules, because a wrong name is worse than a blank:
  * only executive-head roles count: CEO / Chief Executive Officer first, then
    Managing Director (including Egypt's common "Chairman & Managing Director")
  * a chairman on their own is not a CEO and is ignored
  * deputy / assistant / former roles are ignored
  * a "name" that is really an entity (a bank, holding, fund, ministry...) is
    rejected - board seats held by institutions appear in the same list
  * existing ceos.json entries are never overwritten
  * the role is stored verbatim beside the name, with the profile URL and the
    date checked, in ceos_sources.json

Board listings can lag a change, so every name carries its source and date
rather than presenting itself as live.

usage: python fill_ceos_mubasher.py            (dry run -> preview JSON only)
       python fill_ceos_mubasher.py --apply    (merge into ceos.json)
       python fill_ceos_mubasher.py --limit 10
"""
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, "static_data")
CEOS = os.path.join(S, "ceos.json")
META = os.path.join(S, "ceos_sources.json")
PREVIEW = os.path.join(HERE, "_mubasher_ceos_preview.json")
APPLY = "--apply" in sys.argv
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "Chrome/128 Safari/537.36", "Accept-Language": "en"}
TODAY = time.strftime("%Y-%m-%d")

PAIR = re.compile(
    r'company-profile__management__text1">\s*(.*?)\s*</span>\s*'
    r'<span class="company-profile__management__text2">\s*(.*?)\s*</span>',
    re.S | re.I)
ENTITY = re.compile(
    r"\b(company|co\.|bank|holding|holdings|insurance|group|fund|ministry|authority|"
    r"s\.a\.e|sae|ltd|limited|corporation|investments?|capital|trust|bureau|"
    r"organization|organisation|association|federation|misr|national)\b", re.I)
NOT_HEAD = re.compile(r"\b(deputy|assistant|former|advisor|adviser|secretary)\b", re.I)


def arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def has(v):
    return str(v or "").strip() not in ("", "-", "—", "None", "null")


def rank(role):
    r = role.lower()
    if NOT_HEAD.search(r):
        return None
    if "ceo" in r or "chief executive" in r:
        return 0
    if "managing director" in r:
        return 1
    return None


def candidates(row):
    seen = []
    for f in ("ticker", "code", "short", "display_sym", "data_sym", "sym"):
        v = str(row.get(f) or "").split(".")[0].upper().strip()
        if 2 <= len(v) <= 6 and v.isalpha() and v not in seen:
            seen.append(v)
    return seen


def fetch(code):
    url = "https://english.mubasher.info/markets/EGX/stocks/%s/profile" % code
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                     timeout=40).read().decode("utf-8", "replace")
    except Exception:
        return url, None
    return url, raw


def pick(raw):
    best = None
    for name, role in PAIR.findall(raw):
        name = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", name)).split())
        role = " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", role)).split())
        rk = rank(role)
        if rk is None or not name or ENTITY.search(name) or len(name) < 5:
            continue
        if best is None or rk < best[0]:
            best = (rk, name, role)
    return best


def main():
    ceos = json.load(open(CEOS, encoding="utf-8"))
    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {}
    rows = json.load(open(os.path.join(S, "listing_EGX.json"), encoding="utf-8"))["stocks"]

    todo = []
    for r in rows:
        if str(r.get("instrument")) not in ("common", "equity", "None"):
            continue
        keys = {str(r.get("sym") or ""), str(r.get("ticker") or "")} - {""}
        if any(has(ceos.get(k)) for k in keys):
            continue
        todo.append((r, keys))
    limit = int(arg("--limit", "0") or 0)
    if limit:
        todo = todo[:limit]
    print("EGX companies missing a CEO: %d%s" % (len(todo), "" if APPLY else "  (dry run)"),
          flush=True)

    preview, stats, misses = {}, {"found": 0, "no_page": 0, "no_head": 0}, []
    for i, (r, keys) in enumerate(todo, 1):
        got = None
        tried = None
        for code in candidates(r):
            url, raw = fetch(code)
            time.sleep(1.5)
            if not raw or "company-profile__management" not in raw:
                continue
            tried = url
            got = pick(raw)
            break
        tk = str(r.get("ticker") or r.get("sym") or "")
        if tried is None:
            stats["no_page"] += 1
            misses.append([tk, r.get("name"), "no page"])
        elif not got:
            stats["no_head"] += 1
            misses.append([tk, r.get("name"), "no CEO/MD listed"])
        else:
            stats["found"] += 1
            _, name, role = got
            preview[tk] = {"name": name, "role": role, "url": tried,
                           "company": r.get("name")}
            if APPLY:
                for k in keys:
                    if not has(ceos.get(k)):
                        ceos[k] = name
                        meta[k] = {"name": name, "title": role,
                                   "source": "Mubasher EGX company profile (board of directors)",
                                   "url": tried, "checked": TODAY}
        if i % 25 == 0:
            print("  ... %d/%d  found %d" % (i, len(todo), stats["found"]), flush=True)
            json.dump(preview, open(PREVIEW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if APPLY:
                json.dump(ceos, open(CEOS, "w", encoding="utf-8"), ensure_ascii=False)
                json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(preview, open(PREVIEW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(misses, open(PREVIEW.replace(".json", "_misses.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if APPLY:
        json.dump(ceos, open(CEOS, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    roles = {}
    for v in preview.values():
        roles[v["role"]] = roles.get(v["role"], 0) + 1
    print("\n  found %d | no Mubasher page %d | page but no CEO/MD listed %d"
          % (stats["found"], stats["no_page"], stats["no_head"]))
    print("  roles taken:", dict(sorted(roles.items(), key=lambda x: -x[1])))
    print("  preview written to %s" % PREVIEW)
    return 0


if __name__ == "__main__":
    sys.exit(main())
