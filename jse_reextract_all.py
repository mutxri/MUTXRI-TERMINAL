#!/usr/bin/env python3
"""jse_reextract_all.py - wipe ALL income statements and re-extract with the
fixed parser (note-ref / over-fusion fix). Reuses downloaded PDFs.
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "jse_financials_data.json")
PDFS = os.path.join(BASE, "jse_pdfs")
sys.path.insert(0, BASE)
from jse_extract import extract

def find_pdf(t):
    for f in os.listdir(PDFS):
        if f.endswith(".pdf") and (f.startswith(t) or f.split("_")[0].startswith(t[:3])):
            return os.path.join(PDFS, f)
    return None

def main():
    data = json.load(open(DATA, encoding="utf-8"))
    targets = [t for t, v in data.items() if v.get("figures")]
    print(f"re-extracting income for {len(targets)} issuers with figures")

    filled, failed = 0, 0
    for i, t in enumerate(targets, 1):
        pdf = find_pdf(t)
        if not pdf:
            failed += 1
            continue
        try:
            res = extract(pdf, t)
            inc = res.get("income") or {}
            figs = data[t].setdefault("figures", {})
            if inc:
                figs["income"] = inc
                data[t].setdefault("income_page", res.get("income_page"))
                filled += 1
            else:
                figs.pop("income", None)  # wipe stale
                failed += 1
        except Exception as e:
            figs = data[t].setdefault("figures", {})
            figs.pop("income", None)
            failed += 1
        if i % 10 == 0:
            print(f"  {i}/{len(targets)} (filled {filled})")
            json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = sum(1 for v in data.values() if v.get("figures"))
    with_inc = sum(1 for v in data.values() if (v.get("figures") or {}).get("income"))
    print(f"\nDONE: filled {filled}, failed {failed}")
    print(f"total with figures: {total} | with income: {with_inc}")

if __name__ == "__main__":
    main()
