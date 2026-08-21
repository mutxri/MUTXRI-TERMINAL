#!/usr/bin/env python3
"""Build fundamentals.json — dividends, filings, financial highlights per company.
Covers NGX + NSE via African Financials company pages (rich data).
JSE + EGX dividends come from Yahoo chart events (div) — separate pass.
Run: python build_fundamentals.py   → writes fundamentals.json (resumable)
"""
import json, re, html, time, os, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}
OUT = "fundamentals.json"

def get(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def to_float(s):
    try:
        s = str(s).replace(",", "").replace("KShs", "").replace("KES", "").replace("NGN", "").replace("R", "").replace("EGP", "").replace("$", "").strip()
        return float(s)
    except ValueError:
        return None

def parse_company_page(slug, meta):
    """Parse one AF company page -> profile, docs, dividends, highlights."""
    url = f"https://africanfinancials.com/company/{slug}/"
    try:
        t = get(url)
    except Exception as e:
        return {"slug": slug, "error": str(e)}
    out = {"slug": slug, "name": meta.get("name", slug)}

    # ---- Company profile (founded, listed, year end, industry, employees) ----
    profile = {}
    i = t.find("Company Profile")
    seg = t[i:i+15000] if i >= 0 else ""
    txt = html.unescape(re.sub(r"<[^>]+>", "\n", seg))
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    for idx, l in enumerate(lines):
        ll = l.lower()
        if ll in ("founded", "listed", "year end", "industry", "employees", "phone", "indices", "transfer secretary"):
            val = lines[idx+1][:120] if idx+1 < len(lines) else ""
            profile[l.lower().replace(" ", "_")] = val
    out["profile"] = profile

    # ---- Financial highlights: pull labeled figures from profile text ----
    highlights = {}
    # AF pages use patterns like "Total Revenue (FY2025): KShs 388.7 billion" or
    # "Revenue: KShs 199.9 billion, up 11.1% YoY."  Labels/values may straddle lines.
    flat = re.sub(r"\s+", " ", txt)
    hl_pat = re.compile(
        r"(?i)(total revenue|service revenue|profit after tax|net income|profit for the year|"
        r"operating profit|ebit(?:da)?|earnings per share|basic eps|total assets|total equity|net assets|"
        r"cash (?:generated )?from operating|operating cash flow|dividend per share|dps|"
        r"revenue growth|profit margin|operating margin|gross margin|return on equity|roe)"
        r"\s*(?:\([^)]*\))?\s*:?\s*([A-Za-z$]?\s?[\d,.]+\s?(?:KShs|KES|NGN|billion|million|bn|m|%)?)"
    )
    seen = set()
    for m in hl_pat.finditer(flat):
        label = m.group(1).strip().lower().replace(" ", "_")
        val = m.group(2).strip()
        if label in seen or len(val) > 30:
            continue
        seen.add(label)
        highlights[label] = val
    out["highlights"] = highlights

    # ---- Documents (filings) ----
    docs = []
    started = False
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        cells = [c for c in cells if c]
        if any("Type" in c for c in cells) and "Year" in " ".join(cells):
            started = True
            continue
        if started and cells and len(cells) >= 4:
            links = re.findall(r'href="([^"]+)"', r)
            docs.append({"type": cells[0], "year": cells[1], "period": cells[2],
                         "date": cells[3], "url": links[0] if links else ""})
    out["documents"] = docs[:60]

    # ---- Financial statement summary: parse latest document's meta description ----
    fin = {}
    if docs:
        latest = docs[0]["url"]
        for attempt in range(2):
            try:
                dt = get(latest, timeout=60)
                m = re.search(r'<meta name="description" content="([^"]+)"', dt) or re.search(r'<meta property="og:description" content="([^"]+)"', dt)
                if m:
                    desc = html.unescape(m.group(1))
                    # AF descriptions look like: "Period ending X:- Revenue: 199.9B, up 11%.- Profit After Tax: 42.8B..."
                    # Split on bullet separators first, then parse "Label: value" from each chunk
                    chunks = re.split(r"\.\s*-\s*|-\s*", desc)
                    for chunk in chunks:
                        cm = re.match(r"\s*([A-Za-z][A-Za-z &()/]+?)\s*:\s*(.+)", chunk)
                        if cm:
                            label = cm.group(1).strip().lower().replace(" ", "_")
                            val = cm.group(2).strip().rstrip(".").strip()
                            if label and val and label not in fin and len(val) < 80:
                                fin[label] = val
                break
            except Exception:
                time.sleep(2)
    out["financial_summary"] = fin

    # ---- Dividends ----
    divs = []
    started = False
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        cells = [c for c in cells if c]
        if any("Post Date" in c for c in cells):
            started = True
            continue
        if started and cells:
            # flexible: date-ish fields + amount
            datecells = [c for c in cells if re.match(r"^\d{4}-\d{2}-\d{2}$", c)]
            amount = next((c for c in cells if re.search(r"[\d.,]+\s*(KES|NGN|KShs|R|EGP|Tsh|UGX|RWF|ZAR|USD)?$", c) and not re.match(r"^\d{4}-\d{2}-\d{2}$", c)), None)
            if datecells:
                rec = {"dates": datecells, "amount": amount or ""}
                divs.append(rec)
    out["dividends"] = divs[:40]
    out["fetched"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    return out

def main():
    slugs = json.load(open("af_slugs.json"))
    # resume: load existing
    db = {}
    if os.path.exists(OUT):
        try:
            db = json.load(open(OUT))
        except Exception:
            db = {}
    db.setdefault("companies", {})
    db.setdefault("meta", {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())})

    todo = []
    for ex, lst in slugs.items():
        for m in lst:
            key = f"{ex}:{m['slug']}"
            if key not in db["companies"]:
                todo.append((ex, m))
    print(f"{len(todo)} companies to fetch (of {sum(len(v) for v in slugs.values())})")

    def worker(item):
        ex, m = item
        return ex, m, parse_company_page(m["slug"], m)

    done = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        for ex, m, res in pool.map(worker, todo):
            key = f"{ex}:{m['slug']}"
            db["companies"][key] = res
            done += 1
            if done % 10 == 0 or done == len(todo):
                json.dump(db, open(OUT, "w"), indent=1)
                print(f"  {done}/{len(todo)} ({key})")
            time.sleep(0.6)  # be polite
    db["meta"]["generated"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    json.dump(db, open(OUT, "w"), indent=1)
    print(f"DONE. {len(db['companies'])} companies in {OUT}")

if __name__ == "__main__":
    import sys
    if "--refetch-highlights" in sys.argv:
        # delete company entries so resume logic re-fetches pages with new parser
        db = json.load(open(OUT))
        n = len(db["companies"])
        db["companies"] = {}
        json.dump(db, open(OUT, "w"), indent=1)
        print(f"cleared {n} companies — rerun normally to refetch with improved parser")
    else:
        main()
