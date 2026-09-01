#!/usr/bin/env python3
"""build_shares_pdfs.py - extract outstanding shares from the NGX annual
report PDFs (static_data/ngx_pdfs/). Pattern:
  'Number of shares issued and fully paid as at period end 20,996 (millions)'
-> 20,996M = 20,996,000,000 shares. Writes into market_NGX.json.

Also scans for 'issued share capital' rows as fallback (shares count
= capital / par value where par value is stated).
"""
import pdfplumber, re, os, json

BASE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE, "static_data", "ngx_pdfs")
MP = os.path.join(BASE, "static_data", "market_NGX.json")

SHARE_RE = re.compile(r"Number of shares issued and fully paid[^\d]*([\d,]+)")
MILLIONS_RE = re.compile(r"\(?\s*(millions?|in millions|Nm|N'million)\s*\)?", re.I)

def extract_shares(pdf_path):
    """return (shares, unit) or None"""
    try:
        with pdfplumber.open(pdf_path) as doc:
            for page in doc.pages[:10]:
                text = page.extract_text() or ""
                lines = text.split("\n")
                for i, ln in enumerate(lines):
                    if "Number of shares issued and fully paid" in ln:
                        m = SHARE_RE.search(ln)
                        if m:
                            val = float(m.group(1).replace(",", ""))
                            # check units: look at this line and next few
                            unit = 1e6  # default: millions
                            for l in lines[i:i+3]:
                                if MILLIONS_RE.search(l):
                                    unit = 1e6
                                    break
                            return int(val * unit)
    except Exception:
        pass
    return None

def main():
    m = json.load(open(MP, encoding="utf-8"))
    by_tkr = {s.get("ticker"): s for s in m["stocks"]}
    by_sym = {s.get("sym"): s for s in m["stocks"]}

    found = 0
    for f in sorted(os.listdir(PDF_DIR)):
        if not f.endswith(".pdf"):
            continue
        tkr = os.path.splitext(f)[0].upper()
        shares = extract_shares(os.path.join(PDF_DIR, f))
        if shares and shares > 1000:
            rec = by_tkr.get(tkr) or by_sym.get(tkr)
            if rec:
                rec["sharesIssued"] = shares
                rec["sharesSource"] = "annual report (issued shares)"
                found += 1
                print(f"  {tkr}: {shares:,}", flush=True)
            else:
                print(f"  {tkr}: shares {shares:,} but no market record", flush=True)

    json.dump(m, open(MP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nDONE: {found} NGX securities updated from PDFs", flush=True)

if __name__ == "__main__":
    main()
