#!/usr/bin/env python3
"""Fill financial_summary for all companies — throttled single pass (rate-limit safe).
Run: python fill_financial_summary.py  → updates fundamentals.json
"""
import json, re, html, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0",
      "Accept-Language": "en-US,en;q=0.9"}
OUT = "fundamentals.json"

def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

def parse_financials(desc):
    """Parse financial metrics from AF document meta descriptions.
    Two formats:
      A) bullet: "- Revenue: 199.9B, up 11%.- Profit After Tax: 42.8B..."
      B) prose:  "Revenue grew to NGN 2.51 trillion from NGN 2.07 trillion..."
    """
    fin = {}
    desc = html.unescape(desc)
    # Format A: bullets
    chunks = re.split(r"\.\s*-\s*|-\s*", desc)
    for chunk in chunks:
        cm = re.match(r"\s*([A-Za-z][A-Za-z &()/]+?)\s*:\s*(.+)", chunk)
        if cm:
            label = cm.group(1).strip().lower().replace(" ", "_")
            val = cm.group(2).strip().rstrip(".").strip()
            if label and val and label not in fin and len(val) < 80:
                fin[label] = val
    # Format B: prose patterns
    prose_pats = [
        (r"revenue (?:grew|rose|increased|declined|fell|was|stood at|reached) (?:by )?(?:to |from )?([\d.,]+\s*(?:trillion|billion|million|bn|m|KShs|KES|NGN|R|EGP)?)", "revenue"),
        (r"(?:profit after tax|net income|net profit|profit for the period|profit for the year|PAT) (?:grew|rose|increased|declined|fell|was|stood at|reached|of|was) (?:by )?(?:to )?([\d.,]+\s*(?:trillion|billion|million|bn|m|KShs|KES|NGN|R|EGP)?)", "profit_after_tax"),
        (r"(?:earnings per share|basic EPS|EPS) (?:was|of|stood at|is) (?:KShs|KES|NGN|R|EGP)?\s?([\d.,]+)", "eps"),
        (r"total assets (?:of|were|stood at|was|reached) (?:KShs|KES|NGN|R|EGP)?\s?([\d.,]+\s*(?:trillion|billion|million|bn|m)?)", "total_assets"),
        (r"(?:operating profit|EBIT|operating income) (?:grew|rose|increased|was|stood at|of|by) (?:by )?(?:to )?([\d.,]+\s*(?:trillion|billion|million|bn|m|KShs|KES|NGN|R|EGP)?)", "operating_profit"),
        (r"(?:dividend per share|DPS|dividend) (?:of|was|declared at) (?:KShs|KES|NGN|R|EGP)?\s?([\d.,]+)", "dividend_per_share"),
    ]
    low = desc.lower()
    for pat, key in prose_pats:
        if key in fin:
            continue
        m = re.search(pat, low)
        if m:
            fin[key] = m.group(1).strip()[:60]
    return fin

def main():
    db = json.load(open(OUT, encoding="utf-8"))
    comps = db["companies"]
    todo = [(k, v) for k, v in comps.items()
            if v.get("documents") and not v.get("financial_summary")]
    print(f"{len(todo)} companies need financial_summary")

    done, failed = 0, 0
    for k, v in todo:
        try:
            url = v["documents"][0]["url"]
            dt = get(url)
            m = re.search(r'<meta name="description" content="([^"]+)"', dt) or \
                re.search(r'<meta property="og:description" content="([^"]+)"', dt)
            if m:
                fin = parse_financials(m.group(1))
                if fin:
                    v["financial_summary"] = fin
                    done += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        if (done + failed) % 15 == 0:
            json.dump(db, open(OUT, "w"), encoding="utf-8", indent=1)
            print(f"  done={done} failed={failed} total={done+failed}/{len(todo)} ({k})")
        time.sleep(1.2)  # throttle — AF rate-limits bursts

    json.dump(db, open(OUT, "w"), encoding="utf-8", indent=1)
    print(f"DONE: {done} with financial_summary, {failed} failed")

if __name__ == "__main__":
    main()
