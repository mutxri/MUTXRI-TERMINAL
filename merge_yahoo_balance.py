#!/usr/bin/env python3
"""merge_yahoo_balance.py - fill the balance-sheet rows the shipped files lack.

WHY THIS EXISTS. The balance sheet is the emptiest statement in the panel, and
the cause was two wrong keys, not missing data. `build_static_financials.py`
maps the Yahoo row names through YF_MAP, which looks for:

    "Total Current Assets"      -> currentAssets
    "Total Current Liabilities" -> currentLiabilities

but yahoo_financials.json actually calls them:

    "Current Assets"
    "Current Liabilities"

So both rows came back empty and were dropped, which is why `Current
Liabilities` appears in 0 of 545 shipped balance files and `Current Assets` in
75 - while the source has each of them for 327 securities.

This merges those rows (and the rest of the balance schema) from the Yahoo
source into the existing per-security files. It only ADDS:

  - a row that is missing entirely, or
  - a row that is present with every value null.

It never overwrites a figure that is already there, so a value sourced from an
exchange filing keeps its provenance. Period labels are matched by year:
the shipped files carry "FY2026", the source keys on 2026.

Usage: python3 merge_yahoo_balance.py [--dry]
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "static_data", "yahoo_financials.json")
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv

# panel schema label -> the Yahoo balance row name that fills it
ROWS = [
    ("Non-current Assets",      ["Total Non Current Assets"]),
    ("Current Assets",          ["Current Assets", "Total Current Assets"]),
    ("Cash & Equivalents",      ["Cash Cash Equivalents And Short Term Investments",
                                 "Cash And Cash Equivalents"]),
    ("Total Assets",            ["Total Assets"]),
    ("Non-current Liabilities", ["Total Non Current Liabilities Net Minority Interest"]),
    ("Current Liabilities",     ["Current Liabilities", "Total Current Liabilities"]),
    ("Total Liabilities",       ["Total Liabilities Net Minority Interest", "Total Liabilities"]),
    ("Total Equity",            ["Total Equity Gross Minority Interest", "Stockholders Equity"]),
]


def year_of(period):
    """'FY2026' or '2026' or '2026-06-30' -> '2026'."""
    m = re.search(r"(19|20)\d{2}", str(period))
    return m.group(0) if m else None


def main():
    if not os.path.exists(SRC):
        print(f"FATAL: {SRC} not found"); return
    with open(SRC, encoding="utf-8") as fh:
        src = json.load(fh)
    print(f"source securities: {len(src)}")

    files = [f for f in os.listdir(FIN) if f.endswith("__balance.json")]
    filled = {}
    files_touched = 0
    no_source = 0
    for f in sorted(files):
        sym = f[: -len("__balance.json")]
        rec = src.get(sym)
        if not rec or not rec.get("balance"):
            no_source += 1
            continue
        path = os.path.join(FIN, f)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        periods = doc.get("periods") or []
        if not periods:
            continue
        yb = rec["balance"]
        existing = {}
        for r in doc.get("rows") or []:
            existing.setdefault(str(r.get("label", "")).strip().lower(), r)
        added_rows = 0
        for label, alt_keys in ROWS:
            row = existing.get(label.lower())
            if row is not None and any(v is not None for v in (row.get("values") or [])):
                continue                              # a real figure is already there
            vals = []
            for p in periods:
                yr = year_of(p)
                fields = yb.get(yr) or {}
                v = None
                for k in alt_keys:
                    if k in fields and fields[k] is not None:
                        v = fields[k]
                        break
                vals.append(v)
            if not any(v is not None for v in vals):
                continue
            if row is None:
                doc.setdefault("rows", []).append(
                    {"label": label, "values": vals, "derived": False,
                     "source": "Yahoo Finance balance sheet"})
            else:
                row["values"] = vals
                row["derived"] = False
                row["source"] = "Yahoo Finance balance sheet"
            existing[label.lower()] = {"label": label, "values": vals}
            added_rows += 1
            filled[label] = filled.get(label, 0) + sum(1 for v in vals if v is not None)
        if added_rows:
            files_touched += 1
            if not DRY:
                doc.setdefault("merge", {})["by"] = "merge_yahoo_balance.py"
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, ensure_ascii=False, indent=1)
    print(f"balance files: {len(files)} | no Yahoo record: {no_source}")
    print(f"files gained rows: {files_touched}")
    for k in sorted(filled, key=lambda x: -filled[x]):
        print(f"    {filled[k]:5} values  {k}")
    print(f"  TOTAL balance values added: {sum(filled.values())}")
    print("  (dry run)" if DRY else "  written")


if __name__ == "__main__":
    main()
