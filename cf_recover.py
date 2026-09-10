#!/usr/bin/env python3
"""cf_recover.py - recover cash-flow statements the main parser cannot see.

ngx_parse matches a label only when it is the WHOLE line, which is why a long
list of "Net cash from/used in/generated from ..." variants still leaves ~30
statements empty: those filings print the figures on the same line as the label

    Net Cash flow from Operating activities ( 2,524)
    Net Cash used for Investing Activities (1,367,515) (396,790)
    Net cash (used in)/from operating activities 18,426

and no amount of adding exact strings will catch them. This is a supplementary
pass, not a change to ngx_parse: it runs only for tickers that currently have no
cash-flow rows, so the 500-odd statements that already parse cannot regress.

Matching is structural rather than literal - "net cash", any of the connectors
filings actually use (from / used in / used for / generated in / inflow /
"(used in)/from"), then one of the three activity classes - with an optional
trailing note reference. Values are read inline when present, otherwise from the
lines below, the same way the main parser does it.

Rule kept from the house standard: never fabricate. A statement is written only
when at least two of the three activity lines are found, and figures that fail a
sanity check are dropped rather than guessed.

usage: python cf_recover.py [--apply]      (default: dry run)
"""
import glob
import json
import os
import re
import sys
import warnings

import pdfplumber

warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
OUT = os.path.join(BASE, "_cf_out")
APPLY = "--apply" in sys.argv

CLASSES = [("operating", "Operating Cash Flow"),
           ("investing", "Investing Cash Flow"),
           ("financing", "Financing Cash Flow")]

# "net cash", then any connector these filings actually use, then the class
LINE_RE = re.compile(
    r"(?i)\bnet\s+cash\s*(?:flows?)?\s*"
    r"(?:\(?(?:used\s+in|used\s+for|generated|inflow|outflow|provided)\)?"
    r"[\s/]*)*"
    r"(?:in|from|for|by)?\s*"
    r"(operating|investing|financing)\s+activities")
CHANGE_RE = re.compile(r"(?i)\bnet\s+(?:increase|decrease|change)[^\n]{0,40}"
                       r"in\s+cash(?:\s+and\s+cash\s+equivalents)?")
NUM_RE = re.compile(r"\(?\s*-?[\d][\d,]*(?:\.\d+)?\s*\)?")
NOTE_ONLY = re.compile(r"^\s*(?:[a-z]|\d{1,2}(?:\.\d+)?)\s*$", re.I)


def repair_digits(line):
    """Rejoin figures the PDF text layer split with spaces.

    NGX filings extract as "9 ,948,938", "1 ,433,725,619", "7 3,317,626" and
    "( 535,280,087)". Read as-is a regex takes "9" and drops the rest, so the
    recovered figure is wrong by orders of magnitude - the difference between a
    real number and a fabricated one.
    """
    s = re.sub(r"\(\s+", "(", line)               # "( 535,280,087)" -> "(535,280,087)"
    s = re.sub(r"(\d)\s+(?=,)", r"\1", s)          # "1 ,433,725" -> "1,433,725"
    # Only an orphaned one-or-two-digit fragment joins rightwards. Without the
    # lookbehind this also welds two complete adjacent figures together:
    # "4,551,934 9,948,938" would become one number.
    s = re.sub(r"(?<![\d,])(\d{1,2})\s+(\d,)", r"\1\2", s)
    return s

def to_num(tok):
    t = tok.strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace(" ", "")
    if not t or t in {"-", "."}:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def unit_scale(text):
    """Filings state their own scale; respect it rather than assuming."""
    t = text.lower()
    if re.search(r"n'?\s?000|kobo|shs\s*'?\s*000|kshs?\s*'?\s*000|in thousands|'000", t):
        return 1000.0
    if re.search(r"\bin millions\b|n'?\s?m\b|millions of", t):
        return 1e6
    if re.search(r"\bin billions\b", t):
        return 1e9
    return 1.0


def real_figures(tokens):
    """Drop note references. These rows often read

        Net Cash Flow from Operating Activities a 3 09,337

    where "a" is a note letter and "3" its number - taking the first number
    yields an operating cash flow of 3. A bare one-or-two-digit integer is
    only kept when nothing figure-shaped follows it.
    """
    shaped = [i for i, (raw, v) in enumerate(tokens)
              if ("," in raw or "." in raw or len(raw.strip("()- ")) >= 4)]
    if shaped:
        return [v for i, (raw, v) in enumerate(tokens) if i >= shaped[0]]
    return [v for _, v in tokens]


