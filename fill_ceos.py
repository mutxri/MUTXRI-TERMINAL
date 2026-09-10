#!/usr/bin/env python3
"""fill_ceos.py - fill and date-stamp the CEO field from Yahoo's officer data.

Kenya Airways shipped for years showing Titus Naikuni, who left in 2014, and
Naspers showed Bob van Dijk two years after he went. Nothing recorded where a
name came from or when it was last checked, so nothing could rot visibly.

This fills the gap from Yahoo's assetProfile.companyOfficers and writes the
provenance beside it: name, title as published, source, and the date checked.

Three judgements it makes, all of which matter for correctness:

  * Titles are ranked, not taken first. A profile lists "Group CEO", "CEO of
    South Africa" and "CFO" together; the subsidiary CEO is not the company's
    chief executive. Group/global titles win, divisional ones are ignored.
  * Acting appointments keep their qualifier. "Ag." or "Interim" in the title is
    carried into the stored name, because a reader deciding whether to trust the
    figure needs to know the seat is not settled.
  * Hand-verified entries are never overwritten. Anything already in
    ceos_sources.json was checked against the company's own disclosure, which
    outranks an aggregator - Yahoo itself can lag a transition by months.

usage: python fill_ceos.py [--apply] [--limit N] [--exchange JSE]
"""
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
CEOS = os.path.join(SD, "ceos.json")
META = os.path.join(SD, "ceos_sources.json")
TODAY = time.strftime("%Y-%m-%d")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

APPLY = "--apply" in sys.argv


def arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


# most specific first - the first pattern that matches decides the seat
TITLE_RANK = [
    (re.compile(r"\b(group|global)\b.*\bchief exec|\bgroup ceo\b", re.I), 0),
    (re.compile(r"^(mr\.?|ms\.?|mrs\.?|dr\.?)?\s*(chief executive officer|ceo)\b", re.I), 1),
    (re.compile(r"\bchief executive officer\b|\bceo\b", re.I), 2),
    (re.compile(r"\bmanaging director\b|\bmd\b", re.I), 3),
]
# a divisional or country chief executive is not the company's chief executive
# A divisional or country chief executive is not the company's chief executive.
# This must match the SPELLED-OUT form as well as the abbreviation: Absa's Yahoo
# profile carries no group CEO, and "Chief Executive Officer of Personal &
# Private Banking" slipped through a "ceo of" pattern and was very nearly
# published as the CEO of one of the JSE's largest banks.
DIVISIONAL = re.compile(
    r"\b(?:ceo|chief\s+executive(?:\s+officer)?)\s+of\s+(?!the\s+group\b)"
    r"|\bco-chief\s+executive"
    r"|\b(country|regional|divisional|subsidiary|unit|division)\b"
    r"|-\s*(cib|rbb|pbb)\b", re.I)
ACTING = re.compile(r"\b(acting|interim|ag\.)\b", re.I)
HONORIFIC = re.compile(r"^(mr|mrs|ms|miss|dr|prof|capt|hon)\.?\s+", re.I)
# Yahoo appends degrees to names ("Simon Baloyi M.Sc.", "Jeanett M. Modise B.Com,
# MDP"). Strip from the first qualification token to the end - the name always
# precedes them. Initials like "M." inside a name are safe: they are single
# letters followed by a name, not one of these tokens.
# The terminating boundary must NOT be \b: a qualification ending in a period
# ("B.A.") has no word boundary after it, so \b silently failed and "Alberto
# Calderon B.A." shipped as the name. A negative lookahead for a letter works
# for both "B.A." and "BSc".
#
# Two or more leading capitals marks a qualification rather than a name token
# (BBusSci, BSc, LLB), and is safe for real surnames: McEwan and MacDonald have
# a lowercase second letter.
# The bare initials branch "(X.){2,}" must only fire at the END of the name or
# before a comma. Without that guard it matches the initials in "Mr. D.J. de
# Villiers", strips everything after them, and leaves the name as "Mr." - which
# is exactly what happened to Alexander Forbes on the first pass. Named
# qualifications (M.Sc., B.Com) are unambiguous and need no such guard.
QUALS = re.compile(
    r"\s+(?:(?:(?:[A-Za-z]\.){2,})(?=\s*(?:,|$))"
    r"|(?:M\.?Sc\.?|B\.?Sc\.?|B\.?Com\.?|M\.?B\.?A\.?|Ph\.?\s?D\.?|LL\.?[BM]\.?"
    r"|C\.?A\.?|CFA|ACCA|CPA|CIMA|MDP|Hons?|Agric|Econ"
    r"|[A-Z]{2,}[A-Za-z]*)(?![A-Za-z])).*$")
TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def clean_name(raw):
    n = re.sub(r"\s+", " ", (raw or "").strip())
    n = TRAILING_PAREN.sub("", n)
    n = QUALS.sub("", n)
    n = n.split(",")[0].strip()
    n = HONORIFIC.sub("", n)     # Yahoo prefixes "Mr."/"Ms."; existing entries do not
    return n.strip()


def pick_officer(officers):
    """The chief executive, or nothing. Never a guess."""
    best = None
    for o in officers or []:
        title = (o.get("title") or "").strip()
        if not title or DIVISIONAL.search(title):
            continue
        for pat, rank in TITLE_RANK:
            if pat.search(title):
                if best is None or rank < best[0]:
                    best = (rank, o.get("name") or "", title)
                break
    if not best:
        return None, None
    _, name, title = best
    name = clean_name(name)
    if not name:
        return None, None
    if ACTING.search(title) and not ACTING.search(name):
        name += " (Ag.)"
    return name, title


class Yahoo:
    """quoteSummary needs a cookie plus a crumb; one handshake serves the run."""

    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        try:
            self.op.open(urllib.request.Request("https://fc.yahoo.com", headers=UA), timeout=20)
        except Exception:
            pass
        try:
            r = self.op.open(urllib.request.Request(
                "https://query1.finance.yahoo.com/v1/test/getcrumb", headers=UA), timeout=20)
            self.crumb = r.read().decode().strip()
        except Exception:
            self.crumb = ""

    def officers(self, sym):
        if not self.crumb:
            return None
        url = ("https://query2.finance.yahoo.com/v10/finance/quoteSummary/%s"
               "?modules=assetProfile&crumb=%s"
               % (urllib.parse.quote(sym), urllib.parse.quote(self.crumb)))
        try:
            r = self.op.open(urllib.request.Request(url, headers=UA), timeout=25)
            d = json.loads(r.read().decode())
            res = (d.get("quoteSummary") or {}).get("result") or []
            if not res:
                return None
            return (res[0].get("assetProfile") or {}).get("companyOfficers") or []
        except Exception:
            return None


def listings(only=None):
    out = []
    for ex in ("JSE", "NGX", "NSE", "EGX"):
        if only and ex != only:
            continue
        p = os.path.join(SD, "listing_%s.json" % ex)
        if not os.path.exists(p):
            continue
        L = json.load(open(p, encoding="utf-8"))
        rows = L if isinstance(L, list) else (L.get("stocks") or [])
        for s in rows:
            sym = s.get("sym")
            if sym:
                out.append((ex, sym, s.get("name") or ""))
    return out


def main():
    ceos = json.load(open(CEOS, encoding="utf-8"))
    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {}
    hand = {k for k, v in meta.items() if "yahoo" not in (v.get("source", "")).lower()}

    limit = int(arg("--limit", "0") or 0)
    rows = listings(arg("--exchange"))
    todo = [r for r in rows if r[1] not in hand]
    if limit:
        todo = todo[:limit]

    y = Yahoo()
    if not y.crumb:
        print("could not obtain a Yahoo crumb - aborting rather than writing blanks")
        return 1
    print("crumb ok; checking %d securities%s\n" % (len(todo), "" if APPLY else "  (dry run)"))

    stats = {"filled": 0, "changed": 0, "same": 0, "no_officer": 0, "no_profile": 0}
    changes = []
    for i, (ex, sym, name) in enumerate(todo, 1):
        offs = y.officers(sym)
        if offs is None:
            stats["no_profile"] += 1
        else:
            ceo, title = pick_officer(offs)
            if not ceo:
                stats["no_officer"] += 1
            else:
                prev = ceos.get(sym)
                if prev == ceo:
                    stats["same"] += 1
                else:
                    stats["changed" if prev else "filled"] += 1
                    changes.append((ex, sym, name[:26], prev, ceo, title))
                ceos[sym] = ceo
                meta[sym] = {"name": ceo, "title": title,
                             "source": "Yahoo assetProfile.companyOfficers",
                             "checked": TODAY}
        if i % 25 == 0:
            print("  ... %d/%d" % (i, len(todo)), flush=True)
        time.sleep(0.25)

    if APPLY:
        json.dump(ceos, open(CEOS, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(meta, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n  newly filled     %d" % stats["filled"])
    print("  corrected        %d" % stats["changed"])
    print("  already correct  %d" % stats["same"])
    print("  no CEO in profile %d" % stats["no_officer"])
    print("  no Yahoo profile  %d" % stats["no_profile"])
    print("\n  sample of corrections (previous -> new):")
    for ex, sym, nm, prev, ceo, title in [c for c in changes if c[3]][:12]:
        print("    %-4s %-11s %-26s %-22s -> %s" % (ex, sym, nm, prev, ceo))
    if not APPLY:
        print("\n  dry run - pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
