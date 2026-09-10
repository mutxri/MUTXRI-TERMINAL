import json, os, sys, time, urllib.request, urllib.parse, io

BASE = "D:/mutxri-terminal/static_data"
OUTDIR = os.path.join(BASE, "logos_img")
os.makedirs(OUTDIR, exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
SEARCH_HDRS = {
    "User-Agent": UA,
    "Referer": "https://www.tradingview.com/",
    "Origin": "https://www.tradingview.com",
    "Accept": "application/json",
}
DL_HDRS = {"User-Agent": UA}

def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return r.status, r.headers, data
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except Exception as e:
        return None, None, b""

def tv_search(q):
    url = "https://symbol-search.tradingview.com/symbol_search/?text=" + urllib.parse.quote(q) + "&type=stock&hl=1&lang=en"
    st, hd, body = http_get(url, headers=SEARCH_HDRS)
    if st != 200 or not body:
        return []
    try:
        return json.loads(body.decode("utf-8", "ignore"))
    except Exception:
        return []

def is_png(buf):
    return buf[:8] == b"\x89PNG\r\n\x1a\n" and len(buf) > 500

def download_logo(logoid, dest):
    for suffix in ("--600.png", ".png"):
        url = f"https://s3-symbol-logo.tradingview.com/{logoid}{suffix}"
        st, hd, body = http_get(url, headers=DL_HDRS)
        if st == 200 and is_png(body):
            with open(dest, "wb") as f:
                f.write(body)
            return url
    return None

def clean_sym(s):
    s = s.replace(".", "_").replace(" ", "_")
    return s

with open(os.path.join(BASE, "_logo_missing_final.json"), encoding="utf-8") as f:
    data = json.load(f)

entries = data[59:]
results = []

for e in entries:
    sym = e["sym"]
    name = e["name"]
    exchange = e["exchange"]
    fname = clean_sym(sym) + ".png"
    dest = os.path.join(OUTDIR, fname)
    rec = {"sym": sym, "found": False, "filename": None, "source_url": None}
    logoid = None
    match_item = None

    # Build candidate search queries
    queries = []
    if sym.startswith("EGS"):
        isin = sym[:-3] if sym.endswith(".CA") else sym
        queries.append(isin)
    # plain ticker (strip exchange suffix)
    ticker = sym.split(".")[0]
    queries.append(ticker)
    queries.append(name)

    # special overrides for hard cases
    special = {
        "AIA.JO": ["AIA Ascension Properties", "Ascension Properties"],
        "AWT.JO": ["Awethu Breweries", "AWT"],
        "DAW.JO": ["Distribution And Warehousing Network", "DAW"],
        "ABBEYBDS": ["Abbey Mortgage Bank", "Abbey"],
        "AREDEL": ["Aredel Nigeria", "Aredel"],
        "GOLDBREW": ["Golden Guinea Breweries", "GOLDBREW"],
        "INTERBREW": ["International Breweries", "INTERBREW"],
        "MOFI REIF": ["MOFI REIF", "MOFI Real Estate"],
        "TRANS EXPRESS": ["Trans Nationwide Express", "TRANS EXPRESS"],
        "WAPCO": ["Lafarge Africa", "WAPCO", "HBM Nigeria"],
        "NBV": ["Nairobi Business Ventures", "NBV"],
        "MMHC.CA": ["El Mamoura", "MMHC"],
        "SLTD.CA": ["Sky Light", "SLTD"],
    }
    if sym in special:
        queries = special[sym] + queries

    for q in queries:
        if not q:
            continue
        items = tv_search(q)
        for it in items:
            it_sym = (it.get("symbol") or "").upper()
            it_isin = (it.get("isin") or "").upper()
            it_desc = (it.get("description") or "").upper()
            # For EGX, prefer isin match
            if sym.startswith("EGS"):
                target_isin = (sym[:-3] if sym.endswith(".CA") else sym).upper()
                if it_isin == target_isin:
                    match_item = it
                    break
            else:
                target_t = ticker.upper()
                if it_sym == target_t:
                    match_item = it
                    break
        if match_item:
            break

    if match_item:
        logoid = match_item.get("logoid") or (match_item.get("logo") or {}).get("logoid")

    if logoid:
        url = download_logo(logoid, dest)
        if url:
            # verify with PIL
            try:
                from PIL import Image
                im = Image.open(dest)
                im.verify()
                rec["found"] = True
                rec["filename"] = fname
                rec["source_url"] = url
            except Exception:
                rec["found"] = False
                if os.path.exists(dest):
                    os.remove(dest)

    results.append(rec)
    print(json.dumps(rec), flush=True)
    time.sleep(0.4)

outpath = os.path.join(BASE, "_logo_fetch_results_last58.json")
with open(outpath, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=1)
print("WROTE", outpath)
print("FOUND", sum(1 for r in results if r["found"]), "/", len(results))
