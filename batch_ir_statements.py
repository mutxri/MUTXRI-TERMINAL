#!/usr/bin/env python3
"""batch_ir_statements.py - extract financial statements from company IR PDFs.
For each company in fundamentals.json whose statement record is PDF-only
(format == "pdf" or empty data), download the linked PDF and parse the
statement figures with ir_financials.parse_pdf_statements.

Run: python batch_ir_statements.py [--limit N]
"""
import json, os, sys, time, urllib.request, io, re

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import ir_financials as ir

def get_pdf(url, timeout=90):
    """Download a PDF from a URL, or resolve an HTML page to its embedded PDF
    (AF document pages embed Google Drive iframes)."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if data[:5] == b"%PDF-":
        return data
    # HTML page: look for an embedded PDF / Google Drive iframe
    t = data.decode("utf-8", "ignore")
    # google drive iframe: /file/d/ID/preview
    m = re.search(r'drive\.google\.com/file/d/([^/"]+)/preview', t)
    if m:
        did = m.group(1)
        durl = f"https://drive.google.com/uc?export=download&id={did}"
        req2 = urllib.request.Request(durl, headers=UA)
        with urllib.request.urlopen(req2, timeout=timeout) as r2:
            d2 = r2.read()
        return d2 if d2[:5] == b"%PDF-" else None
    # direct pdf link in page
    m = re.search(r'href="([^"]+\.pdf[^"]*)"', t, re.I)
    if m:
        purl = m.group(1) if m.group(1).startswith("http") else urllib.parse.urljoin(url, m.group(1))
        req3 = urllib.request.Request(purl, headers=UA)
        with urllib.request.urlopen(req3, timeout=timeout) as r3:
            d3 = r3.read()
        return d3 if d3[:5] == b"%PDF-" else None
    return None

def main():
    fund_path = os.path.join(BASE, "fundamentals.json")
    db = json.load(open(fund_path, encoding="utf-8"))
    comps = db["companies"]

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    # companies with PDF-only statements (no structured data yet)
    todo = []
    for k, v in comps.items():
        st = v.get("statements") or {}
        if st.get("format") == "pdf" or not st.get("data"):
            url = st.get("url") or ""
            if url and url.startswith("http"):
                todo.append((k, url))
    if limit:
        todo = todo[:limit]
    print(f"[batch_ir] {len(todo)} PDF-only companies to process")

    done = 0
    for key, url in todo:
        comp = comps[key]
        try:
            data = get_pdf(url)
            if not data:
                print(f"  {key}: download failed / not PDF")
                time.sleep(1)
                continue
            st = ir.parse_pdf_statements(data)
            if st:
                rec = comp.get("statements") or {}
                rec["data"] = st
                rec["format"] = "ir-pdf"
                rec["source"] = "Company IR PDF"
                comp["statements"] = rec
                print(f"  {key}: {len(st)} fields ({', '.join(list(st)[:4])})")
                done += 1
            else:
                print(f"  {key}: PDF parsed but no statement figures found")
        except Exception as e:
            print(f"  {key}: ERR {str(e)[:60]}")
        time.sleep(0.5)

    json.dump(db, open(fund_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ns = sum(1 for v in comps.values() if (v.get("statements") or {}).get("data"))
    print(f"\nDONE: {ns}/190 companies with structured statement data (+{done} this pass)")

if __name__ == "__main__":
    main()
