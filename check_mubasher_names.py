#!/usr/bin/env python3
"""check_mubasher_names.py - reject a Mubasher CEO whose page is a different company.

Our EGX listing and Mubasher do not always agree on which company a ticker is:
our CCAP row is named "Heibco for Commercial Investment", while Mubasher's CCAP
page is Qalaa Holdings - so its managing director would have been published as
Heibco's. Every name taken from Mubasher is checked here: the page heading's
company name must share a distinctive word with the listing name, otherwise the
name is removed from ceos.json (only if it came from Mubasher) and reported.

usage: python check_mubasher_names.py [--apply]
"""
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, "static_data")
PREVIEW = os.path.join(HERE, "_mubasher_ceos_preview.json")
OUT = os.path.join(HERE, "_mubasher_name_check.json")
APPLY = "--apply" in sys.argv
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "Chrome/128 Safari/537.36"}
GENERIC = set("""co company for and the of s a e sae egypt egyptian misr el al
international investment investments financial holding holdings group development
industries industrial real estate commercial trading general national new co.
pharmaceuticals pharmaceutical pharma chemicals chemical cement food foods mills flour
bakeries company inc corporation plc ltd limited services textile textiles spinning
weaving reclamation contracting construction housing tourism hotels bank insurance
products packaging printing medical agricultural engineering projects enterprises""".split())


def words(s):
    s = re.sub(r"\(.*?\)", " ", s or "").lower()
    return {w for w in re.findall(r"[a-z]{3,}", s) if w not in GENERIC}


def main():
    prev = json.load(open(PREVIEW, encoding="utf-8"))
    ceos = json.load(open(os.path.join(S, "ceos.json"), encoding="utf-8"))
    meta = json.load(open(os.path.join(S, "ceos_sources.json"), encoding="utf-8"))
    rows = json.load(open(os.path.join(S, "listing_EGX.json"), encoding="utf-8"))["stocks"]
    by_tk = {str(r.get("ticker")): r for r in rows}

    ok, bad = {}, {}
    for tk, v in prev.items():
        try:
            raw = urllib.request.urlopen(urllib.request.Request(v["url"], headers=UA),
                                         timeout=40).read().decode("utf-8", "replace")
            h1 = re.sub(r"<[^>]+>", " ", (re.findall(r"<h1[^>]*>(.*?)</h1>", raw, re.S) or [""])[0])
            h1 = " ".join(h1.split())
        except Exception as e:
            h1 = ""
        time.sleep(1.2)
        lw, pw = words(v["company"]), words(h1)
        rec = {"listing": v["company"], "mubasher": h1, "name": v["name"]}
        # The heading must be THIS ticker's page: MPHA's URL served Minapharm (MIPH),
        # and "Pharmaceuticals" alone let Memphis match it. Then the company names
        # must share a distinctive word, compared with spacing removed as well so
        # "GlaxoSmithKline" and "Glaxo Smith Kline" agree.
        same_page = ("(%s)" % tk.upper()) in h1.upper() or ("-%s)" % tk.upper()) in h1.upper()
        lc = re.sub(r"[^a-z]", "", re.sub(r"\(.*?\)", "", v["company"].lower()))
        pc = re.sub(r"[^a-z]", "", re.sub(r"\(.*?\)", "", h1.lower()))
        compact = bool(lc and pc) and (lc[:10] in pc or pc[:10] in lc)
        if h1 and same_page and (lw & pw or compact):
            ok[tk] = rec
        else:
            bad[tk] = rec
            print("MISMATCH %-6s listing=%r  mubasher=%r" % (tk, v["company"], h1), flush=True)

    json.dump({"ok": ok, "mismatch": bad}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n  name match %d | mismatch %d" % (len(ok), len(bad)))
    if APPLY:
        removed = 0
        for tk in bad:
            r = by_tk.get(tk) or {}
            for k in {tk, str(r.get("sym") or "")} - {""}:
                if "mubasher" in str((meta.get(k) or {}).get("source", "")).lower():
                    ceos.pop(k, None)
                    meta.pop(k, None)
                    removed += 1
        json.dump(ceos, open(os.path.join(S, "ceos.json"), "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(meta, open(os.path.join(S, "ceos_sources.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("  removed %d mismatched keys from ceos.json" % removed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
