#!/usr/bin/env python3
"""nse_collect.py - full NSE (Nairobi) official audited-annual financial statement run.

Source: nse.co.ke listed-company-announcements (WordPress admin-ajax 'list_dwnlds'
feed, newest-first, 8 rows/page). For every NSE symbol from listing_NSE.json:
find its newest AUDITED ANNUAL statement PDF in the feed (by company-name match),
download it, and run ngx_parse.py to produce the 3 standardized JSON files.

Usage:
    python nse_collect.py [--max-pages N] [--only SYM,...]

Writes:
    _nse_pdf/<SYM>.pdf            downloaded statements
    _nse_out/<SYM>__{income,balance,cashflow}.json   parsed rows
    _nse_manifest.csv             SYMBOL<TAB>OK|FAIL<TAB>reason<TAB>url
Resume: symbols already marked OK (or with >=2 parsed JSONs) are skipped.
"""
import sys, os, re, csv, json, time, subprocess, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ANNOUNCE = "https://www.nse.co.ke/listed-company-announcements/"
AJAX = "https://www.nse.co.ke/wp-admin/admin-ajax.php"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "X-Requested-With": "XMLHttpRequest"}
PDF_DIR = os.path.join(HERE, "_nse_pdf")
OUT_DIR = os.path.join(HERE, "_nse_out")
MANIFEST = os.path.join(HERE, "_nse_manifest.csv")

GENERIC = {"plc", "limited", "ltd", "company", "co", "corporation", "corp",
           "group", "holdings", "holding", "international", "kenya", "east",
           "african", "the", "and", "of", "for", "investments", "investment"}

BAD_TITLE = re.compile(r"unaudited|interim|quarter|six months|6 months|9 months|nine months|half[- ]year|hy\b|notice|delay|extension|board approval|corporate action|suspension|press release|media statement|dividend|annual report|agm|egm|prospectus|rights issue|buyback|bonds?\b|results presentation", re.I)
GOOD_TITLE = re.compile(r"audited|afs\b|audit|year ended|year-end|financial statements? for the year|full year|annual results|financial results? for the year", re.I)
YEAR_RE = re.compile(r"(20\d\d)")


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


