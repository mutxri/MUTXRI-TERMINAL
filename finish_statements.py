#!/usr/bin/env python3
"""finish_statements.py - complete the remaining statement extractions.
Two jobs:
  1. For companies with NO documents scraped: re-scrape the AF company page
     to rebuild the documents list (the original build_fundamentals pass
     failed on them).
  2. For companies with documents but no statements: fetch the latest doc
     page and extract (retry the earlier timeouts).

Gentle: 1.2s between fetches. Resumable. Run: python finish_statements.py
"""
import json, re, html, time, urllib.request, os, sys, importlib.util

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}
BASE = os.path.dirname(os.path.abspath(__file__))
FUND = os.path.join(BASE, "fundamentals.json")

def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def scrape_documents(t):
    """Rebuild the documents list from an AF company page HTML."""
    docs = []
    seen = set()
    # document links: /document/<slug>-<year>-<period>/
    for m in re.finditer(r'href="(https://africanfinancials\.com/document/[^"]+)"[^>]*>\s*([^<]{3,120})', t):
        url, label = m.group(1), html.unescape(m.group(2)).strip()
        if url in seen:
            continue
        seen.add(url)
        label_l = label.lower()
        typ = "Interim Report"
        if "annual" in label_l or "abridged" in label_l:
            typ = "Annual Report" if "annual" in label_l else "Abridged Report"
        elif "presentation" in label_l:
            typ = "Presentation"
        ym = re.search(r"/(\d{4})-[a-z]{2,3}-?([a-z0-9]+)?/?$", url)
        year = ym.group(1) if ym else ""
        period = ""
        if ym and ym.group(2):
            p = ym.group(2).upper()
            period = {"FY": "FY", "HY": "HY", "Q1": "Q1", "Q2": "Q2", "Q3": "Q3", "Q4": "Q4"}.get(p, "")
        if not period and "-ar-" in url:
            period = "FY"
        if not year:
            ym2 = re.search(r"/(\d{4})/", url)
            if ym2:
                year = ym2.group(1)
        docs.append({"type": typ, "year": year, "period": period, "url": url})
    return docs

def main():
    spec = importlib.util.spec_from_file_location("es", os.path.join(BASE, "extract_statements.py"))
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)

    db = json.load(open(FUND, encoding="utf-8"))
    comps = db["companies"]
    todo = [(k, v) for k, v in comps.items() if not v.get("statements")]
    print(f"{len(todo)} companies need statements")

    fixed_docs = 0
    for key, comp in todo:
        slug = comp.get("slug")
        # 1) rebuild documents if missing
        if not comp.get("documents") and slug:
            try:
                t = get(f"https://africanfinancials.com/company/{slug}/")
                docs = scrape_documents(t)
                if docs:
                    comp["documents"] = docs
                    fixed_docs += 1
                    print(f"  {key}: rebuilt {len(docs)} docs")
                time.sleep(1.2)
            except Exception as e:
                print(f"  {key}: doc-scrape ERR {str(e)[:40]}")
        # 2) extract statements from latest doc
        try:
            doc = es.pick_latest_doc(comp)
            if not doc or not doc.get("url"):
                continue
            t = get(doc["url"])
            txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
            txt = re.sub(r"\s+", " ", txt)
            st = es.extract_statements(txt)
            if st:
                comp["statements"] = {"period": doc.get("period"), "year": doc.get("year"),
                                      "url": doc.get("url"), "source": "African Financials", "data": st}
            time.sleep(1.2)
        except Exception as e:
            print(f"  {key}: stmt ERR {str(e)[:40]}")
        # checkpoint every 5
        if todo.index((key, comp)) % 5 == 4:
            json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ns = sum(1 for v in comps.values() if v.get("statements"))
    print(f"\nDONE: statements now {ns}/190 (rebuilt {fixed_docs} doc lists)")

if __name__ == "__main__":
    main()
