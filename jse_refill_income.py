#!/usr/bin/env python3
"""jse_refill_income.py - re-extract INCOME statements for issuers that got
balance/cashflow in the first crawl but missed income (banks/retailers whose
fragmented headers defeated the label matcher before the case-insensitive +
distinctive-line-item fix). Reuses downloaded PDFs; only fills gaps."""
import json, os, sys, re

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "jse_financials_data.json")
PDFS = os.path.join(BASE, "jse_pdfs")
sys.path.insert(0, BASE)
from jse_extract import extract

def main():
    data = json.load(open(DATA, encoding="utf-8"))
    targets = [t for t, v in data.items()
               if (v.get("figures") or {}) and "income" not in (v.get("figures") or {})]
    print(f"targets without income: {len(targets)}")

    filled, failed = 0, 0
    for i, t in enumerate(targets, 1):
        # find the PDF by ticker prefix (files like SBK_2026.pdf, WHLE_2025.pdf)
        pdf = None
        for f in os.listdir(PDFS):
            if f.endswith(".pdf") and (f.startswith(t) or f.split("_")[0].startswith(t[:3])):
                pdf = os.path.join(PDFS, f)
                break
        if not pdf:
            failed += 1
            continue
        try:
            res = extract(pdf, t)
            inc = res.get("income") or {}
            if inc:
                figs = data[t].setdefault("figures", {})
                figs["income"] = inc
                data[t].setdefault("income_page", res.get("income_page"))
                filled += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
        if i % 10 == 0:
            print(f"  {i}/{len(targets)} (filled {filled})")
            json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = sum(1 for v in data.values() if v.get("figures"))
    with_inc = sum(1 for v in data.values() if (v.get("figures") or {}).get("income"))
    print(f"\nDONE: filled {filled}, still missing {failed}")
    print(f"total with figures: {total} | with income: {with_inc}")

if __name__ == "__main__":
    main()
