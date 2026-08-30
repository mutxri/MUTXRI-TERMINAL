#!/usr/bin/env python3
"""merge_logos.py - merge verified ticker->domain results into logos.json.
Merges (never replaces). Deployed via contents API afterward."""
import json, os, sys

SD = r"D:\mutxri-terminal\static_data"
logos_path = os.path.join(SD, "logos.json")
logos = json.load(open(logos_path, encoding="utf-8"))

# read all result files passed on the command line
added = 0
skipped = 0
for path in sys.argv[1:]:
    if not os.path.exists(path):
        print(f"missing: {path}")
        continue
    data = json.load(open(path, encoding="utf-8"))
    for tkr, domain in data.items():
        domain = (domain or "").strip().lower().rstrip("/")
        domain = domain.replace("https://", "").replace("http://", "").replace("www.", "")
        if not domain or "." not in domain:
            continue
        if tkr in logos:
            skipped += 1
        else:
            logos[tkr] = domain
            added += 1

json.dump(logos, open(logos_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"merged: +{added} new, {skipped} already present, total={len(logos)}")
