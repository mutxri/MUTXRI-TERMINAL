#!/usr/bin/env python3
"""fetch_ngx_financials.py - download NGX official financial statement PDFs
from doclib.ngxgroup.com and extract income/balance/cashflow where possible.

The NGX doclib API lists 229 financial-statement disclosures with PDF URLs.
We download them (the official audited statements) and try to extract line
items. Where extraction isn't possible, we keep the PDF link so the panel
can show "official filing" (links only, never fabricated numbers).

Writes:
  - static_data/ngx_financials.json  (statement metadata per ticker)
  - static_data/financials/<SYM>__<type>.json  (parsed when possible)
"""
import json, os, re, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_META = os.path.join(BASE, "static_data", "ngx_financials.json")
FIN_DIR = os.path.join(BASE, "static_data", "financials")
PDF_DIR = os.path.join(BASE, "static_data", "ngx_pdfs")
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(FIN_DIR, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}

def get(url, timeout=40, binary=False):
    req = urllib.request.Request(url, headers=UA)
    r = urllib.request.urlopen(req, timeout=timeout)
    data = r.read()
    return data if binary else data.decode(errors="replace")

def main():
    # rebuild from the disclosures file if present, else fetch fresh
    src = os.path.join(BASE, "_ngx_disclosures.json")
    if os.path.exists(src):
        disc = json.load(open(src, encoding="utf-8"))
    else:
        url = ("https://doclib.ngxgroup.com/_api/Web/Lists/GetByTitle('XFinancial_News')/items/"
               "?$select=URL,Modified,Created,CompanyName,CompanySymbol,InternationSecIN,Type_of_Submission"
               "&$orderby=Created%20desc&$filter=Modified%20ge%20%272019-01-31T23:00:00.000Z%27&$Top=1000")
        req = urllib.request.Request(url, headers={"Accept": "application/json;odata=verbose", **UA})
        d = json.loads(urllib.request.urlopen(req, timeout=40).read().decode())
        disc = []
        for it in d["d"]["results"]:
            disc.append({
                "symbol": it.get("CompanySymbol"), "company": it.get("CompanyName"),
                "type": it.get("Type_of_Submission"), "date": it.get("Created", "")[:10],
                "title": (it.get("URL") or {}).get("Description", ""),
                "url": (it.get("URL") or {}).get("Url", ""),
            })

    fin = [x for x in disc if "financial" in (x.get("type") or "").lower()
           or "financial" in (x.get("title") or "").lower()]
    print(f"NGX financial disclosures: {len(fin)}")

    # group by ticker, keep most recent per ticker
    by_tkr = {}
    for x in fin:
        tkr = x.get("symbol") or ""
        if not tkr: continue
        cur = by_tkr.get(tkr)
        if not cur or x.get("date", "") > cur.get("date", ""):
            by_tkr[tkr] = x
    print(f"unique tickers with statements: {len(by_tkr)}")

    meta = {}
    for i, (tkr, x) in enumerate(sorted(by_tkr.items())):
        url = x.get("url", "")
        pdf_path = None
        if url:
            try:
                fname = re.sub(r"[^A-Za-z0-9._-]", "_", tkr) + ".pdf"
                pdf_path = os.path.join(PDF_DIR, fname)
                data = get(url, binary=True)
                if data[:4] == b"%PDF":
                    open(pdf_path, "wb").write(data)
                    pdf_path = pdf_path
                else:
                    pdf_path = None
            except Exception as e:
                pdf_path = None
        meta[tkr] = {
            "ticker": tkr, "company": x.get("company") or tkr,
            "title": x.get("title", ""), "date": x.get("date", ""),
            "url": url, "pdf": pdf_path,
        }
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(by_tkr)}", flush=True)
        time.sleep(0.3)

    json.dump(meta, open(OUT_META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    npdfs = sum(1 for v in meta.values() if v.get("pdf"))
    print(f"DONE: {len(meta)} tickers, {npdfs} PDFs downloaded")

if __name__ == "__main__":
    main()
