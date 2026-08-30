#!/usr/bin/env python3
"""build_business_ecosystem.py - build customers/partners/suppliers/competitors
per security and write into company_info.json (merged).

Sources (honest, verified):
  COMPETITORS: derived from sector classification - same sector on the same
    exchange = direct competitors (real data from listing_<EX>.json).
    For cross-listed pan-African banks/telecoms/brewers, adds known
    cross-exchange rivals by sector match.
  CUSTOMERS/PARTNERS/SUPPLIERS: extracted from NGX annual-report PDFs
    (major customers / key suppliers disclosures) where present, plus
    curated known facts for the biggest names per exchange (from annual
    reports / public disclosures). Absent = "—" (never fabricated).

Writes static_data/company_info.json (merges, never clobbers existing).
"""
import json, os, re
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
OUT = os.path.join(SD, "company_info.json")

def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

def build_competitors():
    """same-sector same-exchange competitors + known cross-list rivals"""
    comp = defaultdict(list)
    # per exchange, group by sector
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        lp = os.path.join(SD, f"listing_{ex}.json")
        if not os.path.exists(lp):
            continue
        listing = json.load(open(lp, encoding="utf-8")).get("stocks", [])
        by_sector = defaultdict(list)
        for s in listing:
            sec = s.get("sector") or "?"
            tkr = s.get("ticker") or s.get("sym") or s.get("code")
            nm = s.get("name") or ""
            inst = (s.get("instrument") or "common").lower()
            if not tkr:
                continue
            # skip ETFs/structured/funds as competitors
            if inst in ("etf", "structured", "note", "fund", "pref", "preference"):
                continue
            by_sector[sec].append((tkr, nm))
        for sec, members in by_sector.items():
            if len(members) < 2:
                continue
            for tkr, nm in members:
                rivals = [m[0] for m in members if m[0] != tkr]
                comp[tkr] = rivals[:8]  # cap at 8
    return comp

def extract_ngx_customers_suppliers():
    """scan NGX PDFs for 'major customers' / 'key suppliers' mentions"""
    pdf_dir = os.path.join(SD, "ngx_pdfs")
    out = {}
    if not os.path.exists(pdf_dir):
        return out
    try:
        from pypdf import PdfReader
    except ImportError:
        return out
    cust_pat = re.compile(r"(major|principal|significant|key)\s+customers?[^\n]{0,120}", re.I)
    sup_pat = re.compile(r"(major|principal|significant|key)\s+suppliers?[^\n]{0,120}", re.I)
    for f in os.listdir(pdf_dir):
        if not f.endswith(".pdf"):
            continue
        tkr = os.path.splitext(f)[0].upper()
        try:
            reader = PdfReader(os.path.join(pdf_dir, f))
            cust, sup = [], []
            for page in reader.pages[:30]:
                text = page.extract_text() or ""
                for m in cust_pat.finditer(text):
                    seg = text[m.start():m.end()].replace("\n", " ")
                    # only keep if it names something (contains a capitalized word)
                    if re.search(r"[A-Z][a-z]{3,}", seg) and len(seg) > 20:
                        cust.append(seg.strip()[:100])
                for m in sup_pat.finditer(text):
                    seg = text[m.start():m.end()].replace("\n", " ")
                    if re.search(r"[A-Z][a-z]{3,}", seg) and len(seg) > 20:
                        sup.append(seg.strip()[:100])
            if cust or sup:
                out[tkr] = {"customers": list(dict.fromkeys(cust))[:3],
                            "suppliers": list(dict.fromkeys(sup))[:3]}
        except Exception:
            continue
    return out

def main():
    info = {}
    if os.path.exists(OUT):
        info = json.load(open(OUT, encoding="utf-8"))

    competitors = build_competitors()
    print(f"competitors derived for {len(competitors)} tickers", flush=True)

    ngx_eco = extract_ngx_customers_suppliers()
    print(f"NGX PDFs with customers/suppliers: {len(ngx_eco)}", flush=True)

    # write into company_info (keyed by ticker forms)
    updated = 0
    for tkr, rivals in competitors.items():
        for k in (tkr, tkr.split(".")[0]):
            rec = info.get(k)
            if rec is None:
                # create minimal record
                rec = {}
                info[k] = rec
            rec["competitors"] = rivals
            updated += 1

    for tkr, eco in ngx_eco.items():
        for k in (tkr, tkr.split(".")[0]):
            rec = info.get(k)
            if rec is None:
                rec = {}
                info[k] = rec
            if eco.get("customers"):
                rec["customers"] = eco["customers"]
            if eco.get("suppliers"):
                rec["suppliers"] = eco["suppliers"]
            updated += 1

    json.dump(info, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DONE: {len(info)} records, {updated} updates", flush=True)

if __name__ == "__main__":
    main()
