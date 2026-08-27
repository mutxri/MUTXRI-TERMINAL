#!/usr/bin/env python3
"""jse_extract.py - extract headline financial figures from JSE AFS PDFs.

Parses the primary statements (comprehensive income, financial position,
cash flows) from the official JSE annual financial statement PDFs.
Figures are in Rm (ZAR millions) unless the statement says otherwise.

Usage: python jse_extract.py <pdf_path>  -> prints JSON
"""
import json, os, re, sys
from pypdf import PdfReader

SCALE = {"Rm": 1e6, "R'm": 1e6, "Rm'": 1e6, "R000": 1e3, "R'000": 1e3,
         "R000'": 1e3, "R": 1, "R'": 1}

def num(s):
    """'25 602 24 903' -> 25602.0 (FIRST number only - current year).
    '(12 957)' -> -12957.0 ; '–' -> None"""
    s = s.replace("’", "")
    neg = s.strip().startswith("(")
    # Take the leading number token (supporting decimals); fuse FOLLOWING
    # 3-digit tokens as thousands.
    # "32,183 33,598" -> 32183 ; "700.0 700.0" -> 700.0 ; "25 602 24 903" -> 25602
    groups = re.findall(r"\d[\d.,]*", s)
    if not groups:
        return None
    first = groups[0].replace(",", "")
    parts = [first]
    total = len(first.replace(".", ""))
    for g in groups[1:]:
        digits = g.replace(",", "")
        if "." in digits or len(digits.replace(".", "")) != 3 or total + 3 > 7:
            break
        parts.append(digits)
        total += 3
    if not parts:
        return None
    raw = "".join(parts)
    try:
        v = float(raw)
        return -v if neg else v
    except ValueError:
        return None

def find_scale(page_text):
    """Detect the units line (e.g. 'Rm', 'R'000') in a statement page."""
    m = re.search(r"\bR[’']?0*,?0*0*\b|Rm|R[’']000|R000", page_text)
    return "Rm" if ("Rm" in page_text) else ("R'000" if "R'000" in page_text else ("R000" if "R000" in page_text else "Rm"))

def extract_statement(reader, label_patterns, line_patterns, max_pages=250):
    """Find the statement page with the MOST matched figures and pull the
    line items. Handles both 'Label 25 602 24 903' and 'Label 19 32,183 33,598'
    (with note reference). Notes/reference pages that mention the labels but
    hold no real figures are skipped."""
    best = {}
    best_pno = None
    for pno in range(min(max_pages, len(reader.pages))):
        txt = reader.pages[pno].extract_text() or ""
        # normalize tabs and runs of spaces (JSE AFS use tab-separated columns)
        txt = re.sub(r"[\t ]+", " ", txt)
        tl = txt.lower()
        # label patterns are REGEXES (e.g. "statement[s]? of profit or loss")
        if not all(re.search(p, tl) for p in label_patterns):
            continue
        scale = find_scale(txt)
        scale_mult = SCALE.get(scale, 1e6)
        out = {}
        for canon, pats in line_patterns.items():
            for pat in pats:
                # optional note-reference token (1-2 digits) after the label
                m = re.search(pat + r"\s+(?:(\d{1,2})\s+)?([\d,()\s.–-]+)", txt, re.I)
                if m:
                    v = num(m.group(2))
                    # if we skipped a note-ref token, verify the captured number
                    # is plausibly larger than the skipped token (a note ref is
                    # 1-2 digits, real figures are usually 3+ digits). If the
                    # skipped token was actually the start of the number
                    # ("2 239 479"), the capture would be tiny - retry without
                    # the skip.
                    if m.group(1) is not None:
                        # re-parse including the skipped token: if that yields a
                        # LARGER number, the "note ref" was really the first
                        # digit of the figure ("2 239 479" not "2" + "239 479")
                        v2 = num(m.group(1) + " " + (m.group(2) or "").strip())
                        if v2 is not None and abs(v2) > abs(v or 0):
                            v = v2
                    if v is not None:
                        out[canon] = {"label": m.group(0).strip().split("\n")[0][:80],
                                      "value": v, "unit": scale, "mult": scale_mult}
                        break
        if len(out) > len(best):
            best = out
            best_pno = pno
        # a page with 3+ real figures is certainly the statement - stop early
        if len(out) >= 3:
            return out, pno
    return best, best_pno

# pattern sets (first match wins per canonical key) - LABEL-ONLY regexes;
# extract_statement appends the value capture. Matches the JSE AFS format
# "Label [note] 25 602 24 903" (label + current year + prior year).
INCOME_PATTERNS = {
    "revenue": [r"Total income", r"Revenue", r"Turnover", r"Net interest income"],
    "net_interest_income": [r"Net interest income"],
    "profit_after_tax": [r"Profit for the (?:reporting )?period", r"Profit for the year", r"Net profit"],
    "profit_before_tax": [r"Profit before (?:tax|taxation)"],
    "operating_profit": [r"Operating income before operating expenditure", r"Operating profit"],
}
BALANCE_PATTERNS = {
    "total_assets": [r"Total assets", r"Total equity and liabilities"],
    "total_equity": [r"Total equity"],
}
CASHFLOW_PATTERNS = {
    "operating_cash_flow": [r"Net cash (?:flows )?from operating activities", r"Cash flows from operating activities"],
}

def extract(pdf_path, company=None):
    reader = PdfReader(pdf_path)
    result = {"company": company, "pages": len(reader.pages)}
    inc, pno = extract_statement(reader, [r"statement[s]? of profit or loss"], INCOME_PATTERNS)
    if inc:
        result["income"] = inc
        result["income_page"] = pno
    bal, pno2 = extract_statement(reader, ["statement of financial position"], BALANCE_PATTERNS)
    if bal:
        result["balance"] = bal
        result["balance_page"] = pno2
    cf, pno3 = extract_statement(reader, ["statement of cash flows"], CASHFLOW_PATTERNS)
    if cf:
        result["cashflow"] = cf
        result["cashflow_page"] = pno3
    return result

if __name__ == "__main__":
    path = sys.argv[1]
    company = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(path)
    res = extract(path, company)
    print(json.dumps(res, ensure_ascii=False, indent=1))