def numbers_after(lines, i, want=6):
    """Inline figures if the row carries them, else the lines below."""
    tail = LINE_RE.split(lines[i], maxsplit=1)
    if len(tail) > 1:
        toks = [(m.group(), to_num(m.group())) for m in NUM_RE.finditer(tail[-1])]
        inline = real_figures([(r, v) for r, v in toks if v is not None])
        if inline:
            return inline[:want]
    vals, j = [], i + 1
    while j < len(lines) and len(vals) < want:
        s = lines[j].strip()
        if not s or NOTE_ONLY.match(s):
            j += 1
            continue
        toks = [(m.group(), to_num(m.group())) for m in NUM_RE.finditer(s)]
        found = real_figures([(r, v) for r, v in toks if v is not None])
        if not found:
            break
        vals.extend(found)
        j += 1
    return vals[:want]


def parse(path):
    with pdfplumber.open(path) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    text = "\n".join(pages)
    if len(text) < 200:
        return None, "scanned - no text layer"

    scale = unit_scale(text)
    got = {}
    for page in pages:
        lines = [repair_digits(l) for l in page.split("\n")]
        for i, ln in enumerate(lines):
            m = LINE_RE.search(ln)
            if m:
                out_label = dict(CLASSES)[m.group(1).lower()]
                if out_label in got:
                    continue
                vals = numbers_after(lines, i)
                if vals:
                    got[out_label] = vals
            elif CHANGE_RE.search(ln) and "Net Change in Cash" not in got:
                vals = numbers_after(lines, i)
                if vals:
                    got["Net Change in Cash"] = vals

    activity = [l for _, l in CLASSES if l in got]
    if len(activity) < 2:
        return None, "only %d of 3 activity lines found" % len(activity)

    # Three activity totals from one statement belong to the same order of
    # magnitude. When they do not, a note reference has been read as a figure
    # (operating cash flow of 1,000 beside investing of -19 billion), so the
    # statement is refused rather than published.
    mags = [abs(got[l][0]) for l in activity if got[l] and got[l][0]]
    if len(mags) >= 2 and max(mags) / max(min(mags), 1e-9) > 1e4:
        return None, "activity totals differ by >10,000x - note refs misread"

    n = min(len(got[l]) for l in activity)
    n = max(1, min(n, 5))
    rows = []
    for label in [l for _, l in CLASSES] + ["Net Change in Cash"]:
        if label in got:
            rows.append({"label": label,
                         "values": [round(v * scale, 2) for v in got[label][:n]]})
    return {"rows": rows, "periods_found": n, "scale": scale}, None


def targets():
    """Tickers whose cash-flow statement is missing or empty, with a source PDF."""
    out = []
    for f in sorted(glob.glob(os.path.join(FIN, "*__income.json"))):
        t = os.path.basename(f).split("__")[0]
        cf = os.path.join(FIN, "%s__cashflow.json" % t)
        empty = True
        if os.path.exists(cf):
            d = json.load(open(cf, encoding="utf-8"))
            empty = not d.get("available") or not any(
                any(v is not None for v in (r.get("values") or [])) for r in d.get("rows", []))
        if not empty:
            continue
        for d in ("_ngx_pdf", "_nse_pdf"):
            p = os.path.join(BASE, d, "%s.pdf" % t)
            if os.path.exists(p):
                out.append((t, p, "NGX" if d == "_ngx_pdf" else "NSE"))
                break
    return out


def main():
    idx_path = os.path.join(BASE, "static_data", "financials_index.json")
    index = json.load(open(idx_path, encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    ok = fail = 0
    for ticker, pdf, ex in targets():
        res, err = parse(pdf)
        if err:
            fail += 1
            print("  %-12s skipped: %s" % (ticker, err))
            continue
        meta = index.get(ticker, {})
        doc = {"ticker": ticker, "name": meta.get("name", ticker),
               "currency": meta.get("currency", "NGN" if ex == "NGX" else "KES"),
               "source": meta.get("source", "%s filing" % ex),
               "statement": "cashflow", "statementTitle": "Cash Flow",
               "period": "annual", "available": True,
               "periods": ["FY%d" % (2025 - i) for i in range(res["periods_found"])],
               "rows": res["rows"]}
        doc["asOf"] = doc["periods"][0]
        ok += 1
        print("  %-12s %s" % (ticker, [(r["label"].split()[0], r["values"][0]) for r in res["rows"]]))
        if APPLY:
            with open(os.path.join(FIN, "%s__cashflow.json" % ticker), "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)
        with open(os.path.join(OUT, "%s__cashflow.json" % ticker), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)

    print("\nrecovered %d, skipped %d%s" % (ok, fail, "" if APPLY else "  (dry run - pass --apply)"))


if __name__ == "__main__":
    main()
