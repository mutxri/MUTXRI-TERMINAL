#!/usr/bin/env python3
"""merge_ngx_ceos.py - merge the AFS-extracted NGX CEO names into ceos.json.

Only rows that carry a document citation are merged, and a pick whose own line
says retired/former/resigned is SKIPPED (the filing is then out of date and the
successor has to come from a later announcement). Every merged entry lands in
ceos_sources.json with the file, page and printed line, so the name can be
re-checked against the report it came from.

usage: python merge_ngx_ceos.py [--dry]
"""
import json, os, sys, re, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
ST = os.path.join(BASE, "static_data")
DUMP = os.path.join(BASE, "_ngx_ceos_from_afs.json")
DRY = "--dry" in sys.argv

def sanitize(name):
    """Names arrive attached to whatever the PDF printed next to them."""
    n = re.sub(r"\s*\([^)]*$", "", name)                       # trailing "(" or "(Ag."
    n = re.sub(r"\s*[-–,]\s*(?:Non-)?Executive\s+Director.*$", "", n, flags=re.I)
    n = re.sub(r"\s*[-–,]?\s*(?:Ag\.?|Co-?)$", "", n, flags=re.I)
    n = re.sub(r"[\s\[\(\*–—]+$", "", n)                       # footnote and dash tails
    n = re.sub(r"\s+", " ", n).strip(" -,:;.()[]")
    return n


dump = json.load(open(DUMP, encoding="utf-8"))
ceos = json.load(open(os.path.join(ST, "ceos.json"), encoding="utf-8"))
srcs = json.load(open(os.path.join(ST, "ceos_sources.json"), encoding="utf-8"))
listing = {s.get("ticker") or s.get("sym") for s in
           json.load(open(os.path.join(ST, "listing_NGX.json"), encoding="utf-8"))["stocks"]}
today = datetime.date.today().isoformat()

added, skipped_stale, off_listing, rejected = [], [], [], []
for sym, v in dump.items():
    if not v.get("source"):
        continue
    name = sanitize(v["name"])
    if v.get("stale"):
        skipped_stale.append((sym, name, v["line"]))
        continue
    if not re.match(r"^[A-Z][A-Za-z.'\- ]{4,50}$", name) or len(name.split()) < 2:
        rejected.append((sym, name, v["line"]))
        continue
    if sym not in listing:
        off_listing.append(sym)
        continue
    ceos[sym] = name
    srcs[sym] = {"name": name, "title": v.get("title", "Managing Director / CEO"),
                 "source": v["source"], "checked": today, "line": v.get("line", "")}
    added.append((sym, name))

print(f"merged {len(added)} NGX CEO names (source = the company's own annual report)")
if rejected:
    print(f"rejected {len(rejected)} malformed picks:")
    for r in rejected:
        print(f"   {r[0]:12s} {r[1]:32s} | {r[2][:60]}")
for s in skipped_stale:
    print(f"   {s[0]:12s} {s[1]:30s} | {s[2][:70]}")
if off_listing:
    print("not in the NGX listing:", off_listing)
if DRY:
    print("dry run, nothing written")
    sys.exit(0)
json.dump(ceos, open(os.path.join(ST, "ceos.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
json.dump(srcs, open(os.path.join(ST, "ceos_sources.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(f"ceos.json now holds {len(ceos)} names, ceos_sources.json {len(srcs)} citations")