def fetch(u, data=None, timeout=40):
    req = urllib.request.Request(u, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_nonce():
    req = urllib.request.Request(ANNOUNCE, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        h = r.read().decode("utf-8", "replace")
    m = re.search(r'var wp_ajax = \{.*?"ajaxnonce":"([a-f0-9]+)".*?"nse_id":"(\d+)"', h, re.S)
    if not m:
        raise RuntimeError("nonce not found on announcements page")
    return m.group(1), m.group(2)


def feed_page(page, nonce, nse_id):
    d = urllib.parse.urlencode({"page": str(page), "action": "list_dwnlds",
                                "security": nonce, "nse_id": nse_id, "limit": "",
                                "tags": "All", "expiry": ""}).encode()
    body = fetch(AJAX, data=d).decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]+\.pdf[^"]*)"', body, re.I)
    return hrefs


def candidate_from_url(u):
    """Decide audited-annual candidacy + year from the URL slug. Returns (ok, year)."""
    name = urllib.parse.unquote(u.split("/")[-1])
    name = name.replace("\u2013", "-").replace("\u2014", "-").replace("_", " ")
    stem = os.path.splitext(name)[0]
    if BAD_TITLE.search(stem):
        return False, 0
    if not GOOD_TITLE.search(stem):
        return False, 0
    yrs = [int(y) for y in YEAR_RE.findall(stem) if 1990 <= int(y) <= 2040]
    return True, max(yrs) if yrs else 0


def match_symbol(name_tokens, sym, company_name):
    """Score a filename against one company. Returns match score."""
    ct = [w for w in norm(company_name) if w not in GENERIC]
    if not ct:
        return 0.0
    nt = set(name_tokens)
    if sym.lower() in nt:
        return 1.0  # ticker literally in the filename (EABL, KCB, BAT...)
    hit = sum(1 for w in ct if w in nt)
    if len(ct) == 1:
        return 1.0 if (hit == 1 and len(ct[0]) >= 2) else 0.0
    return hit / len(ct)


def load_symbols():
    d = json.load(open(os.path.join(HERE, "static_data", "listing_NSE.json"), encoding="utf-8"))
    return [(x.get("sym") or x["ticker"], x["name"]) for x in d["stocks"]]


def done_set():
    done = set()
    if os.path.exists(MANIFEST):
        for row in csv.reader(open(MANIFEST, encoding="utf-8"), delimiter="\t"):
            if len(row) >= 2 and row[1] == "OK":
                done.add(row[0])
    if os.path.isdir(OUT_DIR):
        for f in os.listdir(OUT_DIR):
            m = re.match(r"^([A-Z0-9.]+)__(income|balance|cashflow)\.json$", f)
            if m:
                done.add(m.group(1))
    return done


def download(url, dest):
    enc = urllib.parse.quote(url, safe=":/?&=%")
    for attempt in range(3):
        try:
            body = fetch(enc)
            if body[:5] == b"%PDF-" or b"%PDF" in body[:100]:
                open(dest, "wb").write(body)
                return True
        except Exception:
            time.sleep(2)
    return False


def parse_one(sym, name, pdf):
    r = subprocess.run([sys.executable, os.path.join(HERE, "ngx_parse.py"),
                        pdf, sym, name, OUT_DIR], capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        return "FAIL parse: " + (r.stderr or r.stdout or "").strip()[:160]
    outs = [f for f in os.listdir(OUT_DIR) if f.startswith(sym + "__")]
    if len(outs) < 2:
        return "FAIL few-rows: " + (r.stdout or "").strip()[:160]
    return "OK"


def main():
    args = sys.argv[1:]
    max_pages = 90
    only = None
    i = 0
    while i < len(args):
        if args[i] == "--max-pages":
            max_pages = int(args[i + 1]); i += 2
        elif args[i] == "--only":
            only = set(args[i + 1].split(",")); i += 2
        else:
            i += 1

    os.makedirs(PDF_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    nonce, nse_id = get_nonce()
    print(f"nonce={nonce} nse_id={nse_id}", flush=True)

    syms = [(s, n) for s, n in load_symbols() if (not only) or s in only]
    done = done_set()
    todo = [(s, n) for s, n in syms if s not in done]
    print(f"symbols: {len(syms)} todo: {len(todo)} done: {len(syms) - len(todo)}", flush=True)
    if not todo:
        return

    matched = {}   # sym -> (url, year)
    empty_pages = 0
    pages = 0
    while pages < max_pages and len(matched) < len(todo) and empty_pages < 8:
        pages += 1
        hrefs = feed_page(pages, nonce, nse_id)
        if not hrefs:
            empty_pages += 1
            continue
        annual_here = 0
        new_this_page = 0
        for u in hrefs:
            ok, yr = candidate_from_url(u)
            if not ok:
                continue
            annual_here += 1
            tokens = norm(urllib.parse.unquote(u.split("/")[-1]).replace("\u2013", "-"))
            best, best_score = None, 0.0
            for s, n in todo:
                if s in matched:
                    continue
                sc = match_symbol(tokens, s, n)
                if sc > best_score:
                    best, best_score = s, sc
            if best and best_score >= 0.6:
                if best not in matched or yr > matched[best][1]:
                    matched[best] = (u, yr)
                    new_this_page += 1
        if new_this_page == 0 and annual_here == 0:
            empty_pages += 1
        else:
            empty_pages = 0
        if pages % 5 == 0:
            print(f"page {pages}: matched {len(matched)}/{len(todo)}", flush=True)

    print(f"feed scan done at page {pages}; matched {len(matched)}/{len(todo)}", flush=True)
    for s, n in todo:
        if s not in matched:
            with open(MANIFEST, "a", encoding="utf-8") as mf:
                mf.write(f"{s}\tFAIL\tno audited-annual PDF in feed\t\n")
            print(f"  {s}: NO MATCH", flush=True)

    for s, n in todo:
        if s not in matched:
            continue
        u, yr = matched[s]
        pdf = os.path.join(PDF_DIR, f"{s}.pdf")
        if not download(u, pdf):
            with open(MANIFEST, "a", encoding="utf-8") as mf:
                mf.write(f"{s}\tFAIL\tdownload failed\t{u}\n")
            print(f"  {s}: DOWNLOAD FAIL", flush=True)
            continue
        res = parse_one(s, n, pdf)
        with open(MANIFEST, "a", encoding="utf-8") as mf:
            mf.write(f"{s}\t{res.split()[0]}\t{res}\t{u}\n")
        print(f"  {s}: {res} ({yr})", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
