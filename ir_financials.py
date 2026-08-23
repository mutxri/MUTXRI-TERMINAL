#!/usr/bin/env python3
"""ir_financials.py - extract financial statements from company IR PDFs.
Pipeline:
  1. discover_ir(company) -> IR page URL (via search engine / known patterns)
  2. find_statement_pdf(ir_url) -> financial-statement PDF URL
  3. parse_pdf_statements(pdf_bytes) -> {income, balance, cashflow} key figures

Honest: only returns figures that are actually in the PDF. Never invents.
"""
import urllib.request, urllib.parse, io, re, json

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}

def http_get(url, timeout=40, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8", "ignore")

def discover_ir(company, exchange):
    """Find a company's investor relations page. Tries known patterns then search."""
    q = urllib.parse.quote(f"{company} {exchange} investor relations annual report")
    try:
        # use DuckDuckGo HTML (no key needed)
        t = http_get(f"https://html.duckduckgo.com/html/?q={q}", timeout=25)
        links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', t)
        # decode ddg redirect
        out = []
        for l in links[:6]:
            m = re.search(r'uddg=([^&]+)', l)
            out.append(urllib.parse.unquote(m.group(1)) if m else l)
        return out
    except Exception as e:
        return [f"ERR {e}"]

def find_statement_pdf(ir_url):
    """From an IR page, find the financial-statement PDF (signed financials / annual report)."""
    try:
        t = http_get(ir_url, timeout=30)
    except Exception:
        return None
    # collect candidate links: PDFs named financials/statement/report/result
    links = re.findall(r'href="([^"]+\.pdf[^"]*)"', t, re.I)
    cands = []
    for l in links:
        ll = l.lower()
        if any(k in ll for k in ["financial", "statement", "annual-report", "annual_report", "signed", "result"]):
            cands.append(l)
    if not cands:
        cands = links
    # prefer the most recent / signed financials
    for pref in ["signed", "financial", "annual"]:
        for l in cands:
            if pref in l.lower():
                return l if l.startswith("http") else urllib.parse.urljoin(ir_url, l)
    if cands:
        return cands[0] if cands[0].startswith("http") else urllib.parse.urljoin(ir_url, cands[0])
    return None

def _page_lines(page):
    """Extract [(x, y, text)] via pypdf visitor, group into lines by y.
    Returns list of (x0, text) rows sorted top-to-bottom."""
    items = []
    def visitor(text, cm, tm, font_dict, font_size):
        x = tm[4]; y = tm[5]
        if text.strip():
            items.append((x, y, text))
    page.extract_text(visitor_text=visitor)
    lines = {}
    for x, y, t in items:
        key = round(y, 1)
        lines.setdefault(key, []).append((x, t))
    out = []
    for y in sorted(lines, reverse=True):
        row = sorted(lines[y])
        line = "".join(t for x, t in row)
        out.append((row[0][0], y, line))
    return out


def parse_pdf_statements(data):
    """Parse statement text from a financial PDF using positional layout.
    Labels sit at x<320; value columns at x~390 (2025/current) and x~470 (prior).
    Returns real figures only."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    rows_by_page = []
    for p in reader.pages:
        try:
            rows_by_page.append(_page_lines(p))
        except Exception:
            rows_by_page.append([])

    # locate statement pages: income (has 'Revenue'), balance (has 'TOTAL ASSETS'),
    # cash flow (has 'Net cash flows from operating')
    def find_page(substr):
        for i, rows in enumerate(rows_by_page):
            for x, y, line in rows:
                if substr.lower() in line.lower():
                    return i
        return -1

    def row_value(rows, label, col="current", exact=False):
        """Find the row whose label matches, return the number in the value column.
        Falls back to scanning the rows below the label (label/value split rows)."""
        for ri, (x, y, line) in enumerate(rows):
            ll = line.lower()
            if label.lower() in ll:
                # try same-row numbers first
                nums = re.findall(r"\(?[\d,]+\.?\d*\)?", line)
                vals = []
                for raw in nums:
                    n = raw.replace(",", "").replace("(", "-").replace(")", "")
                    try:
                        v = float(n)
                    except ValueError:
                        continue
                    vals.append((raw, v))
                big = [v for r, v in vals if abs(v) >= 1 and not (v == int(v) and abs(v) < 50 and len(r.replace(',', '')) <= 2)]
                if big:
                    return big[0] if col == "current" else big[-1]
                # label and value on separate rows: scan the next 12 rows
                # for the first value-column number (x > 330)
                for rr in rows[ri+1:ri+13]:
                    rrx, rry, rrline = rr
                    if rrx > 330:
                        nums = re.findall(r"\(?[\d,]+\.?\d*\)?", rrline)
                        for raw in nums:
                            n = raw.replace(",", "").replace("(", "-").replace(")", "")
                            try:
                                v = float(n)
                            except ValueError:
                                continue
                            if abs(v) >= 1 and not (v == int(v) and abs(v) < 50 and len(raw.replace(',', '')) <= 2):
                                return v
                return None
        return None

    out = {}

    # income statement
    # PASS 1: pages with 'Consolidated statement of profit or loss' (preferred)
    # PASS 2: any 'statement of profit or loss' page with a Revenue row
    def _inc_candidates():
        for i, rows in enumerate(rows_by_page):
            for ri, (x, y, line) in enumerate(rows):
                ll = line.lower()
                if "statement of profit or loss" in ll or "statement of comprehensive income" in ll:
                    nxt = " ".join(rr[2].lower() for rr in rows[ri:ri+3])
                    if "(continued" not in nxt and any("revenue" in rr[2].lower() for rr in rows):
                        yield i, ll
    best_inc = -1
    for i, ll in _inc_candidates():
        if "consolidated" in ll:
            best_inc = i
    if best_inc < 0:
        for i, ll in _inc_candidates():
            best_inc = i
    last_inc = best_inc
    if last_inc >= 0:
        rows = rows_by_page[last_inc]
        out["revenue"] = row_value(rows, "Revenue")
        out["gross_profit"] = row_value(rows, "Gross profit")
        out["operating_profit"] = row_value(rows, "Operating")
        # profit for the year: row with '(loss)/profit for the year'
        for x, y, line in rows:
            if "profit for the year" in line.lower() and "comprehensive" not in line.lower():
                nums = re.findall(r"\(?[\d,]+\.?\d*\)?", line)
                vals = [float(n.replace(",", "").replace("(", "-").replace(")", "")) for n in nums]
                vals = [v for v in vals if abs(v) >= 1 and not (v == int(v) and abs(v) < 50)]
                if vals:
                    out["profit_after_tax"] = vals[0]
                    break

    # balance sheet
    # PASS 1: 'Consolidated statement of financial position' with TOTAL ASSETS
    # PASS 2: any 'statement of financial position' page with TOTAL ASSETS
    def _bs_candidates():
        for i, rows in enumerate(rows_by_page):
            for ri, (x, y, line) in enumerate(rows):
                ll = line.lower()
                if "statement of financial position" in ll:
                    nxt = " ".join(rr[2].lower() for rr in rows[ri:ri+3])
                    if "(continued" not in nxt and any("total assets" in rr[2].lower() for rr in rows):
                        yield i, ll
    last_bs = -1
    for i, ll in _bs_candidates():
        if "consolidated" in ll:
            last_bs = i
    if last_bs < 0:
        for i, ll in _bs_candidates():
            last_bs = i
    if last_bs >= 0:
        rows = rows_by_page[last_bs]
        # TOTAL ASSETS: the largest value in the asset column (x>350) is the
        # grand total (it exceeds all component subtotals)
        def col_values(rows):
            out = []
            for x, y, line in rows:
                if x > 350:
                    nums = re.findall(r"\(?[\d,]+\.?\d*\)?", line)
                    for raw in nums:
                        digits = raw.replace(",", "").replace("(", "").replace(")", "").replace(".", "")
                        # skip concatenated year headers (7+ pure digits like 20252024)
                        if digits.isdigit() and len(digits) >= 7:
                            continue
                        n = raw.replace(",", "").replace("(", "-").replace(")", "")
                        try:
                            v = float(n)
                        except ValueError:
                            continue
                        # exclude year headers (1900-2100) and notes refs
                        if abs(v) >= 1000 and not (1900 <= abs(v) <= 2100 and v == int(v) and len(digits) <= 4):
                            out.append(v)
            return out
        cv = col_values(rows)
        pos = [v for v in cv if v > 0]
        if pos:
            out["total_assets"] = max(pos)
        out["total_liabilities"] = row_value(rows, "TOTAL LIABILITIES")
        out["cash_and_equivalents"] = row_value(rows, "Cash and bank balances")

    # cash flow
    # PASS 1: 'Consolidated statement of cash flows' with operating activities
    # PASS 2: any 'statement of cash flows' page with operating activities
    def _cf_candidates():
        for i, rows in enumerate(rows_by_page):
            for ri, (x, y, line) in enumerate(rows):
                ll = line.lower()
                if "statement of cash flows" in ll:
                    nxt = " ".join(rr[2].lower() for rr in rows[ri:ri+3])
                    if "(continued" not in nxt and any("operating activities" in rr[2].lower() for rr in rows):
                        yield i, ll
    last_cf = -1
    for i, ll in _cf_candidates():
        if "consolidated" in ll:
            last_cf = i
    if last_cf < 0:
        for i, ll in _cf_candidates():
            last_cf = i
    if last_cf >= 0:
        rows = rows_by_page[last_cf]
        out["operating_cash_flow"] = row_value(rows, "Net cash flows from operating")

    # ---- results-at-a-glance fallback: tabular format with label + values ----
    # e.g. 'Revenue  505,360  622,637' / 'Earnings after tax  (99,338)  239,853'
    if not out.get("revenue") or not out.get("profit_after_tax"):
        for rows in rows_by_page:
            has_glance = False
            for x, y, line in rows:
                ll = line.lower()
                if "results at a glance" in ll or "result at a glance" in ll:
                    has_glance = True
                    break
            if not has_glance:
                continue
            for xx, yy, ln in rows:
                m = re.match(r"^([A-Za-z][A-Za-z &/'()%-]{2,60}?)\s+\(?([\d,]+\.?\d*)\)?\s+\(?[\d,]+\.?\d*\)?\s*$", ln)
                if m:
                    lab = m.group(1).lower()
                    v = m.group(2).replace(",", "").replace("(", "-")
                    try:
                        val = float(v)
                    except ValueError:
                        continue
                    if "revenue" in lab and "revenue" not in out:
                        out["revenue"] = val
                    elif "earnings after tax" in lab or "profit after tax" in lab or "profit for the period" in lab or "profit/(loss)" in lab:
                        if "profit_after_tax" not in out:
                            out["profit_after_tax"] = val
                    elif "total assets" in lab:
                        if "total_assets" not in out:
                            out["total_assets"] = val
                    elif "total liabilities" in lab:
                        if "total_liabilities" not in out:
                            out["total_liabilities"] = val
                    elif "operating profit" in lab:
                        if "operating_profit" not in out:
                            out["operating_profit"] = val
                    elif "cash and cash equivalents" in lab or "cash and bank" in lab:
                        if "cash_and_equivalents" not in out:
                            out["cash_and_equivalents"] = val
                    elif "operating cash" in lab or "cash generated from operations" in lab:
                        if "operating_cash_flow" not in out:
                            out["operating_cash_flow"] = val
                    elif "gross profit" in lab:
                        if "gross_profit" not in out:
                            out["gross_profit"] = val
                    elif "earnings per share" in lab or "basic earnings" in lab:
                        if "eps" not in out:
                            out["eps"] = val
            break
    return {k: v for k, v in out.items() if v is not None}

if __name__ == "__main__":
    # test on KQ
    print("discover KQ IR:", discover_ir("Kenya Airways", "NSE")[:3])
