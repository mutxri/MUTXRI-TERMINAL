#!/usr/bin/env python3
"""finish_all.py - close every remaining gap in one pass:
1. Re-extract statements for the 19 companies that have docs but no statements
2. Re-scrape descriptions for the 5 missing descriptions
3. Fetch EOD prices for the new NGX companies from kwayisi
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
    """Parse narrative financial statement text -> {field: value}."""
    st = {}
    # income statement section
    isec = ""
    i = txt.find("Condensed Statement of Comprehensive Income")
    if i < 0:
        i = txt.find("Statement of Comprehensive Income")
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
            elif "thousand" in s or "k" == s: n *= 1e3
        return n
    st["revenue"] = amt([rf"[Rr]evenue {VERBS}[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["gross_profit"] = amt([rf"[Gg]ross profit (?:of|was|reached|stood at|jumped to|rose to|grew to|climbed to)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["operating_profit"] = amt([rf"[Oo]perating profit {VERBS}[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    st["profit_after_tax"] = amt([rf"[Pp]rofit (?:for the period|after tax|for the year|attributable)[^,]{{0,60}}?(?:was|stood at|reached|jumped|rocketed|rose|amounted to|skyrocketed|surged)[^,]{{0,40}}?({N})(million|billion|bn|m|trillion|tn|thousand|k)?"])
    # EPS - plain, no scale
    m = find([rf"[Bb]asic earnings per share \(EPS\) of ({N})", rf"[Ee]arnings per share (?:of|was) ({N})"])
    if m:
        st["eps"] = to_num(re.sub(r"[^\d.]", "", m.group(1)))
    # balance sheet
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
    # cash flow
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
    # drop empty
    return {k: v for k, v in st.items() if v is not None}

def pick_latest_doc(comp):
    docs = comp.get("documents", [])
    cands = []
    for d in docs:
        url = d.get("url") or ""
        year = str(d.get("year") or "")
        period = (d.get("period") or "").upper()
        dtype = (d.get("type") or "").lower()
        # skip junk rows (dividend declarations, dates-as-year)
        if not url or not url.startswith("http") or len(year) != 4 or not year.isdigit():
            continue
        # skip press releases / presentations - not financial statements
        if "pr" in dtype or "presentation" in dtype or re.search(r"\d{4}-pr", url):
            continue
        # period from URL if not set properly
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

    # 1) statements for the 19 with docs but none extracted
    todo = [k for k, v in comps.items() if not v.get("statements") and v.get("documents")]
    print(f"[1] statement retry: {len(todo)} companies")
    done = 0
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
            if st:
                comp["statements"] = {"period": doc.get("period"), "year": doc.get("year"),
                                      "url": doc.get("url"), "source": "African Financials", "data": st}
                print(f"  {key}: {len(st)} fields ({', '.join(list(st)[:4])})")
                done += 1
            else:
                print(f"  {key}: loaded but no statement text matched")
        except Exception as e:
            print(f"  {key}: ERR {str(e)[:50]}")
        time.sleep(0.8)

    # 2) descriptions for the 5 missing
    missing_desc = [k for k, v in comps.items() if not v.get("description")]
    print(f"\n[2] description retry: {len(missing_desc)}")
    for key in missing_desc:
        comp = comps[key]
        slug = comp.get("slug") or key.split(":")[-1]
        try:
            t = get(f"https://africanfinancials.com/company/{slug}/")
            txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
            txt = re.sub(r"\s+", " ", txt)
            m = re.search(r"(?:About|Company Profile|Profile|Overview)[^.]{0,80}?\.\s*(.{80,500}?)(?:Financial|Employees|Share|Address|\\n|$)", txt)
            # fallback: meta description
            if not m:
                md = re.search(r'name="description" content="([^"]+)"', t)
                if md:
                    comp["description"] = md.group(1)[:400]
                    print(f"  {key}: meta description")
                    continue
            if m:
                comp["description"] = m.group(1).strip()[:400]
                print(f"  {key}: description")
        except Exception as e:
            print(f"  {key}: ERR {str(e)[:40]}")
        time.sleep(0.8)

    json.dump(db, open(fund_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ns = sum(1 for v in comps.values() if v.get("statements"))
    nd = sum(1 for v in comps.values() if v.get("description"))
    print(f"\nDONE: statements {ns}/190 | descriptions {nd}/190")

if __name__ == "__main__":
    main()
