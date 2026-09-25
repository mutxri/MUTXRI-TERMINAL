#!/usr/bin/env python3
"""validate_financials.py - suppress figures that cannot be true.

The parsers occasionally pull two line items from different scale columns of the
same statement, which produces numbers that are not merely wrong but impossible:
Dangote Cement shipped with a gross profit twelve times its revenue.

A structurally impossible number is worse than a gap. The house rule for this
data set is "never fabricate a number", and a mis-parsed figure is a fabricated
one - it just arrived by accident rather than on purpose.

So: for each period, test the identities that must hold in any income statement.
Where one fails we cannot tell WHICH of the two figures is wrong, so this does
not guess - it drops both and leaves the panel to render an honest dash. Every
suppression is written to _fin_suppressed.json so the affected statements can be
re-parsed properly later.

Identities tested, per period:
    gross profit <= revenue
    net profit   <= pre-tax profit           (a tax credit gets 5% headroom)
    pre-tax profit <= 20x net profit         (catches mixed-scale columns)

Deliberately NOT enforced: net profit == pre-tax + tax. Minority interests and
discontinued operations break that legitimately, and enforcing it flagged 70% of
the book - a threshold that noisy tells you nothing.

usage: python validate_financials.py [--apply]     (default is a dry run)
"""
import glob
import json
import os
import sys

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data", "financials")
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fin_suppressed.json")
APPLY = "--apply" in sys.argv


def row(rows, label):
    for r in rows:
        if r.get("label") == label:
            return r
    return None


def check(rows):
    """Return {period_index: [(label_a, label_b, reason)]} for impossible pairs."""
    hits = {}

    def pair(a, b, test, reason, skip=None):
        ra, rb = row(rows, a), row(rows, b)
        if not ra or not rb:
            return
        va, vb = ra.get("values") or [], rb.get("values") or []
        for i in range(min(len(va), len(vb))):
            x, y = va[i], vb[i]
            if x is None or y is None:
                continue
            if skip is not None and skip(i, x, y):
                continue
            if test(x, y):
                hits.setdefault(i, []).append((a, b, reason))

    # Signed, not absolute. Cost of sales is never negative, so gross profit can
    # never sit ABOVE revenue - but it can sit below it by more than revenue's
    # own size. An investment holding company with fair-value losses reports
    # negative revenue (EPE Capital Partners, FY2025: revenue -726.8M, gross
    # profit -757.2M); a business selling below cost reports a gross loss larger
    # than its revenue. Both are real. Comparing magnitudes flagged both as
    # impossible and suppressed them.
    pair("Revenue", "Gross Profit",
         lambda rev, gp: bool(rev) and bool(gp) and gp > rev + abs(rev) * 0.02,
         "gross profit exceeds revenue")
    # A tax CREDIT legitimately pushes net profit ABOVE pre-tax profit, so a
    # strict np > pbt test suppresses figures the filer actually printed. AEG.JO
    # FY2024: pre-tax 16,083,000 with an income tax CREDIT of 9,657,000 gives
    # net profit 25,653,000, and the three numbers tie to within 0.4%. Before
    # this exception the pair was withheld and the ratio derived from it went
    # with it, so a real year read as blank. The tax row decides: only when it
    # cannot account for the gap is the pair treated as impossible.
    tax_row = row(rows, "Income Tax")
    tax_vals = (tax_row or {}).get("values") or []

    def tax_credit_explains(i, pbt, np_):
        if i >= len(tax_vals) or tax_vals[i] is None:
            return False
        t = tax_vals[i]
        if not isinstance(t, (int, float)) or t >= 0:
            return False          # a charge (or no figure) cannot explain it
        expected = pbt - t        # net profit = pre-tax less the tax line
        return abs(np_ - expected) <= max(abs(pbt) * 0.05, 1.0)

    pair("Profit Before Tax", "Net Profit",
         lambda pbt, np_: pbt > 0 and np_ > 0 and np_ > pbt * 1.05,
         "net profit exceeds pre-tax profit",
         skip=tax_credit_explains)
    pair("Profit Before Tax", "Net Profit",
         lambda pbt, np_: pbt > 0 and np_ > 0 and pbt / np_ > 20,
         "pre-tax profit over 20x net profit (mixed scale columns)")
    return hits


def main():
    files = sorted(glob.glob(os.path.join(DIR, "*__income.json")))
    suppressed, touched, emptied = {}, 0, 0

    for path in files:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if not doc.get("available"):
            continue
        rows = doc.get("rows", [])
        hits = check(rows)
        if not hits:
            continue

        ticker = os.path.basename(path).split("__")[0]
        periods = doc.get("periods", [])
        detail = []
        for i, problems in sorted(hits.items()):
            labels = set()
            for a, b, reason in problems:
                labels.update((a, b))
                detail.append({"period": periods[i] if i < len(periods) else "index %d" % i,
                               "fields": [a, b], "reason": reason})
            # cannot tell which side is wrong, so neither survives
            for lab in labels:
                r = row(rows, lab)
                if r and i < len(r.get("values", [])):
                    r["values"][i] = None

        # a row with nothing left is noise in the panel
        rows = [r for r in rows if any(v is not None for v in (r.get("values") or []))]
        doc["rows"] = rows
        doc["validated"] = True
        if not any(r["label"] in ("Revenue", "Net Profit", "Profit Before Tax") for r in rows):
            doc["available"] = False
            doc["unavailableReason"] = "figures failed accounting checks; awaiting re-parse"
            emptied += 1

        suppressed[ticker] = detail
        touched += 1
        if APPLY:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False)

    if APPLY:
        with open(REPORT, "w", encoding="utf-8") as fh:
            json.dump(suppressed, fh, indent=1, ensure_ascii=False)

    print("%s %d of %d income statements" % ("fixed" if APPLY else "would fix",
                                             touched, len(files)))
    print("  statements left with no usable figures: %d" % emptied)
    print("  individual figures suppressed: %d"
          % sum(len(v) * 2 for v in suppressed.values()))
    if not APPLY:
        print("\n  dry run - pass --apply to write")
    else:
        print("  report: %s" % REPORT)
    for t, d in list(suppressed.items())[:8]:
        print("   %-12s %s" % (t, d[0]["reason"] if d else ""))


if __name__ == "__main__":
    main()
