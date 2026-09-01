#!/usr/bin/env python3
"""sanitize_financials.py - drop values in static_data/financials/*.json that
cannot be the figure they claim to be.

Some NSE statements were scraped out of filing PDFs and captured table
artefacts instead of numbers: Absa Bank Kenya's income statement shipped
"Revenue: 10.0 KES / 5.0 / 21.0 / 7.0" and Standard Chartered's shipped
"Income Tax: 3.0 KES". Rendered next to real billions, those read as genuine
figures. A statement line is money in NGN/KES/ZAR/EGP - published in thousands
at minimum - so anything under a thousand is an artefact, as is a bare report
year sitting in a money field.

A file left with nothing real is marked unavailable so the panel falls back to
its filings-links state instead of showing a statement made of dashes.
"""
import json, os, glob

BASE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "static_data", "financials")
RATIO_LABELS = {"eps"}          # per-share and ratio rows are legitimately small
# exact zero is a real reported figure and must survive the floor below
MIN_MONEY = 1000.0


def suspect(label, v, siblings=()):
    """siblings are the other values on the same line, used to judge whether a
    year-sized number is a real figure or a stray date."""
    if v is None or isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return True
    if label.strip().lower() in RATIO_LABELS:
        return False
    if v == 0:
        return False          # a company that paid no tax really did report 0
    if abs(v) < MIN_MONEY:
        return True
    # a bare year only counts as an artefact when the rest of the line is
    # orders of magnitude bigger - otherwise 2,000 may simply be the figure
    if 1900 <= v <= 2100 and float(v).is_integer():
        return any(isinstance(x, (int, float)) and abs(x) >= 1e6 for x in siblings)
    return False


def main():
    files = sorted(glob.glob(os.path.join(DIR, "*.json")))
    scrubbed = emptied = 0
    hits = []
    for p in files:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        rows = d.get("rows") or []
        changed = False
        for r in rows:
            lbl = r.get("label", "")
            vals = r.get("values") or []
            for i, v in enumerate(vals):
                if suspect(lbl, v, [x for j, x in enumerate(vals) if j != i]):
                    hits.append((os.path.basename(p), lbl, v))
                    vals[i] = None
                    changed = True
        if not changed:
            continue
        scrubbed += 1
        if not any(v is not None for r in rows for v in (r.get("values") or [])):
            d["available"] = False
            d["periods"] = []
            emptied += 1
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, allow_nan=False)

    print(f"{len(files)} statement files scanned | {scrubbed} had artefact values "
          f"removed | {emptied} left with nothing real (marked unavailable)")
    for h in hits[:25]:
        print(f"    {h[0]}: {h[1]} = {h[2]}")
    if len(hits) > 25:
        print(f"    ... and {len(hits)-25} more")


if __name__ == "__main__":
    main()
