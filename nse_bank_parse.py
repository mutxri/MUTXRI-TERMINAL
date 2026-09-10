#!/usr/bin/env python3
"""nse_bank_parse.py - income statements from NSE condensed results notices.

Kenyan listed banks publish to a Central Bank of Kenya template: numbered line
items, several entity blocks side by side (Bank / Company / Consolidated), each
carrying the same two periods. These notices are one flattened page, which is
why a table parser produced nothing and they landed in the "no financial
statements" list.

The trap is that most of these pages also carry a narrative column beside the
figures. Read line by line, "custody surpassed Kshs. 69 billion" lands in the
middle of the net-interest-income row and a regex happily takes 69 as a figure.
So this works from word COORDINATES: numeric columns are located once per page
by clustering the x-centres of numeric tokens, and any number that does not sit
in one of those columns - i.e. any number from the prose - is discarded.

Two more things it refuses to assume, because getting either wrong produces a
wrong number rather than a missing one:

  * Column order. ABSA prints 2024 then 2025; KCB prints 31-Dec-25 then
    31-Dec-24. The period header is parsed and the output follows the document.
  * Which block is the listed entity. The consolidated group is the last block
    on these notices, so figures come from the final period pair, and the basis
    is recorded in the output so a reader can check it.

Units are read from the document ("Shs '000" / "Kshs 000") and scaled to
absolute currency, matching the majority convention in static_data.

usage: python nse_bank_parse.py <pdf> <symbol> <name> <out_dir>
"""
import json
import os
import re
import sys
import warnings

import pdfplumber

warnings.filterwarnings("ignore")

WANTED = [
    ("Revenue", r"total operating income"),
    ("Net Interest Income", r"net interest income"),
    ("Operating Expenses", r"total operating expenses"),
    ("Profit Before Tax", r"profit.{0,30}before tax"),
    ("Income Tax", r"^\s*\d*\.?\s*current tax\b"),
    ("Net Profit", r"profit.{0,30}after tax"),
    ("EPS", r"earnings per share"),
]
NUMTOK = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")


def to_num(tok):
    neg = tok.startswith("(") and tok.endswith(")")
    t = tok.strip("()").replace(",", "")
    if not t or t in {"-", "."}:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def rows_from_words(page, ytol=2.5):
    """Group words into visual rows, keeping x positions."""
    rows = []
    for w in sorted(page.extract_words(), key=lambda w: (round(w["top"], 1), w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]) <= ytol:
            rows[-1][1].append(w)
        else:
            rows.append([w["top"], [w]])
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in rows]


def numeric_columns(rows, min_numbers=4):
    """Find the x-centres of the figure columns, from rows that look like data."""
    centres = []
    for ws in rows:
        nums = [w for w in ws if NUMTOK.match(w["text"])]
        if len(nums) >= min_numbers:
            centres.extend((w["x0"] + w["x1"]) / 2 for w in nums)
    if not centres:
        return []
    centres.sort()
    clusters, cur = [], [centres[0]]
    for c in centres[1:]:
        if c - cur[-1] <= 18:
            cur.append(c)
        else:
            clusters.append(cur); cur = [c]
    clusters.append(cur)
    # keep well-populated clusters: real columns repeat down the page
    strong = [sum(c) / len(c) for c in clusters if len(c) >= 4]
    return strong


def figures_in_row(ws, cols, tol=22):
    """Numbers that sit in a real column. Prose numbers are dropped."""
    out = []
    for w in ws:
        if not NUMTOK.match(w["text"]):
            continue
        mid = (w["x0"] + w["x1"]) / 2
        if any(abs(mid - c) <= tol for c in cols):
            v = to_num(w["text"])
            if v is not None:
                out.append((mid, v))
    return [v for _, v in sorted(out)]


