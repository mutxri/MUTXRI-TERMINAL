#!/usr/bin/env python3
"""derive_ratios.py - compute the standard ratios from the statements we hold.

ROE and the margin ratios are pure arithmetic on figures already in the
financials files, so leaving them as dashes is a gap we created. This writes
them as extra rows on the INCOME statement, labelled to match the panel schema
in features/panels/afri_financials.html (the panel maps row label -> schema key
case-insensitively, so the label must match exactly).

Ratios written (all as percentages except Debt to Equity, which is a multiple):
    ROE (%)               = Net Profit / Total Equity x 100
    ROA (%)               = Net Profit / Total Assets x 100
    Net Margin (%)        = Net Profit / Revenue x 100
    Gross Margin (%)      = Gross Profit / Revenue x 100
    Operating Margin (%)  = Operating Profit (EBIT) / Revenue x 100
    Debt to Equity        = Total Liabilities / Total Equity

Rules:
  - Only written when BOTH inputs exist for that period, never from one.
  - Equity <= 0 or Revenue == 0 yields no ratio: a negative-equity ROE is
    meaningless and a zero-revenue margin is undefined. Leave a dash.
  - Every row is tagged derived with its formula.
Usage: python3 derive_ratios.py [--dry]
"""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(BASE, "static_data", "financials")
DRY = "--dry" in sys.argv

I_ALIAS = {
    "np":  ("net profit", "net income", "profit after tax", "profit for the year"),
    "rev": ("revenue", "total revenue", "revenue from operations", "net revenue"),
    "gp":  ("gross profit", "gross profit (loss)", "gross income"),
    "ebit":("operating profit (ebit)", "operating profit", "operating income", "ebit"),
}
B_ALIAS = {
    "eq":  ("total equity", "total stockholders' equity", "total shareholders' equity"),
    "ta":  ("total assets",),
    "tl":  ("total liabilities",),
}
# A ratio beyond these bounds cannot describe a real business, which means the
# INPUT is wrong, not the arithmetic. Measured on this data: 69 Net Margin, 52
# Operating Margin, 22 ROA, 13 ROE and 2 Gross Margin values were impossible
# (AIRTELAFRI revenue read as 1598 against a real ~5bn; ACTF profit 4x its
# revenue). Those inputs are bad parse output, so the derived ratio must be
# withheld rather than displayed as a confident-looking number.
CEILING = {
    "ROE (%)": 200.0,
    "ROA (%)": 100.0,
    "Net Margin (%)": 100.0,
    "Gross Margin (%)": 100.0,
    "Operating Margin (%)": 100.0,
    "Debt to Equity": 100.0,
}

RATIOS = [
    ("ROE (%)",              "np", "eq", 100.0, "Net Profit / Total Equity x 100"),
    ("ROA (%)",              "np", "ta", 100.0, "Net Profit / Total Assets x 100"),
    ("Net Margin (%)",       "np", "rev", 100.0, "Net Profit / Revenue x 100"),
    ("Gross Margin (%)",     "gp", "rev", 100.0, "Gross Profit / Revenue x 100"),
    ("Operating Margin (%)", "ebit", "rev", 100.0, "Operating Profit (EBIT) / Revenue x 100"),
    ("Debt to Equity",       "tl", "eq",   1.0, "Total Liabilities / Total Equity"),
]


def rows_of(p):
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None, None
    m = {}
    for r in d.get("rows") or []:
        m.setdefault(str(r.get("label", "")).strip().lower(), r)
    return m, d


def vals(m, alts):
    for a in alts:
        if a in m:
            v = m[a].get("values") or []
            if any(x is not None for x in v):
                return v
    return None


