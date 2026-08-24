#!/usr/bin/env python3
"""finish_statements_pdf.py - extract financial statement figures from the 14
PDF-only AF documents (Legend, PZ, EkoCorp, African Alliance, NIDF, Uchumi,
Car&General, Kurwitu, Total, AMA, Kenya Airways, Sasini, Eveready, Sanlam).

AF document pages embed a PDF; we fetch it, extract text with pymupdf, then
pull the key income-statement figures via the same number+scale regexes used
by extract_statements.py.
"""
import json, re, os, sys, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}

MISSING = [
    ("NGX:ng-legend", "https://africanfinancials.com/document/ng-legend-2026-ir-hy/"),
    ("NGX:ng-pz", "https://africanfinancials.com/document/ng-pz-2026-ir-hy/"),
    ("NGX:ng-ekocor", "https://africanfinancials.com/document/ng-ekocor-2021-ir-hy/"),
    ("NGX:ng-afrins", "https://africanfinancials.com/document/ng-afrins-2022-ir-hy/"),
    ("NGX:ng-nidf", "https://africanfinancials.com/document/ng-nidf-2026-ir-hy/"),
    ("NSE:ke-uchm", "https://africanfinancials.com/document/ke-uchm-2018-ir-hy/"),
    ("NSE:ke-cgen", "https://africanfinancials.com/document/ke-cgen-2024-ir-hy/"),
    ("NSE:ke-kurv", "https://africanfinancials.com/document/ke-kurv-2019-ir-hy/"),
    ("NSE:ke-totl", "https://africanfinancials.com/document/ke-totl-2024-ir-hy/"),
    ("NSE:ke-orch", "https://africanfinancials.com/document/ke-orch-2022-ab-00/"),
    ("NSE:ke-kq", "https://africanfinancials.com/document/ke-kq-2023-ir-hy/"),
    ("NSE:ke-sasn", "https://africanfinancials.com/document/ke-sasn-2026-ir-hy/"),
    ("NSE:ke-evrd", "https://africanfinancials.com/document/ke-evrd-2024-ir-hy/"),
    ("NSE:ke-slam", "https://africanfinancials.com/document/ke-slam-2024-ir-hy/"),
]

def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def find_pdf_url(html):
    """AF document pages embed the PDF via a Google Drive iframe, or a direct
    <a href=...pdf> link."""
    # Google Drive iframe: <iframe src="https://drive.google.com/file/d/ID/preview">
    m = re.search(r'<iframe[^>]*src=["\'](https://drive\.google\.com/file/d/([^/]+)/preview)["\']', html)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(2)}"
    # direct pdf links
    m = re.search(r'(?:src|href)\s*=\s*["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I)
    if m:
        u = m.group(1)
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            u = "https://africanfinancials.com" + u
        return u
    # og:url / pdf embed link
    m = re.search(r'content\s*=\s*["\']([^"\']*\.pdf[^"\']*)["\']', html, re.I)
    return m.group(1) if m else None

def parse_figures(text):
    """Pull income-statement figures: Revenue, Gross Profit, Operating Profit,
    Profit After Tax. Returns dict or None."""
    out = {}
    def scale(v, unit):
        v = float(v.replace(",", ""))
        if unit in ("billion", "bn", "bln"): return v * 1e9
        if unit in ("million", "mn", "m"): return v * 1e6
        if unit in ("trillion", "tn"): return v * 1e12
        return v  # assume raw units (millions in most AF PDFs)

    patterns = {
        "revenue": r"(?:Revenue|Turnover|Gross earnings)[^\d]{0,40}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
        "gross_profit": r"Gross (?:profit|income)[^\d]{0,40}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
        "operating_profit": r"(?:Operating profit|Profit from operations|EBIT)[^\d]{0,40}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
        "profit_after_tax": r"(?:Profit (?:after tax|for the year|for the period)|Net profit|PAT)[^\d]{0,40}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            try:
                out[key] = scale(m.group(1), (m.group(2) or "").lower())
            except ValueError:
                pass
    return out or None

def main():
    try:
        from pypdf import PdfReader  # already installed
    except ImportError:
        try:
            import fitz as _  # pymupdf fallback
        except ImportError:
            print("no pdf lib available")
            return

    results = {}
    os.makedirs(os.path.join(BASE, "pdf_statements"), exist_ok=True)
    for i, (key, doc_url) in enumerate(MISSING):
        slug = key.split(":")[-1]
        print(f"[{i+1}/{len(MISSING)}] {key} ...")
        try:
            html = fetch(doc_url).decode(errors="replace")
            pdf_url = find_pdf_url(html)
            if not pdf_url:
                print(f"    no PDF link found")
                results[key] = {"error": "no pdf link"}
                continue
            pdf_bytes = fetch(pdf_url, timeout=60)
            pdf_path = os.path.join(BASE, "pdf_statements", slug + ".pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            # extract text
            try:
                reader = PdfReader(pdf_path)
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            except NameError:
                doc = fitz.open(pdf_path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            figs = parse_figures(text)
            if figs:
                results[key] = {"url": doc_url, "pdf": pdf_url, **figs}
                print(f"    OK: {figs}")
            else:
                results[key] = {"url": doc_url, "pdf": pdf_url, "error": "no figures parsed (scanned?)"}
                print(f"    no figures (len={len(text)})")
        except Exception as e:
            results[key] = {"error": str(e)[:80]}
            print(f"    FAIL: {str(e)[:80]}")

    with open(os.path.join(BASE, "pdf_statements", "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("\nDONE. results in pdf_statements/results.json")

if __name__ == "__main__":
    main()