def find_periods(rows):
    """Period labels in the order the document prints them.

    Only year-shaped tokens count. Matching bare two-digit numbers turns the
    "31" of 31-Dec-25 into 2031, which is how KCB first came out as FY2031.
    """
    for ws in rows[:20]:
        text = " ".join(w["text"] for w in ws)
        yrs = re.findall(r"(?<![0-9])(20[0-9]{2})(?![0-9])", text)
        if len(set(yrs)) < 2:
            yrs = ["20" + y for y in
                   re.findall(r"(?i)[A-Z][a-z]{2}-([0-9]{2})(?![0-9])", text)]
        yrs = [y for y in yrs if 2015 <= int(y) <= 2035]
        if len(yrs) >= 2 and len(set(yrs)) >= 2:
            return yrs
    return []


def unit_scale(text):
    if re.search(r"(?i)k?shs?\.?\s*'?\s*000", text):
        return 1000.0, "Shs '000"
    if re.search(r"(?i)\bmillions?\b", text[:2500]):
        return 1e6, "millions"
    return 1.0, "units (no scale stated)"


def parse(path, symbol, name):
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        rows = rows_from_words(page)
        text = page.extract_text() or ""
    cols = numeric_columns(rows)
    if len(cols) < 2:
        return None, "could not locate figure columns"
    years = find_periods(rows)
    if len(years) < 2:
        return None, "could not read the period header"
    scale, unit_src = unit_scale(text)

    found = {}
    for ws in rows:
        line = " ".join(w["text"] for w in ws)
        for label, pat in WANTED:
            if label in found or not re.search(pat, line, re.I):
                continue
            nums = figures_in_row(ws, cols)
            if len(nums) < 2:
                continue
            pair = nums[-2:]                      # consolidated block, last pair
            mult = 1.0 if label == "EPS" else scale
            found[label] = [round(v * mult, 2) for v in pair]

    if "Net Profit" not in found and "Profit Before Tax" not in found:
        return None, "no profit line found"

    # A statement that contradicts itself is worse than a missing one: refuse to
    # emit it rather than publish a figure taken from the wrong column.
    def val(label, i):
        return found.get(label, [None, None])[i]
    for i in (0, 1):
        pbt, np_, rev = val("Profit Before Tax", i), val("Net Profit", i), val("Revenue", i)
        if pbt and np_ and pbt > 0 and np_ > 0:
            if np_ > pbt * 1.05:
                return None, "net profit exceeds pre-tax profit - columns misread"
            if pbt / np_ > 20:
                return None, "pre-tax profit over 20x net profit - columns misread"
        if rev and np_ and abs(np_) > abs(rev) * 1.5:
            return None, "net profit exceeds revenue - columns misread"

    # The last pair of columns is the consolidated block, and its years are the
    # last two in the header - but documents print them either way round (ABSA
    # runs 2024 then 2025, KCB runs Dec-25 then Dec-24). Pair each figure with
    # its own year and sort newest first, matching the rest of static_data,
    # rather than trusting the printed order.
    col_years = [int(years[-2]), int(years[-1])]
    newest_first = col_years[0] > col_years[1]
    periods = ["FY%d" % y for y in sorted(col_years, reverse=True)]

    def ordered(vals):
        return list(vals) if newest_first else list(reversed(vals))

    order = [l for l, _ in WANTED if l in found]
    doc = {
        "ticker": symbol, "name": name, "currency": "KES",
        "source": "NSE (nse.co.ke) - condensed results notice",
        "asOf": periods[0], "statement": "income",
        "statementTitle": "Income Statement", "period": "annual",
        "periods": periods, "available": True,
        "basis": "consolidated group, %d figure columns, scale %s" % (len(cols), unit_src),
        "rows": [{"label": l, "values": ordered(found[l])} for l in order],
    }
    return doc, None


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    pdf, symbol, name, out_dir = sys.argv[1:5]
    doc, err = parse(pdf, symbol, name)
    if err:
        print("  %-8s SKIPPED: %s" % (symbol, err))
        return 1
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "%s__income.json" % symbol), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    print("  %-8s %s | %s" % (symbol, doc["periods"], doc["basis"]))
    for r in doc["rows"]:
        print("      %-22s %s" % (r["label"], r["values"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
