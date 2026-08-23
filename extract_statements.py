#!/usr/bin/env python3
"""extract_statements.py - fetch each company's latest financial statement
document from African Financials and parse the narrative statements
(income statement, balance sheet, cash flow, equity) into structured data.

Saves into fundamentals.json under company["statements"].
Resumable: skips companies that already have statements. Gentle throttle.
"""
import json, re, html, time, urllib.request, os, sys

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}

BASE = os.path.dirname(os.path.abspath(__file__))
FUND = os.path.join(BASE, "fundamentals.json")

NUM_RE = re.compile(r"([A-Z]{1,4}[$£€]?|KShs|KES|NGN|Naira|R\s|EGP|ZAR|US\$|USD|₦|Ksh|N\$)?\s*([\d,]+\.?\d*)\s*(million|billion|bn|m|trillion|tn|thousand|k)?")

def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def to_num(s):
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None

def parse_amount(text):
    """Parse 'N217.31 billion' -> 217310000000 (currency, value, scale).
    Matches the number AND its scale unit (million/billion) immediately
    after it, which the calling patterns must not swallow."""
    if not text:
        return None
    m = re.search(r"([\d,]+\.?\d*)\s*(million|billion|bn|m|trillion|tn|thousand|k)?", text)
    if not m:
        return None
    n = to_num(m.group(1))
    if n is None:
        return None
    scale = (m.group(2) or "").lower()
    mult = {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9,
            "trillion": 1e12, "tn": 1e12, "thousand": 1e3, "k": 1e3}.get(scale, 1)
    return round(n * mult, 2)

def _find_amount(txt, patterns):
    for p in patterns:
        m = re.search(p, txt, re.I)
        if m:
            return parse_amount(m.group(0))
    return None


def _find_amount_plain(txt, patterns):
    """Like _find_amount but NEVER applies a million/billion multiplier
    (per-share values: EPS, DPS). Returns the raw number."""
    for p in patterns:
        m = re.search(p, txt, re.I)
        if m:
            # strip currency prefix and scale suffix: 'N0.39' -> 0.39
            digits = re.sub(r"[^\d.]", "", m.group(1))
            return to_num(digits)
    return None

def extract_statements(txt):
    """Parse the narrative statements from an AF document page text."""
    st = {}
    # ---- Income statement ----
    isec = ""
    i = txt.find("Condensed Statement of Comprehensive Income")
    if i < 0:
        i = txt.find("Statement of Comprehensive Income")
    if i < 0:
        i = txt.find("Profit and Loss")
    if i >= 0:
        j = txt.find("Condensed Statement of Cash Flows", i)
        if j < 0:
            j = txt.find("Statement of Cash Flows", i)
        isec = txt[i:j if j > i else i + 4000]
    # number + scale unit pattern (scale word must be adjacent to number)
    N = r"[A-Z$£€₦]{0,4}[\d,]+\.?\d*\s*(?:million|billion|bn|m|trillion|tn|thousand|k)?"
    VERBS = r"(?:jump(?:ed|ing)|grew|grow(?:ing)?|rose|ris(?:e|ing)|climb(?:ed|ing)|increas(?:ed|ing)|soar(?:ed|ing)|surge(?:d|ing)|was|reach(?:ed|ing)|amounted to|stood at|hit|topped|expanded|expanding)"
    st["revenue"] = _find_amount(isec, [rf"[Rr]evenue {VERBS}[^,]{{0,40}}?({N})",
                                        rf"[Rr]evenue (?:of|was) ({N})"])
    st["gross_profit"] = _find_amount(isec, [rf"[Gg]ross profit (?:of|was|reached|stood at|jumped to|rose to|grew to|climbed to)[^,]{{0,40}}?({N})"])
    st["operating_profit"] = _find_amount(isec, [rf"[Oo]perating profit {VERBS}[^,]{{0,40}}?({N})"])
    st["profit_after_tax"] = _find_amount(isec, [rf"[Pp]rofit (?:for the period|after tax|for the year|attributable)[^,]{{0,60}}?(?:was|stood at|reached|jumped|rocketed|rose|amounted to|skyrocketed|surged)[^,]{{0,40}}?({N})"])
    st["eps"] = _find_amount_plain(isec, [rf"[Bb]asic earnings per share \(EPS\) of ({N})",
                                          rf"[Ee]arnings per share (?:of|was) ({N})"])
    # ---- Balance sheet ----
    bsec = ""
    i = txt.find("Condensed Statement of Financial Position")
    if i < 0:
        i = txt.find("Statement of Financial Position")
    if i >= 0:
        j = txt.find("Condensed Statement of Changes in Equity", i)
        if j < 0:
            j = txt.find("Statement of Changes in Equity", i)
        bsec = txt[i:j if j > i else i + 3500]
    st["total_assets"] = _find_amount(bsec, [rf"[Tt]otal assets[^,]{{0,60}}?(?:rose|grew|increased|stood at|reached|was|climbed|expanded|jumped)[^,]{{0,40}}?({N})"])
    st["total_liabilities"] = _find_amount(bsec, [rf"[Tt]otal liabilities[^,]{{0,60}}?(?:stood at|reached|was|rose|increased)[^,]{{0,40}}?({N})"])
    st["shareholders_equity"] = _find_amount(bsec, [rf"[Ss]hareholder[s]?[^.]{{0,30}}?equity[^,]{{0,60}}?(?:stood at|reached|was|rose|grew|increased)[^,]{{0,40}}?({N})"])
    st["cash_and_equivalents"] = _find_amount(bsec, [rf"[Cc]ash and cash equivalents balance of ({N})",
                                                     rf"[Cc]ash and cash equivalents of ({N})"])
    # ---- Cash flow ----
    csec = ""
    i = txt.find("Condensed Statement of Cash Flows")
    if i < 0:
        i = txt.find("Statement of Cash Flows")
    if i >= 0:
        j = txt.find("Condensed Statement of Changes in Equity", i)
        if j < 0:
            j = txt.find("Selected Explanatory Notes", i)
        csec = txt[i:j if j > i else i + 2500]
    st["operating_cash_flow"] = _find_amount(csec, [rf"[Nn]et cash (?:generated|from|provided)[^,]{{0,50}}?operating activities[^,]{{0,60}}?(?:was|of)?[^,]{{0,40}}?({N})"])
    st["investing_cash_flow"] = _find_amount(csec, [rf"[Cc]ash used in investing activities[^,]{{0,40}}?(?:was|of)[^,]{{0,40}}?({N})"])
    st["financing_cash_flow"] = _find_amount(csec, [rf"[Ff]inancing activities resulted in[^,]{{0,40}}?(?:outflow|inflow) of ({N})",
                                                    rf"[Ff]inancing activities (?:was|of)[^,]{{0,40}}?({N})"])
    # ---- Equity / dividends ----
    st["dividends_paid"] = _find_amount(txt, [rf"[Dd]ividend payment totalling ({N})",
                                              rf"[Dd]ividends? (?:paid|totalling) [A-Z$£€₦]{{0,4}}({N})"])
    st["free_float"] = re.search(r"free float percentage of ([\d.]+)%", txt, re.I).group(1) if re.search(r"free float percentage of ([\d.]+)%", txt, re.I) else None
    # keep only found values
    return {k: v for k, v in st.items() if v is not None}

