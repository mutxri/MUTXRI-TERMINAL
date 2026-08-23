#!/usr/bin/env python3
"""final_statements.py - last pass: retry the 18 statement-less companies.
For each: pick the latest real statement doc (fixed picker), fetch the page.
If narrative text exists -> extract structured fields.
If PDF-only -> record the statement URL (view filing still works) with an
honest "pdf" marker so the UI links the actual report.
"""
import json, re, html, time, urllib.request, sys, os

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
BASE = os.path.dirname(os.path.abspath(__file__))

def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")

def to_num(s):
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None

N = r"[A-Z$£€₦]{0,4}[\d,]+\.?\d*\s*(?:million|billion|bn|m|trillion|tn|thousand|k)?"
VERBS = r"(?:jump(?:ed|ing)|grew|was|stood at|reached|amounted to|rose|climbed|surged|skyrocketed|increased|declined|decreased|dropped|fell|hit|topped)"

def extract_statements(txt):
    st = {}
    isec = ""
    i = txt.find("Condensed Statement of Comprehensive Income")
    if i < 0:
        i = txt.find("Statement of Comprehensive Income")
    if i < 0:
        i = txt.find("Comprehensive Income")
    if i >= 0:
        j = txt.find("Condensed Statement of Financial Position", i)
        if j < 0:
            j = txt.find("Statement of Financial Position", i)
        isec = txt[i:j if j > i else i + 3000]
    def find(patterns):
        for p in patterns:
            m = re.search(p, isec, re.I)
            if m:
                return m
        return None
    def amt(patterns):
        m = find(patterns)
        if not m:
            return None
        n = to_num(m.group(1))
        s = m.group(2)
        if n is not None and s:
            if "billion" in s: n *= 1e9
            elif "million" in s or "bn" in s: n *= 1e6
            elif "trillion" in s or "tn" in s: n *= 1e12
            elif "thousand" in s: n *= 1e3
        return n
    st["revenue"] = amt([rf"[Rr]evenue {VERBS}[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["gross_profit"] = amt([rf"[Gg]ross profit (?:of|was|reached|stood at|jumped to|rose to|grew to|climbed to)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["operating_profit"] = amt([rf"[Oo]perating profit {VERBS}[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["profit_after_tax"] = amt([rf"[Pp]rofit (?:for the period|after tax|for the year|attributable)[^,]{{0,60}}?(?:was|stood at|reached|jumped|rocketed|rose|amounted to|skyrocketed|surged)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    m = find([rf"[Bb]asic earnings per share \(EPS\) of ({N})", rf"[Ee]arnings per share (?:of|was) ({N})"])
    if m:
        st["eps"] = to_num(re.sub(r"[^\d.]", "", m.group(1)))
    bsec = ""
    i = txt.find("Condensed Statement of Financial Position")
    if i < 0:
        i = txt.find("Statement of Financial Position")
    if i >= 0:
        j = txt.find("Condensed Statement of Cash Flows", i)
        if j < 0:
            j = txt.find("Statement of Cash Flows", i)
        bsec = txt[i:j if j > i else i + 2500]
    def bamt(patterns):
        for p in patterns:
            m = re.search(p, bsec, re.I)
            if m:
                n = to_num(m.group(1))
                s = m.group(2)
                if n is not None and s:
                    if "billion" in s: n *= 1e9
                    elif "million" in s or "bn" in s: n *= 1e6
                    elif "trillion" in s or "tn" in s: n *= 1e12
                    elif "thousand" in s: n *= 1e3
                return n
        return None
    st["total_assets"] = bamt([rf"[Tt]otal assets (?:of|were|was|stood at|reached|amounted to)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["total_liabilities"] = bamt([rf"[Tt]otal liabilities (?:of|were|was|stood at|reached|amounted to)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    csec = ""
    i = txt.find("Condensed Statement of Cash Flows")
    if i < 0:
        i = txt.find("Statement of Cash Flows")
    if i >= 0:
        csec = txt[i:i + 2500]
    def camt(patterns):
        for p in patterns:
            m = re.search(p, csec, re.I)
            if m:
                n = to_num(m.group(1))
                s = m.group(2)
                if n is not None and s:
                    if "billion" in s: n *= 1e9
                    elif "million" in s or "bn" in s: n *= 1e6
                    elif "trillion" in s or "tn" in s: n *= 1e12
                    elif "thousand" in s: n *= 1e3
                return n
        return None
    st["operating_cash_flow"] = camt([rf"[Oo]perating cash flow (?:of|was|stood at|reached|amounted to|generated)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["investing_cash_flow"] = camt([rf"[Ii]nvesting cash flow (?:of|was|stood at|amounted to)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["financing_cash_flow"] = camt([rf"[Ff]inancing cash flow (?:of|was|stood at|amounted to)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    return {k: v for k, v in st.items() if v is not None}

def pick_latest_doc(comp):
    docs = comp.get("documents", [])
    cands = []
    for d in docs:
        url = d.get("url") or ""
        year = str(d.get("year") or "")
        period = (d.get("period") or "").upper()
        dtype = (d.get("type") or "").lower()
        if not url or not url.startswith("http") or len(year) != 4 or not year.isdigit():
            continue
        if "pr" in dtype or "presentation" in dtype or re.search(r"\d{4}-pr", url):
            continue
        if period not in ("AR", "IR", "AB", "HY", "FY", "Q1", "Q2", "Q3", "Q4"):
            ym = re.search(r"(\d{4})-([a-z]{2})-?([a-z0-9]+)?", url)
            if ym:
                period = {"ar": "AR", "ir": "IR", "ab": "AB", "hy": "HY", "fy": "FY",
                          "q1": "Q1", "q2": "Q2", "q3": "Q3", "q4": "Q4"}.get(ym.group(2).lower(), "AB")
        if period in ("AR", "IR", "AB", "HY", "FY", "Q1", "Q2", "Q3", "Q4"):
            rank = {"AR": 5, "FY": 4, "IR": 3, "HY": 3, "AB": 2, "Q4": 1, "Q3": 1, "Q2": 1, "Q1": 1}[period]
            cands.append((int(year), rank, d))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cands[0][2]

def main():
    fund_path = os.path.join(BASE, "fundamentals.json")
    db = json.load(open(fund_path, encoding="utf-8"))
    comps = db["companies"]
    todo = [k for k, v in comps.items() if not v.get("statements") and v.get("documents")]
    print(f"statement retry: {len(todo)}")
    for key in todo:
        comp = comps[key]
        try:
            doc = pick_latest_doc(comp)
            if not doc:
                print(f"  {key}: no usable doc")
                continue
            t = get(doc["url"])
            txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
            txt = re.sub(r"\s+", " ", txt)
            st = extract_statements(txt)
            rec = {"period": doc.get("period"), "year": doc.get("year"),
                   "url": doc.get("url"), "source": "African Financials"}
            if st:
                rec["data"] = st
                rec["format"] = "narrative"
                print(f"  {key}: {len(st)} fields ({', '.join(list(st)[:4])})")
            else:
                # PDF-only statement - link it honestly
                rec["data"] = {}
                rec["format"] = "pdf"
                print(f"  {key}: PDF-only (linked)")
            comp["statements"] = rec
        except Exception as e:
            print(f"  {key}: ERR {str(e)[:50]}")
        time.sleep(0.7)
    json.dump(db, open(fund_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ns = sum(1 for v in comps.values() if v.get("statements"))
    nn = sum(1 for v in comps.values() if (v.get("statements") or {}).get("data"))
    print(f"DONE: {ns}/190 have statement records | {nn} with structured data")

if __name__ == "__main__":
    main()
