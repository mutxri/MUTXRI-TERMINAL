#!/usr/bin/env python3
"""mass_ir_crawler.py - crawl company IR sites for ALL JSE/EGX/NGX/NSE stocks.
For each company (top-N by liquidity first):
  1. discover website (DuckDuckGo search, bounded)
  2. find IR page (common URL patterns + scan homepage links)
  3. find statement PDFs (financials/annual reports)
  4. download + parse -> statements into fundamentals.json (or a sidecar
     file to merge later)

Multi-threaded, resumable (state file), rate-limited. Run:
  python mass_ir_crawler.py --exchange JSE --limit 20
"""
import json, os, sys, time, re, urllib.request, urllib.parse, io, threading
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
BASE = os.path.dirname(os.path.abspath(__file__))
STOCKS = os.path.join(BASE, "stocks.json")
FUND = os.path.join(BASE, "fundamentals.json")
STATE = os.path.join(BASE, "ir_crawl_state.json")

sys.path.insert(0, BASE)
import ir_financials as ir

# ---- common IR page URL patterns (relative to site root) ----
IR_PATTERNS = [
    "/investor-relations", "/investors", "/investor", "/investors-shareholders",
    "/investor-relations/", "/investors/", "/investor-centre", "/shareholders",
    "/financial-information", "/financials", "/investor-center", "/investors/shareholders",
    "/about-us/investors", "/investor-relations/financial-results", "/ir",
]

