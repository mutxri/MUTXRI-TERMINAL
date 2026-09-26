#!/usr/bin/env python3
"""trim_phantom_periods.py - drop trailing statement columns that hold no data.

The panel renders one column per entry in a file's `periods` array. Some files
declare more periods than they carry figures for (a five-year header with two
years parsed), so the panel prints whole columns of dashes for years the file
reports nothing about. Measured on the shipped set: 996 files carry 1,204 such
phantom columns, which render as 8,140 dash cells.

Trimming is not hiding a gap: a period in which NO row of the file holds a value
is a column the file does not actually report. A period that any row populates is
always kept, even where most rows are dashes, because that dash is a real gap and
must stay visible.

The trim records itself on the file as `periods_note`, so a shorter header is
explainable rather than mysterious, and never touches a value.

Files with no data in ANY row are left alone: those are the funds and structured
notes (JSE AMC0xx, ETFs) that publish no statements at all, and their emptiness
is a different, already-documented fact.

Usage: python3 trim_phantom_periods.py [--apply]
"""
import json, os, shutil, sys, datetime
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
APPLY = "--apply" in sys.argv


def main():
    touched = 0
    dropped_cols = 0
    killed_cells = 0
    by_type = Counter()
    bak = os.path.join(BASE, "static_data",
                       "_bak_periods_%s" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    for f in sorted(os.listdir(FIN)):
        if not f.endswith(".json") or "__" not in f[:-5] or "pre_2026" in f:
            continue
        p = os.path.join(FIN, f)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        per = d.get("periods") or []
        rows = d.get("rows") or []
        if not per or not rows:
            continue
        deepest = -1
        for r in rows:
            for i, x in enumerate(r.get("values") or []):
                if x is not None and i > deepest:
                    deepest = i
        if deepest < 0:                 # nothing at all: a fund/note, leave it
            continue
        trail = len(per) - 1 - deepest
        if trail <= 0:
            continue
        removed = per[deepest + 1:]
        d["periods"] = per[:deepest + 1]
        note = ("columns dropped: %s - no row in this file carries a figure for "
                "them, so they rendered as pure dashes" % ", ".join(str(x) for x in removed))
        old = d.get("periods_note")
        d["periods_note"] = (old.rstrip(". ") + ". " + note) if old else note
        touched += 1
        dropped_cols += trail
        typ = f[:-5].rsplit("__", 1)[-1]
        by_type[typ] += 1
        for r in rows:
            v = r.get("values") or []
            for i in range(deepest + 1, len(per)):
                if i >= len(v) or v[i] is None:
                    killed_cells += 1
        if APPLY:
            os.makedirs(bak, exist_ok=True)
            shutil.copy(p, bak)
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("files trimmed: %d" % touched)
    print("phantom columns removed: %d" % dropped_cols)
    print("dash cells no longer rendered: %d" % killed_cells)
    for k in sorted(by_type):
        print("   %-10s %d files" % (k, by_type[k]))
    print()
    print("DRY RUN - nothing written" if not APPLY else "APPLIED (originals in %s)" % os.path.basename(bak))


if __name__ == "__main__":
    main()
