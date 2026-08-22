#!/usr/bin/env python3
"""retry_gaps.py - retry missing descriptions AND statements for NGX/NSE
companies (rate-limit / timeout victims from earlier passes).
Gentle: 1.5s between fetches, per-company timeout 25s, resumable.
"""
import json, re, html, time, urllib.request, os, sys

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}
BASE = os.path.dirname(os.path.abspath(__file__))
FUND = os.path.join(BASE, "fundamentals.json")

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def extract_des(t, txt):
    out = {}
    descs = re.findall(r'"description":"([^"]{20,400})"', t)
    for d in descs:
        d = html.unescape(d).strip()
        if d and "We make research" not in d and "convenient" not in d:
            out["description"] = d
            break
    m = re.search(r"[Ee]mployees?:?\s*[^.]{0,40}?employs?\s+([\d,]+)\s+people", txt)
    if not m:
        m = re.search(r"[Ee]mploys?\s+([\d,]+)\s+people", txt)
    if m:
        out["employees"] = int(m.group(1).replace(",", ""))
    return out

def main():
    import importlib.util
    spec = importlib.util.spec_from_file_location("es", os.path.join(BASE, "extract_statements.py"))
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)

    db = json.load(open(FUND, encoding="utf-8"))
    comps = db["companies"]
    todo = []
    for k, v in comps.items():
        need = False
        if not v.get("description") and v.get("slug"):
            need = True
        if not v.get("statements") and v.get("documents"):
            need = True
        if need:
            todo.append((k, v))
    print(f"{len(todo)} companies need description and/or statements")

    done = 0
    for key, comp in todo:
        try:
            slug = comp.get("slug")
            if slug and not comp.get("description"):
                t = get(f"https://africanfinancials.com/company/{slug}/")
                txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
                txt = re.sub(r"\s+", " ", txt)
                extra = extract_des(t, txt)
                if extra:
                    comp.update(extra)
            if not comp.get("statements") and comp.get("documents"):
                doc = es.pick_latest_doc(comp)
                if doc:
                    t = get(doc.get("url"))
                    txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
                    txt = re.sub(r"\s+", " ", txt)
                    st = es.extract_statements(txt)
                    if st:
                        comp["statements"] = {"period": doc.get("period"), "year": doc.get("year"),
                                              "url": doc.get("url"), "source": "African Financials", "data": st}
            done += 1
            if done % 10 == 0:
                json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"  {done}/{len(todo)}")
        except Exception as e:
            print(f"  {key}: ERR {str(e)[:50]}")
        time.sleep(1.5)

    json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    nd = sum(1 for v in comps.values() if v.get("description"))
    ns = sum(1 for v in comps.values() if v.get("statements"))
    print(f"\nDONE: description {nd} | statements {ns}")

if __name__ == "__main__":
    main()
