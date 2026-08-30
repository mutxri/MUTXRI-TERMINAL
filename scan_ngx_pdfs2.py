#!/usr/bin/env python3
"""scan_ngx_pdfs2.py - reliable share-count extraction from NGX PDFs.
Uses ONLY exact-count patterns:
  A) 'X ordinary shares of' (e.g. "2,190,382,819 ordinary shares of 50k")
  B) 'Weighted average number of ordinary shares [issued/outstanding] X'
  C) 'Number of shares issued and fully paid X (millions)' -> X*1e6
  D) 'X shares of N0.50 each' / 'X shares of 50k each'
These give the actual share count, not the capital value.
"""
import re, os, json
from pypdf import PdfReader

BASE = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE, "static_data", "ngx_pdfs")
OUT = os.path.join(BASE, "scan_results2.json")

PATS = [
    ("ordshares", re.compile(r"([\d,]{5,})\s+ordinary shares", re.I)),
    ("wavg", re.compile(r"Weighted average number of ordinary shares (?:issued|outstanding)[^\d]*([\d,]{5,})", re.I)),
    ("numissued", re.compile(r"Number of shares issued and fully paid[^\d]*([\d,]{5,})", re.I)),
    ("sharesof", re.compile(r"([\d,]{5,})\s+shares?\s+of\s+(?:N|NGN|k)?0?\.?\d+", re.I)),
]

def scan_one(path, max_pages=40):
    try:
        reader = PdfReader(path)
        n = len(reader.pages)
        for pi in range(min(n, max_pages)):
            try:
                text = reader.pages[pi].extract_text() or ""
            except Exception:
                continue
            for name, pat in PATS:
                m = pat.search(text)
                if m:
                    try:
                        val = int(m.group(1).replace(",", ""))
                        # sanity: shares count must be >= 100k (companies have at least that)
                        if val >= 100000:
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
    json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1)
    with_data = {k: v for k, v in results.items() if v[0] and v[0] != "ERR"}
    print(f"DONE: {len(results)} scanned, {len(with_data)} with reliable share counts", flush=True)
    for f, (typ, val, pi, n) in sorted(with_data.items()):
        print(f"  {f}: {typ} {val:,} (p{pi}/{n})", flush=True)

if __name__ == "__main__":
    main()
