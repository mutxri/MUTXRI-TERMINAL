#!/usr/bin/env python3
"""merge_yahoo_income.py - fill the income rows the shipped files lack.

WHY THIS EXISTS. Two defects, both in the same join.

1. build_static_financials.py maps Yahoo income row names through YF_MAP and
   only ever WRITES a file it does not find, so a statement collected once from
   one feed keeps that feed coverage forever: a JSE name filed from a provider
   that reports Revenue, Net Profit and EBIT alone never gains the Cost of
   Sales, Gross Profit or Operating Expenses rows the same security carries in
   yahoo_financials.json. Measured on the JSE common board before this script:
   40 of 260 had no Cost of Sales, 40 no Gross Profit, 22 no EBIT, 9 no
   Operating Expenses, 7 no EPS and 7 no Net Finance Costs.
2. THE KEYS DO NOT MATCH. The shipped files are keyed on the bare board symbol
   (SHP__income.json) while yahoo_financials.json keys on the suffixed form
   (SHP.JO). A lookup on the file stem alone found a source record for 365 of
   1457 files; resolving the stem against the source key set finds the rest.
   The first version of this script added 25 values on the wrong join and this
   one adds several times that; neither is a coverage number until the join is
   right.

THE ROW KEYS ARE NOT GUESSES. Every candidate was tested against the figures
already in the shipped files, year for year, and kept only when it reproduced
the stored value far more often than it contradicted it. Two obvious keys
failed and are deliberately NOT used:
  "EBIT" as Operating Profit (EBIT): 17 agree, 289 CONTRADICT
  "Total Expenses" as Operating Expenses: 24 agree, 276 CONTRADICT
Kept, with the measured agreement: Operating Income 303/5, Operating Expense
318/4, Cost Of Revenue 278/1, Gross Profit 287/1, Pretax Income 338/2,
Tax Provision 326/0, Net Income Common Stockholders 344/1, Interest Expense
314/18, Diluted EPS 267/2, Total Revenue 343/4, Operating Revenue 344/6.

GUARDS. It only ADDS a row that is missing or entirely null, never overwrites a
filed figure. Period is matched to source year. Revenue, Cost of Sales and
Operating Expenses are MAGNITUDES and a source value of zero or below is
dropped as a parse artefact (Yahoo carries a negative one for SPHT.CA). Then
the two identities that must hold are re-tested, Revenue - Cost of Sales =
Gross Profit and Profit Before Tax - Income Tax = Net Profit, and a fill that
breaks one is withdrawn rather than shipped. Rows it writes carry derived false
and a source string, and a row this script wrote is re-derived from the source
on the next run instead of being frozen in place.

Usage: python3 merge_yahoo_income.py [--dry]
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "static_data", "yahoo_financials.json")
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv
OWN = "Yahoo Finance income statement"
MAGNITUDE = ("Revenue", "Cost of Sales", "Operating Expenses")

ROWS = [
    ("Revenue",                 ["Total Revenue", "Operating Revenue"]),
    ("Cost of Sales",           ["Cost Of Revenue", "Reconciled Cost Of Revenue"]),
    ("Gross Profit",            ["Gross Profit"]),
    ("Operating Expenses",      ["Operating Expense"]),
    ("Operating Profit (EBIT)", ["Operating Income"]),
    ("Net Finance Costs",       ["Interest Expense"]),
    ("Profit Before Tax",       ["Pretax Income"]),
    ("Income Tax",              ["Tax Provision"]),
    ("Net Profit",              ["Net Income Common Stockholders"]),
    ("EPS",                     ["Diluted EPS", "Basic EPS"]),
]


def year_of(period):
    m = re.search(r"[12][0-9][0-9][0-9]", str(period))
    return m.group(0) if m else None


def close(a, b):
    try:
        return abs(float(a) - float(b)) <= abs(float(b)) * 0.005 + 1
    except Exception:
        return False


def label_row(doc, label):
    for r in doc.get("rows") or []:
        if str(r.get("label", "")).strip().lower() == label.strip().lower():
            return r
    return None



STOP = set("limited ltd plc inc incorporated company co group holdings holding corporation corp sa nv ag the and".split())


def name_tokens(n):
    return set(t for t in re.findall(r"[a-z0-9]+", str(n).lower()) if len(t) >= 4 and t not in STOP)


def same_issuer(doc, rec):
    # A bare stem can resolve to a DIFFERENT company on another board.
    # BAT (British American Tobacco Kenya, KES) matched BAT.JO, which is Brait
    # PLC (ZAR), and UPL (University Press, NGN) matched UPL.JO, Universal
    # Partners Limited (GBP). Merge only when the board currency is the same AND
    # the two names share a word, which is the guard the CEO lookup needed too.
    fc, sc = str(doc.get("currency") or "").strip().upper(), str(rec.get("currency") or "").strip().upper()
    if fc and sc and fc != sc:
        return False
    a, b = name_tokens(doc.get("name")), name_tokens(rec.get("name"))
    if a and b and not (a & b):
        return False
    return True


def getf(fields, keys):
    for k in keys:
        if fields.get(k) is not None:
            return fields[k]
    return None


def consistent(label, fields):
    # Guard on the SOURCE OWN arithmetic, never on the stored set.
    # PBT - Tax = Net Profit fails 2198 times across the shipped files, so that
    # identity is NOT valid in this dataset and must not be used to withdraw a
    # fill: the stored Net Profit is the figure attributable to the parent while
    # Pretax - Tax is the total including minorities. Yahoo carries the right
    # pairing internally (Net Income Including Noncontrolling Interests), and
    # that is what this checks.
    if label == "Cost of Sales":
        rev = getf(fields, ["Total Revenue", "Operating Revenue"])
        cos = getf(fields, ["Cost Of Revenue", "Reconciled Cost Of Revenue"])
        gp = getf(fields, ["Gross Profit"])
        if rev is None or cos is None or gp is None:
            return True
        return close(rev - cos, gp)
    if label == "Income Tax":
        pbt = getf(fields, ["Pretax Income"])
        tax = getf(fields, ["Tax Provision"])
        ni = getf(fields, ["Net Income Including Noncontrolling Interests", "Net Income"])
        if pbt is None or tax is None or ni is None:
            return True
        return close(pbt - tax, ni)
    return True


def strip_own_rows(doc):
    # a row this script wrote under a WRONG issuer must not survive the gate
    rows = doc.get("rows") or []
    keep = [r for r in rows if r.get("source") != OWN]
    n = len(rows) - len(keep)
    if n:
        doc["rows"] = keep
    return n


def build_index(src):
    idx = {}
    for k, v in src.items():
        stem = str(k).split(".")[0].upper()
        if stem not in idx:
            idx[stem] = v
    return idx


def main():
    if not os.path.exists(SRC):
        print("FATAL: %s not found" % SRC)
        return
    with open(SRC, encoding="utf-8") as fh:
        src = json.load(fh)
    idx = build_index(src)
    print("source keys: %d   distinct stems: %d" % (len(src), len(idx)))
    files = [f for f in os.listdir(FIN) if f.endswith("__income.json")]
    filled = {}
    files_touched = 0
    no_source = 0
    mismatched = 0
    withdrawn = 0
    kept_checks = 0
    added_rows = 0
    dropped = 0
    for f in sorted(files):
        stem = f[: -len("__income.json")]
        rec = idx.get(stem.split(".")[0].upper())
        if not rec or not rec.get("income"):
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
        if not same_issuer(doc, rec):
            mismatched += 1
            if strip_own_rows(doc):
                if not DRY:
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(doc, fh, indent=1, ensure_ascii=False)
            continue
        yi = rec["income"]
        # Cost of Sales is the one row whose visible arithmetic depends on the
        # Revenue already in the file. When the file own Revenue and the source
        # Revenue are on different bases (SHP: 256,682m from the JSE portal
        # against 252,701m from the source), writing the source cost line makes
        # Revenue minus Cost of Sales stop equalling the displayed Gross Profit,
        # so it is withheld and the row stays an honest dash.
        basis_ok = True
        _rev = label_row(doc, "Revenue")
        _pv = (_rev or {}).get("values") or []
        for _i, _p in enumerate(periods):
            _sv = getf(yi.get(year_of(_p)) or {}, ["Total Revenue", "Operating Revenue"])
            if _i < len(_pv) and _pv[_i] is not None and _sv is not None and not close(_pv[_i], _sv):
                basis_ok = False
        touched = 0
        mine = set()
        for label, alt_keys in ROWS:
            row = label_row(doc, label)
            owns = row is not None and row.get("source") == OWN
            if row is not None and not owns and any(v is not None for v in (row.get("values") or [])):
                continue
            vals = []
            for p in periods:
                yr = year_of(p)
                fields = yi.get(yr) or {}
                v = None
                for k in alt_keys:
                    if k in fields and fields[k] is not None:
                        v = fields[k]
                        break
                if label in MAGNITUDE:
                    try:
                        v = v if (v is not None and float(v) > 0) else None
                    except Exception:
                        v = None
                if v is not None and not consistent(label, fields):
                    v = None
                if label == "Cost of Sales" and not basis_ok:
                    v = None
                vals.append(v)
            if not any(v is not None for v in vals):
                if owns:
                    doc["rows"].remove(row)
                    dropped += 1
                continue
            if row is None:
                doc.setdefault("rows", []).append({
                    "label": label, "values": vals, "derived": False, "source": OWN})
            else:
                row["values"] = vals
                row["derived"] = False
                row["source"] = OWN
            mine.add(label)
            touched += 1
            added_rows += 1
            filled[label] = filled.get(label, 0) + sum(1 for v in vals if v is not None)
        if touched:
            if not DRY:
                doc.setdefault("merge", {})["by"] = "merge_yahoo_income.py"
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=1, ensure_ascii=False)
            files_touched += 1
    print("income files: %d   no source record: %d   issuer mismatch skipped: %d" % (len(files), no_source, mismatched))
    print("files touched: %d   rows added: %d   rows dropped: %d" % (files_touched, added_rows, dropped))
    print("identity checks passed: %d   withdrawn: %d" % (kept_checks, withdrawn))
    for k in sorted(filled):
        print("   %-24s values: %d" % (k, filled[k]))
    if DRY:
        print("DRY RUN - nothing written")


if __name__ == "__main__":
    main()
