#!/usr/bin/env python3
"""jse_financials_crawler.py - crawl the JSE Client Portal for official
financial statements (FREE, public) and extract headline figures.

Source: https://clientportal.jse.co.za/companies-and-financial-instruments
Services:
  CustomerRoleService.svc/GetAllIssuers            -> all issuers
  WebstirService.svc/GetWebstirDocumentYears...    -> years per issuer
  WebstirService.svc/GetWebstirDocumentsByIssuerMasterIdAndYear -> docs
  webstir.jse.co.za/Downloads/File/?id=...         -> PDF download

Steps:
  1. Load issuers (jse_issuers_raw.json or fetch live)
  2. For each equity issuer: fetch years, then financial docs per year
  3. Record the ANNUAL FINANCIAL STATEMENT doc URLs (skip interim/provisional)
  4. Download the most recent AFS PDF, extract headline figures
  5. Save jse_financials.json + update the filings registry
"""
import json, os, re, sys, time, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
PORTAL = "https://clientportal.jse.co.za/_vti_bin/JSE/"
WEBSTIR = "https://webstir.jse.co.za/Downloads/File/?id="

def post_svc(service, body, timeout=30):
    req = urllib.request.Request(PORTAL + service,
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={**UA, "Content-Type": "application/json;", "Accept": "application/json"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read().decode(errors="replace"))

def clean_date(s):
    m = re.search(r"(\d+)", s or "")
    if m:
        import datetime
        return datetime.datetime.fromtimestamp(int(m.group(1)) / 1000).strftime("%Y-%m-%d")
    return ""

def get_equity_issuers():
    """Return equity issuers from the raw dump (or fetch live)."""
    raw_path = os.path.join(BASE, "jse_issuers_raw.json")
    if os.path.exists(raw_path):
        data = json.load(open(raw_path, encoding="utf-8"))
    else:
        d = post_svc("CustomerRoleService.svc/GetAllIssuers", {"filterLongName": "", "filterType": ""})
        data = d if isinstance(d, list) else d.get("GetAllIssuersResult", [])
        json.dump(data, open(raw_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    equities = [x for x in data if x.get("RoleDescription") == "Equity Issuer"]
    return equities

def get_financial_docs(issuer_master_id, max_years=3):
    """Return the most recent AFS doc URLs for an issuer."""
    try:
        years = post_svc("WebstirService.svc/GetWebstirDocumentYearsByIssuerMasterId",
                         {"issuerMasterId": issuer_master_id})
        years = years.get("GetWebstirDocumentYearsByIssuerMasterIdResult", [])
        if not years:
            return []
    except Exception:
        return []
    docs = []
    for y in sorted(years, reverse=True)[:max_years]:
        try:
            d = post_svc("WebstirService.svc/GetWebstirDocumentsByIssuerMasterIdAndYear",
                         {"issuerMasterId": issuer_master_id, "year": str(y)})
            result = d.get("GetWebstirDocumentsByIssuerMasterIdAndYearResult", [])
            for doc in result:
                dt = doc.get("DocumentType", "")
                if "Annual Financial Statement" in dt:
                    docs.append({
                        "year": y,
                        "type": dt,
                        "url": doc.get("DocumentUrl", ""),
                        "submitted": clean_date(doc.get("SubmittedDate")),
                    })
        except Exception:
            continue
        time.sleep(0.2)
    return docs

def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    equities = get_equity_issuers()
    print(f"Equity issuers: {len(equities)}")
    out = {}
    for i, e in enumerate(equities[:limit]):
        mid = e["MasterID"]
        name = e.get("LongName", "")
        alpha = e.get("AlphaCode", "")
        docs = get_financial_docs(mid)
        if docs:
            out[alpha] = {
                "name": name,
                "master_id": mid,
                "registration": e.get("RegistrationNumber", ""),
                "website": e.get("Website", ""),
                "docs": docs,
            }
            print(f"  [{i+1}/{limit}] {alpha} ({name[:40]}): {len(docs)} AFS docs")
        else:
            print(f"  [{i+1}/{limit}] {alpha}: no AFS docs")
        time.sleep(0.3)
    out_path = os.path.join(BASE, "jse_financials.json")
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nsaved {out_path}: {len(out)} issuers with financial docs")

if __name__ == "__main__":
    main()
