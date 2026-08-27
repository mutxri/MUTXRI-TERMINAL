#!/usr/bin/env python3
"""jse_full_crawl.py - download + extract financials for ALL JSE equity issuers.

Pipeline:
  1. Load equity issuers (297)
  2. For each: get AFS doc URLs (most recent year only for speed)
  3. Download the PDF (skip if already downloaded)
  4. Extract income/balance/cashflow figures
  5. Save jse_financials.json (docs) + jse_financials_data.json (figures)

Resumable: skips issuers already processed. Run repeatedly until done.
"""
import json, os, re, sys, time, urllib.request, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jse_extract import extract

BASE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
PORTAL = "https://clientportal.jse.co.za/_vti_bin/JSE/"
PDF_DIR = os.path.join(BASE, "jse_pdfs")
DOCS_PATH = os.path.join(BASE, "jse_financials.json")
DATA_PATH = os.path.join(BASE, "jse_financials_data.json")

def post_svc(service, body, timeout=30):
    req = urllib.request.Request(PORTAL + service,
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={**UA, "Content-Type": "application/json;", "Accept": "application/json"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode(errors="replace"))

def get_equity_issuers():
    data = json.load(open(os.path.join(BASE, "jse_issuers_raw.json"), encoding="utf-8"))
    return [x for x in data if x.get("RoleDescription") == "Equity Issuer"]

def get_latest_afs(mid):
    """Return the single most recent AFS doc for an issuer."""
    try:
        years = post_svc("WebstirService.svc/GetWebstirDocumentYearsByIssuerMasterId",
                         {"issuerMasterId": mid})
        years = years.get("GetWebstirDocumentYearsByIssuerMasterIdResult", [])
    except Exception:
        return None
    for y in sorted(years, reverse=True):
        try:
            d = post_svc("WebstirService.svc/GetWebstirDocumentsByIssuerMasterIdAndYear",
                         {"issuerMasterId": mid, "year": str(y)})
            for doc in d.get("GetWebstirDocumentsByIssuerMasterIdAndYearResult", []):
                if "Annual Financial Statement" in doc.get("DocumentType", ""):
                    return {"year": y, "url": doc.get("DocumentUrl", ""),
                            "type": doc.get("DocumentType", "")}
        except Exception:
            continue
        time.sleep(0.2)
    return None

def download(url, dest, timeout=300):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
    return os.path.getsize(dest)

def main():
    os.makedirs(PDF_DIR, exist_ok=True)
    equities = get_equity_issuers()
    print(f"Equity issuers: {len(equities)}")

    # load existing progress
    docs_db = json.load(open(DOCS_PATH, encoding="utf-8")) if os.path.exists(DOCS_PATH) else {}
    data_db = json.load(open(DATA_PATH, encoding="utf-8")) if os.path.exists(DATA_PATH) else {}
    print(f"already in docs_db: {len(docs_db)}, data_db: {len(data_db)}")

    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else len(equities)

    for i in range(start, min(end, len(equities))):
        e = equities[i]
        alpha = e.get("AlphaCode", "")
        mid = e["MasterID"]
        if alpha in data_db and data_db[alpha].get("figures"):
            continue  # already done
        doc = get_latest_afs(mid)
        if not doc:
            print(f"[{i+1}/{len(equities)}] {alpha}: no AFS")
            docs_db.setdefault(alpha, {"name": e.get("LongName", ""), "master_id": mid, "docs": []})
            json.dump(docs_db, open(DOCS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            continue
        pdf_path = os.path.join(PDF_DIR, f"{alpha}_{doc['year']}.pdf")
        if not os.path.exists(pdf_path):
            try:
                sz = download(doc["url"], pdf_path)
                print(f"[{i+1}/{len(equities)}] {alpha}: downloaded {sz//1024}KB ({doc['year']})")
            except Exception as ex:
                print(f"[{i+1}/{len(equities)}] {alpha}: DL FAIL {str(ex)[:60]}")
                continue
        try:
            res = extract(pdf_path, alpha)
            figs = {sec: {k: {"value": v["value"], "unit": v["unit"]}
                          for k, v in res.get(sec, {}).items() if isinstance(v, dict) and v.get("value") is not None}
                    for sec in ["income", "balance", "cashflow"]}
            figs = {k: v for k, v in figs.items() if v}
            data_db[alpha] = {"name": e.get("LongName", ""), "year": doc["year"],
                              "registration": e.get("RegistrationNumber", ""),
                              "website": e.get("Website", ""), "figures": figs}
            ok = sum(len(v) for v in figs.values())
            print(f"[{i+1}/{len(equities)}] {alpha}: extracted {ok} figures {list(figs.keys())}")
        except Exception as ex:
            print(f"[{i+1}/{len(equities)}] {alpha}: EXTRACT FAIL {str(ex)[:60]}")
        docs_db.setdefault(alpha, {"name": e.get("LongName", ""), "master_id": mid,
                                   "docs": [{"year": doc["year"], "type": doc["type"], "url": doc["url"]}]})
        json.dump(data_db, open(DATA_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(docs_db, open(DOCS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        time.sleep(0.4)

    done = sum(1 for v in data_db.values() if v.get("figures"))
    print(f"\nDONE: {done} issuers with extracted figures")

if __name__ == "__main__":
    main()
