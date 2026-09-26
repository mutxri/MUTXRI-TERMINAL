#!/usr/bin/env python3
"""annotate_reconciliation.py - make the statements self-describing.

_audit_sanity.py flags filed values that do not hold up arithmetically. Per
references/statement-integrity.md rule 2 there are two classes and they get
OPPOSITE treatment:

  impossible  - e.g. a negative Revenue. A top line cannot be negative, so the
                source's column is scrambled, not the company's trading. NULL
                that period and record the reason on the row.
                "an honest blank beats a wrong number"

  unreconciled - the source's printed Net Change in Cash disagrees with its own
                Operating + Investing + Financing sections. The figure itself is
                possible, so it SHIPS as printed; the disagreeing periods are
                named in `reconciliation_note` so the panel can be read against
                the source without anyone re-deriving the discrepancy.

Only ever blanks an IMPOSSIBLE value. An existing reconciliation_note is
extended, never overwritten.

Usage: python3 annotate_reconciliation.py [--apply]
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
APPLY = "--apply" in sys.argv
TOL = 0.02

REV = ("revenue", "total revenue", "revenue from operations", "net revenue")
OCF = ("operating cash flow", "net cash from operating activities")
ICF = ("investing cash flow", "net cash used in investing activities")
FCF = ("financing cash flow", "net cash from financing activities")
NCC = ("net change in cash", "net increase in cash")

IMPOSSIBLE_REASON = ("nulled: a negative value is arithmetically impossible for this "
                     "row, so the source's column is mis-signed or mis-mapped "
                     "rather than the issuer reporting a negative magnitude")


def rows_of(d):
    return (d or {}).get("rows") or []


def find(rows, aliases):
    for r in rows:
        if str(r.get("label", "")).strip().lower() in aliases:
            return r
    return None


def period_at(d, i):
    ps = d.get("periods") or []
    return ps[i] if i < len(ps) else "index %d" % i


def main():
    nulled = []
    noted = []

    for f in sorted(os.listdir(FIN)):
        if not f.endswith(".json") or "__" not in f:
            continue
        path = os.path.join(FIN, f)
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        rows = rows_of(d)
        changed = False

        if f.endswith("__income.json"):
            rev = find(rows, REV)
            if rev:
                vals = rev.get("values") or []
                hits = []
                for i, v in enumerate(vals):
                    if isinstance(v, (int, float)) and v < 0:
                        hits.append(period_at(d, i))
                        vals[i] = None
                if hits:
                    rev["values"] = vals
                    rev["note"] = IMPOSSIBLE_REASON
                    nulled.append((f, hits))
                    changed = True

        if f.endswith("__cashflow.json"):
            o = find(rows, OCF)
            i_ = find(rows, ICF)
            fn = find(rows, FCF)
            nc = find(rows, NCC)
            if all(x is not None for x in (o, i_, fn, nc)):
                ov, iv, fv, nv = (o.get("values") or [], i_.get("values") or [],
                                  fn.get("values") or [], nc.get("values") or [])
                bad = []
                for k in range(min(len(ov), len(iv), len(fv), len(nv))):
                    a, b, c, e = ov[k], iv[k], fv[k], nv[k]
                    if not all(isinstance(x, (int, float)) for x in (a, b, c, e)):
                        continue
                    if abs(e - (a + b + c)) > max(abs(e) * TOL, 1):
                        bad.append((period_at(d, k), e, a + b + c))
                if bad:
                    line = ("Net Change in Cash as printed by the source does not equal "
                            "Operating + Investing + Financing in "
                            + ", ".join("%s (printed %s vs %s)" % (p, g, x) for p, g, x in bad)
                            + ". Both figures are as filed and are shown unchanged.")
                    old = d.get("reconciliation_note")
                    if not old:
                        d["reconciliation_note"] = line
                    elif "does not equal Operating + Investing + Financing" not in old:
                        d["reconciliation_note"] = old.rstrip(". ") + ". " + line
                    else:
                        continue          # already annotated; idempotent
                    noted.append((f, [b[0] for b in bad]))
                    changed = True

        if changed and APPLY:
            json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)

    print("impossible values nulled (files): %d" % len(nulled))
    for f, ps in nulled:
        print("   %-28s %s" % (f, ", ".join(ps)))
    print()
    print("reconciliation notes added (files): %d" % len(noted))
    for f, ps in noted[:10]:
        print("   %-28s %s" % (f, ", ".join(ps)))
    if len(noted) > 10:
        print("   ... and %d more" % (len(noted) - 10))
    print()
    print("DRY RUN - nothing written" if not APPLY else "APPLIED")


if __name__ == "__main__":
    main()