def http_get(url, timeout=30, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8", "ignore")

def discover_website(company, exchange):
    """Find company website/IR/report PDF. Priority:
    1. Wikipedia infobox (official website or direct report PDF)
    2. Known URL patterns (<name>.co.za / .com)
    3. DuckDuckGo (fallback)
    """
    # 1. Wikipedia
    try:
        q = urllib.parse.quote(company.replace(" Ltd", "").replace(" Limited", "").replace(" Plc", "").replace(" PLC", "").replace(" Holdings", "").replace(" Group", "").strip())
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&format=json&srlimit=2"
        req = urllib.request.Request(url, headers=UA)
        d = json.loads(http_get(url, timeout=20))
        for hit in d.get("query", {}).get("search", []):
            title = hit["title"]
            # verify the article title is plausibly this company
            t_norm = re.sub(r"[^a-z0-9]", "", title.lower())
            c_norm = re.sub(r"[^a-z0-9]", "", company.lower())
            if not (c_norm[:8] in t_norm or t_norm[:8] in c_norm):
                continue  # wrong article
            purl = (f"https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content"
                    f"&rvslots=main&format=json&titles={urllib.parse.quote(title)}&rvsection=0")
            d2 = json.loads(http_get(purl, timeout=20))
            for pg in d2.get("query", {}).get("pages", {}).values():
                content = pg.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("*", "")
                for pat in [r"website\s*=\s*([^\n|}]+)", r"\|\s*url\s*=\s*([^\n|}]+)"]:
                    m = re.search(pat, content)
                    if m:
                        site = m.group(1).strip().replace("{{URL|", "").replace("}}", "").strip()
                        if site.startswith("http"):
                            return site
    except Exception:
        pass
    # 2. URL patterns
    short = re.sub(r"(Limited|Ltd|Plc|PLC|Holdings|Group|Incorporated|Inc|S\.A\.|Corporation|Corp|&|,|\s+)\b", "", company, flags=re.I)
    short = re.sub(r"[^A-Za-z0-9]", "", short).lower()
    for dom in [".co.za", ".com", ".africa"]:
        cand = f"https://www.{short}{dom}"
        try:
            r = urllib.request.Request(cand, headers=UA, method="HEAD")
            with urllib.request.urlopen(r, timeout=8) as resp:
                if resp.status == 200:
                    return cand
        except Exception:
            continue
    # 3. DuckDuckGo fallback
    try:
        q = urllib.parse.quote(f"{company} official website")
        t = http_get(f"https://html.duckduckgo.com/html/?q={q}", timeout=20)
        links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', t)
        for l in links[:4]:
            m = re.search(r'uddg=([^&]+)', l)
            url = urllib.parse.unquote(m.group(1)) if m else l
            if "duckduckgo" not in url and "facebook" not in url and "youtube" not in url:
                return url
    except Exception:
        pass
    return None

def find_ir_page(home_url):
    """Given a homepage, find the IR page: try patterns first, then scan links."""
    try:
        t = http_get(home_url, timeout=25)
    except Exception:
        return None
    # collect all internal links
    links = set()
    for m in re.finditer(r'href="([^"#]+)"', t):
        u = m.group(1)
        if u.startswith("/"):
            links.add(urllib.parse.urljoin(home_url, u))
        elif u.startswith("http"):
            links.add(u)
    # try known IR patterns
    host = urllib.parse.urlparse(home_url).netloc
    for pat in IR_PATTERNS:
        u = f"https://{host}{pat}"
        if u in links or True:
            try:
                r = urllib.request.Request(u, headers=UA, method="HEAD")
                with urllib.request.urlopen(r, timeout=10) as resp:
                    if resp.status == 200:
                        return u
            except Exception:
                continue
    # scan homepage links for IR-ish anchors
    for u in links:
        ul = u.lower()
        if any(k in ul for k in ["investor", "shareholder", "financial-report", "annual-report", "ir/"]):
            return u
    return None

def find_statement_pdfs(ir_url):
    """From an IR page, collect statement/report PDF links (up to 6)."""
    try:
        t = http_get(ir_url, timeout=25)
    except Exception:
        return []
    pdfs = []
    for m in re.finditer(r'href="([^"]+\.pdf[^"]*)"', t, re.I):
        u = m.group(1)
        ul = u.lower()
        if any(k in ul for k in ["financial", "statement", "annual", "report", "result", "signed"]):
            full = u if u.startswith("http") else urllib.parse.urljoin(ir_url, u)
            if full not in pdfs:
                pdfs.append(full)
        if len(pdfs) >= 6:
            break
    if not pdfs:
        # check for sub-pages linking to pdfs (financial-results page etc)
        sub = re.findall(r'href="([^"]*(?:financial|result|annual)[^"]*)"', t, re.I)
        for s in sub[:3]:
            if s.startswith("http") or s.startswith("/"):
                try:
                    t2 = http_get(s if s.startswith("http") else urllib.parse.urljoin(ir_url, s), timeout=20)
                    for m in re.finditer(r'href="([^"]+\.pdf[^"]*)"', t2, re.I):
                        u = m.group(1)
                        ul = u.lower()
                        if any(k in ul for k in ["financial", "statement", "annual", "signed", "result"]):
                            full = u if u.startswith("http") else urllib.parse.urljoin(ir_url, u)
                            if full not in pdfs:
                                pdfs.append(full)
                        if len(pdfs) >= 6:
                            break
                except Exception:
                    continue
    return pdfs

def process_company(ex, stock, state, lock):
    """One company: discover -> IR -> PDFs -> parse. Returns summary dict."""
    sym = stock.get("sym") or stock.get("ticker") or ""
    name = stock.get("name") or ""
    key = f"{ex}:{sym or name}"
    if key in state:
        return None  # already done
    result = {"key": key, "sym": sym, "name": name, "website": None, "ir": None, "pdfs": 0, "parsed": 0, "fields": 0}
    # 1. website
    site = discover_website(name, ex)
    if not site:
        result["error"] = "no website"
        with lock: state[key] = result
        return result
    result["website"] = site
    # direct PDF from discovery? parse immediately
    if site.lower().endswith(".pdf"):
        try:
            data = http_get(site, timeout=60, binary=True)
            if data[:5] == b"%PDF-":
                st = ir.parse_pdf_statements(data)
                if st:
                    result["parsed"] = 1
                    result["fields"] = len(st)
                    result["pdf"] = site
                    result["data"] = st
                    with lock: state[key] = result
                    return result
        except Exception:
            pass
    # 2. IR page
    ir_url = find_ir_page(site)
    if not ir_url:
        result["error"] = "no IR page"
        with lock: state[key] = result
        return result
    result["ir"] = ir_url
    # 3. PDFs
    pdfs = find_statement_pdfs(ir_url)
    result["pdfs"] = len(pdfs)
    # 4. parse the first good financial PDF
    for p in pdfs[:3]:
        try:
            data = http_get(p, timeout=60, binary=True)
            if data[:5] != b"%PDF-":
                continue
            st = ir.parse_pdf_statements(data)
            if st:
                result["parsed"] = 1
                result["fields"] = len(st)
                result["pdf"] = p
                result["data"] = st
                break
        except Exception:
            continue
    with lock: state[key] = result
    return result

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="JSE")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    db = json.load(open(STOCKS, encoding="utf-8"))
    stocks = db["stocks"][args.exchange]

    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            state = {}

    # prioritize: JSE/EGX live-priced first (they're liquid), then rest
    stocks_sorted = sorted(stocks, key=lambda s: 0 if s.get("price") is not None else 1)
    todo = stocks_sorted[:args.limit]

    lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(process_company, args.exchange, s, state, lock) for s in todo]
        for f in futs:
            r = f.result()
            if r:
                done += 1
                print(f"  [{done}/{len(todo)}] {r['name'][:35]:37s} website={r.get('website','-')[:40] if r.get('website') else '-':42s} ir={'Y' if r.get('ir') else 'N'} pdfs={r.get('pdfs',0)} parsed={r.get('fields',0)}f {r.get('error','')}")
                # checkpoint every few
                if done % 5 == 0:
                    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)

    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
    parsed = sum(1 for v in state.values() if v.get("parsed"))
    pdf_found = sum(1 for v in state.values() if v.get("pdfs"))
    print(f"\nDONE: {len(todo)} processed | websites {sum(1 for v in state.values() if v.get('website'))} | IR {sum(1 for v in state.values() if v.get('ir'))} | PDFs {pdf_found} | parsed {parsed}")

if __name__ == "__main__":
    main()