def pick_latest_doc(comp):
    """Best financial-statement document: newest by year+period (annual > HY > Q).
    Auto-fixes docs whose year/period are missing (rebuilt from the URL)."""
    docs = comp.get("documents", [])
    cands = []
    for d in docs:
        url = d.get("url") or ""
        if "/document/" not in url:
            continue
        year = str(d.get("year") or "")
        period = (d.get("period") or "").upper()
        # rebuild year/period from the URL if missing (old scrape bug)
        if not year.isdigit():
            ym = re.search(r"(\d{4})-[a-z]{2,3}-?([a-z0-9]+)?", url)
            if ym:
                year = ym.group(1)
                if not period:
                    p = ym.group(2).upper()
                    period = {"FY": "FY", "HY": "HY", "Q1": "Q1", "Q2": "Q2", "Q3": "Q3", "Q4": "Q4"}.get(p, "")
            if not period and "-ar-" in url:
                period = "FY"
            if year.isdigit():
                d["year"] = year
                d["period"] = period.lower()
        if not year.isdigit():
            continue
        # skip press releases (pr-) - they are not financial statements
        if re.search(r"\d{4}-pr", url):
            continue
        rank = {"FY": 4, "AR": 4, "ANNUAL": 4, "HY": 3, "Q3": 2, "Q2": 2, "Q1": 1}.get(period, 0)
        cands.append((int(year), rank, d))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cands[0][2]

def main():
    db = json.load(open(FUND, encoding="utf-8"))
    comps = db["companies"]
    reparse = "--reparse" in sys.argv
    if reparse:
        # re-fetch ALL companies that have statements (to upgrade with the better parser)
        todo = [(k, v) for k, v in comps.items() if v.get("documents")]
    else:
        todo = [(k, v) for k, v in comps.items() if not v.get("statements") and v.get("documents")]
    print(f"{len(comps)} companies, {len(todo)} to process ({'REPARSE' if reparse else 'incremental'})")

    done, ok = 0, 0
    for key, comp in todo:
        doc = pick_latest_doc(comp)
        if not doc:
            continue
        url = doc.get("url")
        try:
            t = get(url)
            txt = html.unescape(re.sub(r"<[^>]+>", " ", t))
            txt = re.sub(r"\s+", " ", txt)
            st = extract_statements(txt)
            if st:
                comp["statements"] = {
                    "period": doc.get("period"), "year": doc.get("year"),
                    "url": url, "source": "African Financials",
                    "data": st,
                }
                ok += 1
            done += 1
            if done % 10 == 0:
                json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                print(f"  {done}/{len(todo)} done, {ok} with statements")
        except Exception as e:
            print(f"  {key}: ERR {str(e)[:50]}")
        time.sleep(0.8)

    json.dump(db, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nDONE: {done} tried, {ok} with statements")
    # summary of what fields we got
    from collections import Counter
    fields = Counter()
    for v in comps.values():
        for k in (v.get("statements") or {}).get("data", {}):
            fields[k] += 1
    print("fields captured:", dict(fields))

if __name__ == "__main__":
    main()
