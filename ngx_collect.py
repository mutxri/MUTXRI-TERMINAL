#!/usr/bin/env python3
"""Collect NGX financial statements from ngxgroup.com company profiles.

Usage:
    python ngx_collect.py <symbols_file> <out_dir> <pdf_dir> <manifest.csv> [--only SYM,...]

symbols_file: lines of "SYMBOL\tCompany Name" (tab-separated).
For each symbol: opens the ngxgroup company profile, finds the latest AUDITED annual
financial statement PDF, downloads it, and runs ngx_parse.py to produce the 3 JSON files.
Logs one line per symbol to the manifest: SYMBOL\tOK|FAIL\t<reason>\t<url>.
"""
import sys, os, re, csv, time, subprocess, urllib.request, ssl

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = "https://ngxgroup.com/exchange/data/company-profile/?symbol={sym}&directory=companydirectory"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def pick_pdf(links):
    """Choose the best audited annual statement link. Returns (url, title) or (None, None)."""
    bad = re.compile(r"notice|delay|extension|board approval|approval of|announcement|corporate action|suspension|interim|half[- ]year|six months|6 months|quarter|unaudited", re.I)
    cands = []
    for l in links:
        t, u = l["t"], l["h"]
        if not re.search(r"\.pdf(\?|$)", u, re.I):
            continue
        if bad.search(t):
            continue
        low = t.lower()
        if "financial statement" not in low and "afs" not in low:
            continue
        is_audited = "audit" in low or "afs" in low
        is_annual = bool(re.search(r"year|annual|december|dec\b|31st", low))
        if not (is_audited and is_annual):
            continue
        yr = max([int(m) for m in re.findall(r"20\d\d", t) if 1990 <= int(m) <= 2040], default=0)
        cands.append((is_audited, yr, t, u))
    if not cands:
        return None, None
    cands.sort(key=lambda x: (-x[0], -x[1]))
    return cands[0][3], cands[0][2]


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
        data = r.read()
    if len(data) < 5000 or data[:4] != b"%PDF":
        raise ValueError(f"not a PDF ({len(data)} bytes)")
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def main():
    syms_file, out_dir, pdf_dir, manifest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    rows = []
    with open(syms_file, encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if not ln.strip() or "\t" not in ln:
                continue
            sym, name = ln.split("\t", 1)
            rows.append((sym.strip(), name.strip()))
    if only:
        rows = [r for r in rows if r[0] in only]
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(pdf_dir, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
        PW = True
    except ImportError:
        PW = False

    done = set()
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            for ln in f:
                parts = ln.rstrip("\n").split("\t")
                if parts and parts[0] and len(parts) > 1 and parts[1].strip() == "OK":
                    done.add(parts[0])

    results = []

    def process_rows(page):
        for sym, name in rows:
            if sym in done:
                print(f"{sym}: skip (already in manifest)", flush=True)
                continue
            url = None
            try:
                if page is None:
                    raise RuntimeError("playwright unavailable")
                page.goto(PROFILE.format(sym=sym), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
                links = page.evaluate("""() => Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => /financial|statement|result|audit/i.test(a.textContent))
                    .map(a => ({t: a.textContent.trim().replace(/\\s+/g, ' '), h: a.href}))""")
                url, title = pick_pdf(links)
                if not url:
                    results.append((sym, "FAIL", "no audited annual PDF found", ""))
                    print(f"{sym}: FAIL no audited annual PDF", flush=True)
                    continue
                dest = os.path.join(pdf_dir, sym + ".pdf")
                download(url, dest)
                r = subprocess.run([sys.executable, os.path.join(HERE, "ngx_parse.py"), dest, sym, name, out_dir],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    results.append((sym, "OK", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", url))
                    print(f"{sym}: OK", flush=True)
                else:
                    results.append((sym, "FAIL", "parse produced no rows", url))
                    print(f"{sym}: FAIL parse ({r.stderr.strip()[:120]})", flush=True)
            except Exception as e:
                results.append((sym, "FAIL", str(e)[:120], url or ""))
                print(f"{sym}: FAIL {str(e)[:120]}", flush=True)
            time.sleep(0.5)

    if PW:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            process_rows(page)
            browser.close()
    else:
        process_rows(None)

    with open(manifest, "a", encoding="utf-8") as f:
        for sym, status, reason, url in results:
            f.write(f"{sym}\t{status}\t{reason}\t{url}\n")
    ok = sum(1 for r in results if r[1] == "OK")
    print(f"TOTAL: {len(results)} processed, {ok} OK")


if __name__ == "__main__":
    main()
