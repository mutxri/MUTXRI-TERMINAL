#!/usr/bin/env python3
"""build_af_financials.py - materialise NGX/NSE financial statements for the
static terminal from the AfricanFinancials data already in fundamentals.json.

The financials panel reads static_data/financials/<TICKER>__<statement>.json.
Those files only ever existed for JSE and EGX (built from Yahoo), so the panel
was dead on NGX and NSE - 136 NGX tickers sat in financials_index.json with no
file behind any of them, and the /api/financials fallback returns
available=false for those exchanges too.

fundamentals.json already carries the real statements: a period ("HY"), a year,
the AfricanFinancials document URL, and the line items. This writes them out in
the shape the panel expects. Fields AfricanFinancials does not publish stay
absent so the panel renders a dash - never a fabricated number.
"""
import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(BASE, "static_data")
OUT = os.path.join(S, "financials")
os.makedirs(OUT, exist_ok=True)

CCY = {"NGX": "NGN", "NSE": "KES", "JSE": "ZAR", "EGX": "EGP"}

# panel schema label -> the AfricanFinancials field that fills it
STATEMENTS = {
    "income": ("Income Statement", [
        ("Revenue", "revenue"),
        ("Gross Profit", "gross_profit"),
        ("Operating Profit (EBIT)", "operating_profit"),
        ("Profit Before Tax", "profit_before_tax"),
        ("Net Profit", "profit_after_tax"),
        ("EPS", "eps"),
    ]),
    "balance": ("Balance Sheet", [
        ("Cash & Equivalents", "cash_and_equivalents"),
        ("Total Assets", "total_assets"),
        ("Total Liabilities", "total_liabilities"),
        ("Total Equity", "total_equity"),
    ]),
    "cashflow": ("Cash Flow Statement", [
        ("Operating Cash Flow", "operating_cash_flow"),
        ("Investing Cash Flow", "investing_cash_flow"),
        ("Financing Cash Flow", "financing_cash_flow"),
    ]),
}
ALIASES = {"total_equity": ("total_equity", "shareholders_equity")}


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def resolve(rec, universe, _names={}):
    """AfricanFinancials slugs are truncated ("ng-zenith", "ng-mtn", "ng-buac")
    while the board uses the full ticker (ZENITHBANK, MTNN, BUACEMENT), so an
    exact lookup misses most of the majors. Fall back to a UNIQUE prefix match,
    then to the company name - ambiguity is always rejected rather than guessed."""
    if not _names:
        for t, (ex, nm) in universe.items():
            _names.setdefault(norm(nm), set()).add(t)

    cand = (rec.get("ticker") or "").upper()
    if cand in universe:
        return cand
    slug = norm((rec.get("slug") or "").split("-", 1)[-1])
    if slug in universe:
        return slug
    if slug:
        hits = [t for t in universe if t.startswith(slug)]
        if len(hits) == 1:
            return hits[0]
        hits = [t for t in universe if slug.startswith(t) and len(t) >= 4]
        if len(hits) == 1:
            return hits[0]
    nm = norm(rec.get("name"))
    if nm:
        exact = _names.get(nm)
        if exact and len(exact) == 1:
            return next(iter(exact))
        hits = [t for t, (ex, cname) in universe.items()
                if norm(cname).startswith(nm) and len(nm) >= 5]
        if len(hits) == 1:
            return hits[0]
    return None


def clean(field, v):
    """Reject values that are obviously not the figure they claim to be.
    Equity Bank's profit_after_tax arrives as 2026.0 - that is the report year
    that leaked into the number, not KES 2,026."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = float(v.replace(",", ""))
        except ValueError:
            return None
    if not isinstance(v, (int, float)):
        return None
    if field == "eps":
        return float(v)
    # a report year that leaked into a money field (Equity Bank's
    # profit_after_tax arrives as 2026.0, not KES 2,026)
    if 1900 <= v <= 2100 and float(v).is_integer():
        return None
    # NGN/KES statements are published in thousands at minimum; anything under
    # a thousand is a margin or a ratio that landed in the wrong field
    # (Airtel Africa's operating_profit arrives as 40.7)
    if abs(v) < 1000:
        return None
    return float(v)


def period_label(st):
    p = (st.get("period") or "").upper()
    y = str(st.get("year") or "").strip()
    if not y:
        return "Latest"
    if p in ("FY", "AR", ""):
        return f"FY{y}"
    return f"{p} {y}"


def main():
    fu = json.load(open(os.path.join(BASE, "fundamentals.json"), encoding="utf-8"))["companies"]
    index_path = os.path.join(S, "financials_index.json")
    index = json.load(open(index_path, encoding="utf-8")) if os.path.exists(index_path) else {}

    # only ship a ticker the terminal actually lists
    universe = {}
    for ex in ("NGX", "NSE"):
        p = os.path.join(S, f"market_{ex}.json")
        if not os.path.exists(p):
            continue
        for s in json.load(open(p, encoding="utf-8")).get("stocks", []):
            t = (s.get("ticker") or s.get("sym") or "").upper()
            if t:
                universe[t] = (ex, s.get("name"))

    written = {"income": 0, "balance": 0, "cashflow": 0}
    covered, skipped_unknown, no_numbers = set(), 0, 0

    for key, rec in fu.items():
        ex = key.split(":")[0].upper()
        if ex not in ("NGX", "NSE"):
            continue
        st = rec.get("statements") or {}
        data = st.get("data") or {}
        ticker = resolve(rec, universe)
        if not ticker:
            skipped_unknown += 1
            continue

        label = period_label(st)
        name = rec.get("name") or universe[ticker][1]
        src_url = st.get("url") or ""
        reports = [d for d in (rec.get("documents") or []) if d.get("url")][:12]
        wrote_any = False

        for stmt, (title, fields) in STATEMENTS.items():
            rows = []
            for lbl, field in fields:
                v = None
                for f in ALIASES.get(field, (field,)):
                    v = clean(f, data.get(f))
                    if v is not None:
                        break
                rows.append({"label": lbl, "values": [v]})
            if not any(r["values"][0] is not None for r in rows):
                continue
            out = {
                "ticker": ticker, "name": name, "currency": CCY.get(ex),
                "source": "African Financials", "asOf": label,
                "statement": stmt, "statementTitle": title,
                "period": "interim" if not label.startswith("FY") else "annual",
                "available": True, "periods": [label], "rows": rows,
                "source_url": src_url, "reports": reports,
            }
            with open(os.path.join(OUT, f"{ticker}__{stmt}.json"), "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, allow_nan=False)
            written[stmt] += 1
            wrote_any = True

        if wrote_any:
            covered.add(ticker)
            index[ticker] = {"name": name, "currency": CCY.get(ex),
                             "exchange": ex, "source": "African Financials"}
        else:
            no_numbers += 1

    # drop index entries that promise statements we cannot serve - a ticker in
    # the dropdown with no file behind it is what made the panel look broken
    dropped = []
    for k in list(index):
        ex = (index[k].get("exchange") or "").upper()
        if ex in ("NGX", "NSE") and k not in covered:
            dropped.append(k)
            del index[k]
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)

    print(f"NGX/NSE statements written: income {written['income']}, "
          f"balance {written['balance']}, cashflow {written['cashflow']}")
    print(f"tickers covered: {len(covered)} | no usable numbers: {no_numbers} | "
          f"not in the listed universe: {skipped_unknown}")
    print(f"index entries dropped (promised statements with no file): {len(dropped)}")


if __name__ == "__main__":
    main()
