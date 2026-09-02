#!/usr/bin/env python3
"""Parse an NGX audited annual financial statement PDF (doclib.ngxgroup.com)
into the MUTXRI terminal financials JSON format.

Usage:
    python ngx_parse.py <pdf_path> <symbol> <name> <out_dir>

Strategy: scan every page except notes pages ("Notes to the ...") in order.
For each wanted row label, take the occurrence with the MOST values (a 5-year
summary beats a 2-column statement; group columns are the first 2 of a
Group+Company layout). Units are detected per page ('000 / millions).
Values are stored in full Naira; EPS stays in Naira.
Writes <symbol>__income.json / __balance.json / __cashflow.json.
"""
import sys, os, re, json
import pymupdf

INC_SOURCES = [("Revenue from contracts with customers", "Revenue"), ("Revenue", "Revenue"),
               ("Total Revenue", "Revenue"), ("Total revenue", "Revenue"),
               ("Gross earnings", "Revenue"), ("Gross premium income", "Revenue"),
               ("Net premium income", "Revenue"),
               ("Cost of sales", "Cost of Sales"), ("Gross profit", "Gross Profit"),
               ("Operating profit", "Operating Profit (EBIT)"), ("Operating profit (loss)", "Operating Profit (EBIT)"),
               ("Profit before tax", "Profit Before Tax"), ("Profit before taxation", "Profit Before Tax"),
               ("Profit before income tax", "Profit Before Tax"),
               ("Profit before tax from continuing operations", "Profit Before Tax"),
               ("Profit for the year", "Net Profit"), ("Profit after tax", "Net Profit"),
               ("Net profit for the year", "Net Profit")]
BAL_SOURCES = [("Non-current assets", "Non-current assets"), ("Current assets", "Current assets"),
               ("Total assets", "Total assets"), ("Total liabilities", "Total liabilities"),
               ("Total equity", "Total equity"), ("Total Assets", "Total assets"),
               ("Total Liabilities", "Total liabilities"), ("Total Equity", "Total equity")]
CF_SOURCES = [("Net cash from operating activities", "Net Cash from Operating Activities"),
              ("Net cash used in operating activities", "Net Cash from Operating Activities"),
              ("Net cash generated from operating activities", "Net Cash from Operating Activities"),
              ("Net cash from investing activities", "Net Cash from Investing Activities"),
              ("Net cash used in investing activities", "Net Cash from Investing Activities"),
              ("Net cash from financing activities", "Net Cash from Financing Activities"),
              ("Net cash used in financing activities", "Net Cash from Financing Activities"),
              ("Net cash generated from financing activities", "Net Cash from Financing Activities"),
              ("Net (decrease)/increase in cash and cash equivalents", "Net Change in Cash"),
              ("Net increase/(decrease) in cash and cash equivalents", "Net Change in Cash")]
NUM_RE = re.compile(r"-?[\d,]+\.?\d*|\([\d,]+\)")
NOTE_RE = re.compile(r"[A-Za-z0-9()\[\].]{1,12}")


def load_pages(pdf):
    doc = pymupdf.open(pdf)
    return [doc[p].get_text() for p in range(doc.page_count)]


def page_unit(text):
    if not text:
        return 1
    if re.search(r"millions? of naira|₦\s*million|'000,000|000,000|kshs?\s*mn|kes\s*millions?|kShs Mn", text, re.I):
        return 1_000_000
    if re.search(r"₦'000|thousands? of naira|'000\b|\(000\)|kshs?\s*'?000", text, re.I):
        return 1_000
    return 1


def occurrences(text, labels):
    """First occurrence per label per page: {label: [(page_idx, unit, values), ...]}
    `labels` items are (source_label, output_label) tuples."""
    lines = text.split("\n")
    out = {}
    for src, _out in labels:
        for i, ln in enumerate(lines):
            if ln.strip() == src:
                j = i + 1
                while j < len(lines) and NOTE_RE.fullmatch(lines[j].strip()):
                    j += 1
                nums = []
                while j < len(lines):
                    x = lines[j].strip()
                    if NUM_RE.fullmatch(x):
                        nums.append(float(x.replace(",", "").replace("(", "-").replace(")", "")))
                        j += 1
                    elif x in ("", "-", "–", "—"):
                        j += 1
                    else:
                        break
                if nums:
                    out[src] = nums
                break
    return out


def find_eps(corpus):
    for marker in ["Basic and diluted (Naira)", "Basic and diluted (Kobo)", "Basic earnings per share",
                   "Basic earnings per share (Naira)", "Basic earnings per share (Kobo)",
                   "Basic and diluted earnings per share (EPS)", "Basic and diluted earnings per share"]:
        i = corpus.find(marker)
        if i >= 0:
            seg = corpus[i:i + 160]
            nums = [float(x) for x in re.findall(r"\d+\.\d+", seg)]
            return nums[:2] if len(nums) >= 2 else (nums[:1] if nums else None)
    return None