def main():
    have = set(os.listdir(FIN))
    incs = sorted(f for f in have if f.endswith("__income.json"))
    written = total_rows = 0
    per = {}
    for f in incs:
        sym = f[:-len("__income.json")]
        mi, di = rows_of(os.path.join(FIN, f))
        if not mi or not di.get("periods"):
            continue
        mb, bd = rows_of(os.path.join(FIN, sym + "__balance.json"))
        periods = di["periods"]
        bperiods = (bd or {}).get("periods") or []
        counts = {}

        def bindex(lbl):
            # Join the BALANCE file by PERIOD LABEL, never by array position.
            # The two files can carry different period lists (SHP.JO's balance
            # runs FY2026/FY2025 while its income statement is FY2025 only), so
            # pairing column 0 with column 0 multiplies one year's profit by
            # another year's equity and prints a confident wrong ratio.
            k = str(lbl).strip().upper().replace("FY", "").strip()
            for j, bp in enumerate(bperiods):
                if str(bp).strip().upper().replace("FY", "").strip() == k:
                    return j
            return None

        def fetch(key):
            # returns (values, index_map) for an input, honouring which file it
            # lives in. Income inputs index on the income period list; balance
            # inputs index on the income period's LABEL inside the balance list.
            if key in I_ALIAS:
                v = vals(mi, I_ALIAS[key])
                return (v, lambda i: i) if v is not None else (None, None)
            v = vals(mb, B_ALIAS[key]) if mb else None
            return (v, lambda i: bindex(periods[i])) if v is not None else (None, None)
        for label, a, b, mult, formula in RATIOS:
            va, ka = fetch(a)
            vb, kb = fetch(b)
            if va is None or vb is None:
                continue
            # A value array shorter than the period list used to abort the whole
            # ratio, so a statement whose balance row carried 3 values against a
            # 5 period list got NO ratio at all, even for the periods where both
            # inputs exist. Derive per PERIOD instead: an index with both inputs
            # present is arithmetic the panel can display, and an index missing
            # one input stays a dash.
            out = []
            for i in range(len(periods)):
                xi, yi = ka(i), kb(i)
                x = va[xi] if xi is not None and xi < len(va) else None
                y = vb[yi] if yi is not None and yi < len(vb) else None
                if x is None or y is None:
                    out.append(None); continue
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    out.append(None); continue
                y = float(y)
                # EVERY denominator must be positive. This used to check only
                # equity and revenue, so a negative Total Assets (a parse error)
                # sailed through and produced SEPLAT ROA of -13235% and +5247%.
                if y <= 0:
                    out.append(None); continue          # meaningless denominator
                val = round(float(x) / y * mult, 2)
                cap = CEILING.get(label)
                if cap is not None and abs(val) > cap:
                    out.append(None)          # input is bad; withhold the ratio
                else:
                    out.append(val)
            if not any(v is not None for v in out):
                continue
            # replace an existing derived row of the same label, never a filed one
            existing = mi.get(label.lower())
            if existing and not existing.get("derived"):
                continue
            newrow = {"label": label, "values": out, "derived": True, "derivedFrom": formula}
            if existing:
                existing.update(newrow)
            else:
                di.setdefault("rows", []).append(newrow)
                mi[label.lower()] = newrow
            counts[label] = counts.get(label, 0) + sum(1 for v in out if v is not None)
        if counts:
            written += 1
            total_rows += sum(counts.values())
            for k, v in counts.items():
                per[k] = per.get(k, 0) + v
            if not DRY:
                di.setdefault("derivation", {})["ratios"] = "derive_ratios.py"
                with open(os.path.join(FIN, f), "w", encoding="utf-8") as fh:
                    json.dump(di, fh, ensure_ascii=False, indent=1)
    print(f"income statements scanned: {len(incs)}")
    print(f"  statements gaining ratios: {written}")
    for k in sorted(per, key=lambda x: -per[x]):
        print(f"    {per[k]:5} values  {k}")
    print(f"  TOTAL ratio values: {total_rows}")
    print("  (dry run)" if DRY else "  written")


if __name__ == "__main__":
    main()
