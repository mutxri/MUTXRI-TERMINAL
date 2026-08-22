#!/usr/bin/env python3
"""Augment fundamentals.json with company description, employees, and revenue
from African Financials company pages (the structured 'Financial Highlights'
section + meta description + Employees line).
Throttled single pass - safe for the rate limit. Run: python augment_des.py
"""
import json, re, html, time, urllib.request, os

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}

BASE = os.path.dirname(os.path.abspath(__file__))
FUND = os.path.join(BASE, "fundamentals.json")
SLUGS = os.path.join(BASE, "af_slugs.json")

def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def extract(t, txt):
    out = {}
    # 1) description: meta description (skip the boilerplate 'We make research...')
    descs = re.findall(r'"description":"([^"]{20,400})"', t)
    for d in descs:
        d = html.unescape(d).strip()
        if d and "We make research" not in d and "convenient" not in d:
            out["description"] = d
            break
    # 2) employees: "Employees: Safaricom employs 6,777 people" (colon + employs)
    m = re.search(r"[Ee]mployees?:?\s*[^.]{0,40}?employs?\s+([\d,]+)\s+people", txt)
    if not m:
        m = re.search(r"[Ee]mploys?\s+([\d,]+)\s+people", txt)
    if m:
        out["employees"] = int(m.group(1).replace(",", ""))
    # 3) revenue: from structured highlights block "Total Revenue (FY2025): KShs 388.7 billion"
    m = re.search(r"Total Revenue[^:]{0,30}:\s*([^.\n]{3,60})", txt)
    if not m:
        m = re.search(r"(?:revenue|Revenue)[^:]{0,25}:\s*(KShs|KES|NGN|N\$|R|EGP|US\$|USD|₦|Ksh)\s*[\d,.]+\s*(?:billion|million|bn|m|trillion)?", txt)
    if m:
        out["revenue"] = m.group(0).replace("Total Revenue", "Revenue").strip()
    # 4) profit / eps if present
    m = re.search(r"Profit After Tax[^:]{0,20}:\s*([^.\n]{3,60})", txt)
    if m:
        out["profit_after_tax"] = m.group(1).strip()
    m = re.search(r"Basic Earnings Per Share[^:]{0,10}:\s*([^.\n]{3,60})", txt)
    if m:
        out["eps"] = m.group(1).strip()
    # 5) customers/subscribers
    m = re.search(r"Number of Customers[^:]{0,20}:\s*([^.\n]{3,60})", txt)
    if m:
        out["customers"] = m.group(1).strip()
    return out

def main():
    try:
        db = json.load(open(FUND, encoding="utf-8"))
    except Exception as e:
        print("fundamentals.json load fail:", e)
        return
    comps = db["companies"]
    todo = [(k, v) for k, v in comps.items() if not v.get("description") and v.get("slug")]
    print(f"{len(comps)} companies, {len(todo)} to augment (parallel)")

    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()

    def worker(item):
        key, comp = item
        slug = comp["slug"]
        try:
            url = f"https://africanfinancials.com/company/{slug}/"
            t = get(url)
            txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
            txt = re.sub(r"\s+", " ", txt)
            extra = extract(t, txt)
            if extra:
                with lock:
                    comp.update(extra)
                    comp["fetched"] = int(time.time())
            return True
        except Exception as e:
            return False

    done = 0
    # gentle pass: 2 workers, long gaps (AF rate-limits bursts)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i, _ in enumerate(pool.map(worker, todo)):
            done += 1
            if done % 20 == 0:
                with lock:
                    json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"  {done}/{len(todo)} done")
            time.sleep(2.2)  # gentle throttle: 2.2s between items

    json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with_desc = sum(1 for v in comps.values() if v.get("description"))
    with_emp = sum(1 for v in comps.values() if v.get("employees"))
    with_rev = sum(1 for v in comps.values() if v.get("revenue"))
    print(f"\nDONE: {done} attempted | description {with_desc} | employees {with_emp} | revenue {with_rev}")

if __name__ == "__main__":
    main()