def main():
    pdf, symbol, name, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    pages = [p for p in load_pages(pdf) if "Notes to the" not in p]
    corpus = "\n".join(pages)

    # gather per-label candidates across pages: {label: [(page_idx, unit, values)]}
    cand = {}
    for idx, page in enumerate(pages):
        unit = page_unit(page)
        for lab, vals in occurrences(page, INC_SOURCES + BAL_SOURCES + CF_SOURCES).items():
            cand.setdefault(lab, []).append((idx, unit, vals))

    def pick(sources):
        """Best (unit, values) for an output row across mapped source labels."""
        best = None
        for src_lab, out_lab in sources:
            for idx, unit, vals in cand.get(src_lab, []):
                if best is None or len(vals) > len(best[1]):
                    best = (unit, vals, idx, out_lab)
        return best

    def final_vals(unit_vals):
        unit, vals, idx, out_lab = unit_vals
        v = vals[:5] if len(vals) >= 5 else vals[:2]
        return [None if x is None else round(x * unit, 2) for x in v], idx, out_lab

    def page_years(page_idx, n):
        t = pages[page_idx]
        ys = sorted({m for m in re.findall(r"20\d\d", t) if 1990 <= int(m) <= 2040}, reverse=True)
        return ["FY" + y for y in ys[:n]] if ys else ["FY2025", "FY2024"][:n]

    def build_rows(sources):
        # For each output label, take the occurrence with the most values.
        order, out = [], {}
        for sl, ol in sources:
            if ol not in out:
                out[ol] = None
                order.append(ol)
            for _idx, unit, vals in cand.get(sl, []):
                if out[ol] is None or len(vals) > len(out[ol][1]):
                    out[ol] = (unit, vals)
        rows = []
        for ol in order:
            if out[ol] is None:
                continue
            unit, vals = out[ol]
            v = vals[:5] if len(vals) >= 5 else vals[:2]
            rows.append({"label": ol, "values": [round(x * unit, 2) for x in v]})
        return rows

    inc_rows = build_rows(INC_SOURCES)
    eps = find_eps(corpus)
    if eps:
        inc_rows.append({"label": "EPS", "values": [round(v, 4) for v in eps]})
    bal_rows = build_rows(BAL_SOURCES)
    cf_rows = build_rows(CF_SOURCES)

    # periods: from the page of the widest candidate occurrence (5-year summary preferred).
    # A 4-value row is Group+Company for ONE year-pair (2 periods); >=5 values = multi-year summary.
    max_cand = 0
    widest_idx = None
    for sl, _ol in INC_SOURCES + BAL_SOURCES + CF_SOURCES:
        if sl in cand:
            for e in cand[sl]:
                if len(e[2]) > max_cand:
                    max_cand = len(e[2])
                    widest_idx = e[0]
    n_periods = min(max_cand, 5) if max_cand >= 5 else min(max_cand, 2)
    periods = []
    if widest_idx is not None:
        if widest_idx is not None:
            pg = pages[widest_idx]
            # prefer column-header years ("31 December 2025"); fall back to any year mention
            hdr = {int(m) for m in re.findall(
                r"(?:31|30|1)\s+(?:December|Dec|March|Mar|January|Jan|February|Feb|June|Jun|July|Jul|September|Sep|October|Oct|November|Nov|April|Apr|May|August|Aug)\s+(20\d\d)",
                pg, re.I)}
            ys = sorted({int(m) for m in re.findall(r"20\d\d", pg) if 1990 <= int(m) <= 2040} - set(), reverse=True)
            if len(hdr) >= n_periods:
                ys = sorted(hdr, reverse=True)
            periods = ["FY" + str(y) for y in ys[:n_periods]] if ys else []
    if not periods or len(periods) < n_periods:
        base = int(periods[0][2:]) if periods else 2026
        periods = ["FY" + str(base - i) for i in range(n_periods)]

    def build_file(stmt, stmt_title, rows):
        cur = "KES" if re.search(r"\bkshs?\b|\bkes\b|kenyan shillings?", "\n".join(pages), re.I) else "NGN"
        src = "NSE (nse.co.ke)" if cur == "KES" else "NGX (doclib.ngxgroup.com)"
        return {
            "ticker": symbol, "name": name, "currency": cur, "source": src,
            "asOf": (periods[0] if periods else ""), "statement": stmt, "statementTitle": stmt_title,
            "period": "annual", "available": len(rows) > 0, "periods": periods, "rows": rows,
        }

    os.makedirs(out_dir, exist_ok=True)
    wrote = 0
    for stmt, title, rows in [("income", "Income Statement", inc_rows),
                              ("balance", "Balance Sheet", bal_rows),
                              ("cashflow", "Cash Flow Statement", cf_rows)]:
        if rows:
            with open(os.path.join(out_dir, f"{symbol}__{stmt}.json"), "w", encoding="utf-8") as f:
                json.dump(build_file(stmt, title, rows), f, ensure_ascii=False)
            wrote += 1
    print(f"{symbol}: wrote {wrote}, periods={periods}, inc={len(inc_rows)} bal={len(bal_rows)} cf={len(cf_rows)}")
    sys.exit(0 if wrote else 1)


if __name__ == "__main__":
    main()
