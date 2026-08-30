#!/usr/bin/env python3
"""scan_ngx_pdfs.py - scan all NGX PDFs for share-count disclosures.
Fast: uses pypdf text extraction (much faster than pdfplumber) and stops
at the first match per file. Writes scan results to scan_results.json."""
import re, os, json, sys
from pypdf import PdfReader

BASE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE, "static_data", "ngx_pdfs")
OUT = os.path.join(BASE, "scan_results.json")

PATTERNS = [
    ("ordinary", re.compile(r"([\d,]{7,})\s+ordinary shares", re.I)),
    ("issued", re.compile(r"Issued Share Capital[^\d]*([\d,]{7,})", re.I)),
    ("numshares", re.compile(r"Number of shares issued and fully paid[^\d]*([\d,]{7,})", re.I)),
    ("sharecapital", re.compile(r"(?:Authorised|Issued)[^\n]{0,40}share capital[^\n]*?([\d,]{7,})", re.I)),
]

def scan_one(path, max_pages=25):
    try:
        reader = PdfReader(path)
        n = len(reader.pages)
        for pi in range(min(n, max_pages)):
            try:
                text = reader.pages[pi].extract_text() or ""
            except Exception:
                continue
            for name, pat in PATTERNS:
                m = pat.search(text)
                if m:
                    try:
                        val = int(m.group(1).replace(",", ""))
                        return (name, val, pi, n)
                    except ValueError:
                        continue
        return (None, None, None, n)
    except Exception as e:
        return ("ERR", str(e)[:40], None, None)

def main():
    results = {}
    for f in sorted(os.listdir(PDF_DIR)):
        if not f.endswith(".pdf"):
            continue
        results[f] = scan_one(os.path.join(PDF_DIR, f))
        if len(results) % 20 == 0:
            print(f"  ... {len(results)} scanned", flush=True)
    json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1)
    with_data = {k: v for k, v in results.items() if v[0] and v[0] != "ERR"}
    print(f"DONE: {len(results)} scanned, {len(with_data)} with share data", flush=True)

if __name__ == "__main__":
    main()
