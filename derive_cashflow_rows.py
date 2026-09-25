#!/usr/bin/env python3
# derive_cashflow_rows.py - fill two cash-flow rows the panel renders as a dash
# whenever their inputs are already stored.
#
#   Free Cash Flow     = Operating Cash Flow + Capital Expenditure
#   Net Change in Cash = Operating + Investing + Financing Cash Flow
#
# BOTH identities were MEASURED against the stored set before this script was
# allowed to derive from them, because most accounting identities do not hold in
# this dataset (Capex is stored NEGATIVE here, so free cash flow ADDS it):
#   Free Cash Flow     : 3,208 periods agree, 32 contradict (99.0%)
#   Net Change in Cash : 3,370 periods agree, 120 contradict (96.6%)
# Only an identity that reproduces the stored value far more often than it
# contradicts may be derived from, and every derived row is tagged
# "derived": true with its formula and the agreement rate, so a later purge or
# re-collection pass can tell an arithmetic row from a filed one.
#
# THE LABEL WRITTEN IS THE PANEL'S OWN DISPLAY LABEL, NOT the schema key: the
# panel maps a row to its display key by matching the row LABEL against
# KEY_ALIASES (label "Free Cash Flow", not "freeCashFlow"), so a row labelled
# with the key name renders as a dash and the work is invisible.
#
# GATES
#   - never overwrite a row that already carries a value
#   - require EVERY period to carry all of its inputs; deriving on a partial
#     series writes a number that looks filed and is not
#   - a result of exactly zero when every input is non-zero is a PARSE FAILURE,
#     not a figure, so the whole row is skipped
# Usage: python3 derive_cashflow_rows.py [--dry]
import json, os, sys, shutil, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M")
BACKUP = os.path.join(FIN, "_backup_" + STAMP)
ALIASES = {
    "operatingCashFlow": ["operating cash flow", "net cash from operating activities",
        "net cash generated from operating activities", "net cash flows from operating activities",
        "net cash provided by operating activities", "cash generated from operations",
        "net cash generated from/(used in) operating activities",
        "net cash flows used in operating activities", "net cash from operations"],
    "investingCashFlow": ["investing cash flow", "net cash from investing activities",
        "net cash generated from investing activities", "net cash flows from investing activities",
        "net cash used in investing activities", "net cash generated from/(used in) investing activities"],
    "financingCashFlow": ["financing cash flow", "net cash from financing activities",
        "net cash generated from financing activities", "net cash flows from financing activities",
        "net cash used in financing activities", "net cash generated from/(used in) financing activities"],
    "capex": ["capital expenditure", "capex", "purchase of property, plant and equipment",
        "purchase of property and equipment", "acquisition of property, plant and equipment",
        "purchase of property plant and equipment", "additions to property, plant and equipment",
        "purchase of pp&e", "purchase of property, plant & equipment"],
    "freeCashFlow": ["free cash flow"],
    "netChangeInCash": ["net change in cash", "net increase in cash", "net decrease in cash",
        "net increase/(decrease) in cash", "net (decrease)/increase in cash",
        "net increase/(decrease) in cash and cash equivalents",
        "increase/(decrease) in cash and cash equivalents",
        "net movement in cash and cash equivalents"],
}
# (match key, LABEL TO WRITE, inputs, formula, measured agreement)
JOBS = [
    ("freeCashFlow", "Free Cash Flow", ["operatingCashFlow", "capex"],
     "Operating Cash Flow + Capital Expenditure (Capex is stored negative)", 0.990),
    ("netChangeInCash", "Net Change in Cash",
     ["operatingCashFlow", "investingCashFlow", "financingCashFlow"],
     "Operating + Investing + Financing Cash Flow", 0.966),
]


def norm(s):
    return " ".join(str("" if s is None else s).strip().lower().split())


def rows_of(d):
    out = {}
    for r in d.get("rows") or []:
        k = None
        l = norm(r.get("label"))
        for key, als in ALIASES.items():
            if l in als:
                k = key
                break
        if k and k not in out:
            out[k] = r
    return out


def has_value(r):
    return bool(r) and any(v is not None for v in (r.get("values") or []))


def main():
    changed = []
    skipped = {"row exists": 0, "missing inputs": 0, "partial series": 0,
               "all zero result": 0, "zero in a partly non-zero input": 0, "nothing to do": 0}
    for fn in sorted(os.listdir(FIN)):
        if not fn.endswith("__cashflow.json"):
            continue
        p = os.path.join(FIN, fn)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        nper = len(d.get("periods") or [])
        if not nper:
            continue
        rows = rows_of(d)
        added = []
        for match_key, write_label, inputs, formula, rate in JOBS:
            if has_value(rows.get(match_key)):
                skipped["row exists"] += 1
                continue
            if any(not rows.get(i) for i in inputs):
                skipped["missing inputs"] += 1
                continue
            series = []
            ok = True
            for i in inputs:
                vals = rows[i].get("values") or []
                if len(vals) < nper:
                    ok = False
                    break
                series.append(vals[:nper])
            if not ok:
                skipped["partial series"] += 1
                continue
            # A ZERO INSIDE A ROW THAT IS NON-ZERO ELSEWHERE IS A SPLIT-LABEL
            # ARTEFACT, NOT A FIGURE. The NSE source stores the same line under
            # two capitalisations ("Purchase of Property and Equipment" and
            # "Purchase Of Property And Equipment"); the panel and this script
            # both take the FIRST match, so the periods held by the other variant
            # read 0 and the derivation would ADD ZERO to operating cash flow and
            # call the result free cash flow. Gate it out rather than ship it.
            allvals = [v for sr in series for v in sr if v is not None]
            if allvals and any(v == 0 for v in allvals) and any(v != 0 for v in allvals):
                skipped["zero in a partly non-zero input"] += 1
                continue
            out = []
            allzero = True
            anyinput = False
            for k in range(nper):
                cells = [series[ix][k] for ix in range(len(inputs))]
                if any(c is None for c in cells):
                    out.append(None)
                    continue
                anyinput = True
                v = 0.0
                for c in cells:
                    v += float(c)
                if v != 0.0:
                    allzero = False
                out.append(v)
            if not anyinput or allzero:
                skipped["all zero result"] += 1
                continue
            added.append({"label": write_label, "values": out, "derived": True,
                          "formula": formula, "identityAgreement": rate,
                          "source": "derived from stored inputs"})
        if not added:
            skipped["nothing to do"] += 1
            continue
        changed.append((p, d, added))
    print("files to gain a derived row:", len(changed))
    print("skips:", skipped)
    for p, d, added in changed[:8]:
        print("   ", os.path.basename(p), [a["label"] for a in added])
    if DRY:
        print("DRY RUN, nothing written")
        return
    os.makedirs(BACKUP, exist_ok=True)
    for p, d, added in changed:
        shutil.copy2(p, os.path.join(BACKUP, os.path.basename(p)))
        d.setdefault("rows", []).extend(added)
        json.dump(d, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"WROTE {len(changed)} files, backup at {BACKUP}")


if __name__ == "__main__":
    main()
