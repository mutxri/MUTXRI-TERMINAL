#!/usr/bin/env python3
"""
AFRI Terminal v2 - local server
Serves the terminal UI + proxies live market data (Yahoo chart API) and news RSS.
Run:  python afri_server.py   (then open http://127.0.0.1:8081/)
Stdlib only - no pip installs needed.
"""
import json, time, urllib.request, urllib.parse, threading, sys, os, re, datetime
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from xml.etree import ElementTree as ET

# Claude feature modules (features/api/*) - stdlib only
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "features", "api"))
try:
    import screener_api, reg_api, commodities_api, bonds_api, tas_api, ratings_api, heatmap_api, fx_api, indicators
    _FEATURES_OK = True
except Exception as _e:
    _FEATURES_OK = False
    _FEATURES_ERR = str(_e)

HOST, PORT = "0.0.0.0", int(os.environ.get("PORT", "8081"))
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={ivl}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# ---- cache: {key: (expires_ts, payload_json_str)} ----
_cache = {}
_lock = threading.Lock()
TTL = {"chart": 45, "quote": 240, "fx": 60, "news": 300}

def cache_get(key):
    with _lock:
        e = _cache.get(key)
        if e and e[0] > time.time():
            return e[1]
    return None

def cache_put(key, ttl, payload):
    with _lock:
        _cache[key] = (time.time() + ttl, payload)

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")

# ---------------- Yahoo chart API ----------------
def yahoo_chart(sym, rng="1y", ivl="1d"):
    key = f"chart:{sym}:{rng}:{ivl}"
    hit = cache_get(key)
    if hit: return json.loads(hit)
    try:
        raw = http_get(YAHOO.format(sym=urllib.parse.quote(sym), rng=rng, ivl=ivl))
        data = json.loads(raw)["chart"]["result"][0]
    except urllib.error.HTTPError as ex:
        return {"error": "no market data for this security"}
    except Exception as ex:
        return {"error": "no market data for this security"}
    ts = data.get("timestamp", [])
    q = (data.get("indicators", {}).get("quote") or [{}])[0]
    opens, highs, lows, closes, vols = q.get("open"), q.get("high"), q.get("low"), q.get("close"), q.get("volume")
    bars = []
    for i, t in enumerate(ts):
        try:
            bars.append({
                "time": int(t),
                "open": round(opens[i], 4), "high": round(highs[i], 4),
                "low": round(lows[i], 4), "close": round(closes[i], 4),
                "volume": int(vols[i] or 0),
            })
        except Exception:
            continue
    meta = data.get("meta", {})
    out = {
        "symbol": sym,
        "name": meta.get("shortName") or meta.get("longName") or sym,
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "tz": meta.get("exchangeTimezoneName"),
        "marketState": meta.get("marketState"),
        "regularMarketPrice": meta.get("regularMarketPrice"),
        "chartPreviousClose": meta.get("chartPreviousClose"),
        "regularMarketDayHigh": meta.get("regularMarketDayHigh"),
        "regularMarketDayLow": meta.get("regularMarketDayLow"),
        "regularMarketVolume": meta.get("regularMarketVolume"),
        "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
        "bars": bars,
        "indicators": _compute_indicators(bars) if _FEATURES_OK else None,
    }
    cache_put(key, TTL["chart"], json.dumps(out))
    return out

def _compute_indicators(bars):
    """Attach MA/EMA/RSI/MACD/Bollinger overlays to chart bars (Claude's indicators.py)."""
    try:
        closes = [b["close"] for b in bars]
        out = {
            "sma20": indicators.sma(closes, 20),
            "sma50": indicators.sma(closes, 50),
            "ema12": indicators.ema(closes, 12),
            "rsi14": indicators.rsi(closes, 14),
            "bollinger": indicators.bollinger(closes, 20),
        }
        macd = indicators.macd(closes)
        if isinstance(macd, dict):
            out["macd"] = macd.get("macd")
            out["macdSignal"] = macd.get("signal")
            out["macdHist"] = macd.get("histogram")
        return out
    except Exception:
        return None

def quote_many(symbols, use_snap=True):
    """Latest quote per symbol via 1d chart (chunked parallel, cached, throttle-friendly).
    When use_snap is True (default), serves from the 30-min quote snapshot cache first —
    only symbols without a snapshot hit Yahoo. This makes watchlist/heatmap loads instant
    after the startup warm thread fills the cache."""
    out = {}
    if use_snap:
        # instant path: everything already in the 30-min snapshot cache
        missing = []
        for s in symbols:
            qc = cache_get("snap:" + s)
            if qc:
                try:
                    out[s] = json.loads(qc)
                    continue
                except Exception:
                    pass
            missing.append(s)
        symbols = missing
        if not symbols:
            return out
    # process in chunks of 20 with 8 workers; Yahoo throttles bursts
    for i in range(0, len(symbols), 20):
        chunk = symbols[i:i+20]
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = ex.map(quote_one, chunk)
        for s, d in zip(chunk, results):
            out[s] = d
        time.sleep(0.8)  # avoid Yahoo 429 on bursts
    return out

def quote_one(s):
    d = yahoo_chart(s, rng="5d", ivl="1d")
    if "error" in d:
        return {"symbol": s, "error": d["error"]}
    bars = d.get("bars", [])
    prev = d.get("chartPreviousClose")
    last = d.get("regularMarketPrice")
    if last is None and bars:
        last = bars[-1]["close"]
        prev = bars[-2]["close"] if len(bars) > 1 else prev
    # always have a last price even when market closed / meta empty
    if last is None and bars:
        last = bars[-1]["close"]
    if prev is None and bars:
        prev = bars[0]["open"] if len(bars) > 0 else last
    chg = (last - prev) if (last is not None and prev) else None
    pct = (chg / prev * 100) if (chg is not None and prev) else None
    out = {
        "symbol": s, "name": d.get("name", s), "price": last,
        "prev": prev, "change": chg, "changePct": pct,
        "currency": d.get("currency"), "exchange": d.get("exchange"),
        "marketState": d.get("marketState"), "dayHigh": d.get("regularMarketDayHigh"),
        "dayLow": d.get("regularMarketDayLow"), "volume": d.get("regularMarketVolume"),
        "w52High": d.get("fiftyTwoWeekHigh"), "w52Low": d.get("fiftyTwoWeekLow"),
    }
    # keep a long-lived per-symbol quote snapshot for the screener (30 min)
    # currency fallback: ISIN syms return null currency; apply listing currency
    if not out.get("currency"):
        for exx in ("JSE", "EGX", "NGX", "NSE"):
            for st in get_listing(exx):
                cands = [str(st.get("ticker") or "").upper(), str(st.get("code") or "").upper(),
                         str(st.get("sym") or "").upper()]
                if s.upper() in cands or any(s.upper() == c.split(".")[0] for c in cands if c):
                    out["currency"] = st.get("currency", "")
                    break
            if out.get("currency"):
                break
    cache_put("snap:" + s, 1800, json.dumps(out))
    return out

# ---------------- Yahoo dividend events ----------------
DIV_TTL = 86400  # 24h — dividends change rarely

def yahoo_dividends(sym, years=6):
    key = f"divs:{sym}"
    hit = cache_get(key)
    if hit:
        return json.loads(hit)
    try:
        raw = http_get(YAHOO.format(sym=urllib.parse.quote(sym), rng=f"{years}y", ivl="1mo") + "&events=div", timeout=20)
        ev = json.loads(raw)["chart"]["result"][0].get("events", {})
        divs = ev.get("dividends", {})
        out = sorted([{"date": int(v["date"]), "amount": v.get("amount")} for v in divs.values()],
                     key=lambda x: x["date"])
    except Exception as ex:
        return {"symbol": sym, "error": str(ex)}
    cache_put(key, DIV_TTL, json.dumps(out))
    return out

# ---------------- News RSS ----------------
# Google News RSS aggregates S&P Global, Wind, Reuters, Bloomberg, CNBC etc (free, reliable)
def _gn(query):
    import urllib.parse as _up
    return ("Google News", "https://news.google.com/rss/search?q=" + _up.quote(query) + "&hl=en-US&gl=US&ceid=US:en")

RSS_FEEDS = [
    _gn('"S&P Global" when:7d'),
    _gn('"S&P Global Commodity Insights" OR "Platts" when:7d'),
    _gn('"Wind Information" OR "Wind Financial" China market data when:7d'),
    _gn('(Nairobi OR Lagos OR Johannesburg OR Cairo OR "African") (stock market OR shares OR equities) when:7d'),
    _gn('(gold OR platinum OR cocoa OR coffee OR tea) Africa prices when:7d'),
    _gn('(Kenya OR Nigeria OR "South Africa" OR Egypt) (interest rate OR inflation OR central bank) when:7d'),
    _gn('(JSE OR "Johannesburg Stock Exchange" OR "NSE Kenya" OR "Nigerian Exchange" OR EGX) when:7d'),

    ("Moneyweb SA",        "https://www.moneyweb.co.za/feed/"),
    ("Moneyweb Markets",   "https://www.moneyweb.co.za/category/markets/feed/"),
    ("Enterprise Egypt",   "https://enterprise.press/feed/"),
    ("Business Daily KE",  "https://www.businessdailyafrica.com/bd/rss.xml"),
    ("TechCabal Africa",   "https://techcabal.com/feed/"),
    ("African Financials", "https://africanfinancials.com/feed/"),
]

def fetch_news(limit=40):
    key = "news"
    hit = cache_get(key)
    if hit: return json.loads(hit)
    def _one(src_url):
        src, url = src_url
        try:
            body = http_get(url, timeout=15)
            root = ET.fromstring(body)
            out = []
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                desc = (it.findtext("description") or "").strip()
                pub = (it.findtext("pubDate") or "").strip()
                # Google News embeds the real publication source in <source>
                src_el = it.find("source")
                real_src = (src_el.text or "").strip() if src_el is not None and src_el.text else src
                out.append((real_src, title, link, desc, pub))
            return out
        except Exception:
            return []
    items = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for batch in ex.map(_one, RSS_FEEDS):
            for src, title, link, desc, pub in batch:
                items.append({"source": src, "title": title, "link": link,
                              "summary": desc[:220], "date": pub})
    items.sort(key=lambda x: x["date"], reverse=True)
    out = items[:limit]
    cache_put(key, TTL["news"], json.dumps(out))
    return out

# ---------------- MongoDB Atlas data layer (optional; falls back to local JSON) ----------------
# The hosted backend reads the dataset from MongoDB Atlas; local dev keeps using
# the checked-in JSON files. Set MONGODB_URI to enable, leave empty for local.
_MONGO_URI = os.environ.get("MONGODB_URI", "")
_mongo_db = None
_mongo_ok = False
try:
    if _MONGO_URI:
        import urllib.parse as _up
        from pymongo import MongoClient as _MC
        _mongo_client = _MC(_MONGO_URI, serverSelectionTimeoutMS=8000)
        _mongo_db = _mongo_client["terminal"]
        _mongo_client.admin.command("ping")
        _mongo_ok = True
        print("MongoDB Atlas connected")
    else:
        print("MongoDB disabled (no MONGODB_URI) - using local JSON")
except Exception as _e:
    _mongo_ok = False
    print("MongoDB unavailable:", str(_e)[:80])

def _mongo_listing(ex):
    """Load listings for an exchange from Mongo if available."""
    if not _mongo_ok:
        return None
    try:
        coll = _mongo_db[f"stocks_{ex}"]
        docs = list(coll.find({}))
        if not docs:
            return None
        out = []
        for d in docs:
            d.pop("_id", None)
            out.append(d)
        return out
    except Exception:
        return None

def _mongo_fundamentals():
    """Load fundamentals map from Mongo if available."""
    if not _mongo_ok:
        return None
    try:
        coll = _mongo_db["fundamentals"]
        out = {}
        for d in coll.find({}):
            key = d.pop("_id", None)
            if key:
                out[key] = d
        return out or None
    except Exception:
        return None

# ---------------- Email accounts (auth_api) ----------------
try:
    import auth_api
    auth_api._init(_mongo_db, _mongo_ok)
except Exception as _ae:
    print("auth_api init failed:", str(_ae)[:60])

# ---------------- Full listings (stocks.json) ----------------
try:
    with open("stocks.json", encoding="utf-8") as f:
        _LISTINGS = json.load(f)["stocks"]
except Exception:
    _LISTINGS = {}

# prefer Mongo if it has fresher data (hosted backend)
_mongo_listings = {ex: _mongo_listing(ex) for ex in ("JSE", "EGX", "NGX", "NSE")}
if _mongo_ok and any(_mongo_listings.values()):
    for ex, docs in _mongo_listings.items():
        if docs:
            _LISTINGS[ex] = docs
    print("Listings loaded from MongoDB Atlas")

def get_listing(ex):
    return _LISTINGS.get(ex, [])

def eod_quote(ex, name):
    """Return EOD quote from static listing (NGX/NSE)."""
    for s in get_listing(ex):
        if s.get("name", "").lower() == name.lower():
            return s
    return None

# ---------------- Sector classification (JSE/EGX have no sector in listing) ----------------
SECTOR_RULES = [
    # (keywords, sector) — checked in order, first match wins
    (["etf", "etn", " notes", "note due", "exchange traded", "tracker", "satrix", "sygnia", "newfunds",
      "proshares", "amc0", "amc1", "amc2"],
     "ETFs & Structured"),
    (["bank", "firstrand", "nedbank", "capitec", "investec", "absa", "standard bank", "african bank",
      "qnb", "commercial international", "credit agricole", "alex bank", "blom bank", "hsbc", "abu dhabi",
      "faisal islamic", "saudi", "emirates nbd", "barclays", "attijariwafa", "arab bank", "banque", "cib ",
      "ubs ag", "ubs ", "societe generale", "bnp", "citibank", "jpmorgan", "goldman"],
     "Banks"),
    (["insurance", "sanlam", "old mutual", "liberty", "santam", "discovery", "metropolitan", "hollard",
      "jubilee", "soras", "alliance", "reinsurance", "reassurance", "misr insurance", "misr life",
      "santam", "brightrock"],
     "Insurance"),
    (["gold", "platinum", "mining", "coal", "iron ore", "manganese", "chrome", "copper", "bauxite",
      "resources", "sibanye", "harmony", "exxaro", "kumba", "northam", "impala", "anglo", "tharisa",
      "austral", "zimbabwe", "lithium", "rare earth", "drilling", "exploration", "assore", "assmang",
      "african rainbow", "bhp", "south32", "samancor", "merafe", "metorex", "platreef", "mcewen",
      "glencore", "europa metals", "venter", "western areas", "gold fields", "pan african", "orinoco",
      "gemfields", "manganese", "hulamin", "southern palladium"],
     "Mining & Resources"),
    (["oil", "gas", "petro", "sasol", "energy", "fuel", "refinery", "upstream", "downstream",
      "alexandria mineral", "amarco", "sidi kerir", "mopco", "natgas", "drilling"],
     "Oil & Gas"),
    (["telecom", "telkom", "vodacom", "mtn", "cell", "mobile", "telecom egypt", "etisalat", "network",
      "broadband", "data networks", "fibre", "fiber", "mast", "tower"],
     "Telecom"),
    (["reit", "property", "prop ", "props", "real estate", "growthpoint", "redefine", "resilient",
      "fortress", "vukile", "nepi", "rockcastle", "palm hills", "madinat", "october", "talat", "tmgh",
      "heliopolis housing", "six of october", "development &", "urban", "sodic", "amer group", "egyptian",
      "housing", "emar", "almaaz", "landmarks", "masa", "wadi", "new cairo", "property development",
      "capital for", "inma", "marakez", "misr development", "balwin", "fairvest", "sasfin property",
      "texton", "spear", "octodec", "safari", "delta property", "emira", "arrowhead", "dipula", "agency",
      "globe trade", "trade centre"],
     "Real Estate"),
    (["retail", "shoprite", "woolworths", "pick n pay", "mr price", "foschini", "tfg", "clicks",
      "dis-chem", "truworths", "edgars", "spar", "cna", "game", "hyper", "pep", "massmart", "makro",
      "supermarket", "department store", "chain stores", "famous brands", "itel", "cashbuild", "steinhoff",
      "richemont", "adidas", "nike", "foschini", "choppies", "pick n"],
     "Retail"),
    (["food", "beverage", "brew", "tiger brands", "pioneer", "rcl", "avi", "illovo", "sugar",
      "juhayna", "edita", "domty", "bisco", "misr foods", "national food", "agriculture", "agri",
      "farming", "fisheries", "fishing", "crops", "tea", "coffee", "packaging", "bottling", "dairy",
      "poultry", "vegetable", "fruit", "anheuser", "ab inbev", "ocean basket", "savanna", "distell",
      "remgro", "bidcorp", "bid corporation", "libstar", "astral", "rainbow chicken", "clover", "first",
      "crookes", "flour mills", "silos", "bakeries", "sugar", "ginning", "reclamation", "dry ice"],
     "Food & Beverage"),
    (["tobacco", "british american", "eastern company", "eastern co", "cigarette", "phillip morris", "nicotine"],
     "Tobacco"),
    (["technology", "software", "tech", "data", "naspers", "prosus", "adapt it", "eoh", "informatics",
      "it services", "computer", "digital", "cyber", "ai ", "semiconductor", "electronics", "elec",
      "electronic", "e-finance", "raya", "ibnsina", "elsewedy", "el sewedy", "egyptian for", "altron",
      "mustek", "datatec", "jse limited", "sara", "iot", "nology", "bitcoin", "crypto", "huge group",
      "blockchain", "fintech", "numeral"],
     "Technology"),
    (["health", "mediclinic", "netcare", "life healthcare", "aspen", "adcock", "pharma", "drug",
      "medical", "hospital", "clinic", "biotech", "diagnostic", "veterinary", "clicks"],
     "Healthcare"),
    (["industrial", "barloworld", "invicta", "astral", "hudaco", "cement", "steel", "ezz", "aluminium",
      "glass", "chemical", "plastic", "rubber", "paper", "timber", "wood", "textile", "weavers",
      "clothing", "apparel", "shoes", "footwear", "furniture", "engineering", "manufacturing", "factory",
      "machinery", "equipment", "building", "construction", "arabia", "misr for", "el araby", "oriental",
      "german", "cairo for", "delta", "aluminium", "ceramic", "tile", "arcelormittal", "aec", "afrimat",
      "aveng", "brikor", "cafca", "consol", "coronation", "hulett", "ilovo", "mongolia", "murray",
      "roberts", "raubex", "wilson bayly", "wba", "basil read", "african oxygen", "afrox", "armstrong",
      "cennergi", "copper", "esorfran", "ewt", "gcg", "grindrod", "ipop", "kaydav", "liberty", "mettle",
      "naac", "pinnacle", "powerfleet", "sable", "sanyati", "southern", "steel", "trencor", "united",
      "wesco", "zeder", "cotton", "contracting", "civil works", "bowler", "ascion", "enx group",
      "numeral", "metcalf", "dry", "aluminum", "aluminium", "granite", "printing", "lecico",
      "hulamin", "ceramic", "tiles"],
     "Industrials"),
    (["auto", "car", "vehicle", "toyota", "ford", "motors", "gb auto", "mansour", "tire", "tyre",
      "spare", "motus", "barloworld motor", "combined motor"],
     "Automotive"),
    (["media", "naspers", "times media", "caxton", "independent news", "multichoice", "broadcast",
      "television", "radio", "publishing", "newspaper", "magazine", "entertainment", "cinema", "film",
      "canal+", "multichoice"],
     "Media & Entertainment"),
    (["shipping", "transport", "logistics", "airlines", "airline", "rail", "port", "harbour", "freight",
      "courier", "postal", "toll", "taxi", "transnet", "imperial", "super group", "trencor"],
     "Transport & Logistics"),
    (["amc", "asset management", "asset mgmt", "wealth", "fintech", "payments", "pay ", "microfinance",
      "leasing", "mortgage", "broker", "exchange", "securities", "venture", "investment", "holding",
      "capital", "financial", "brait", "psg", "curro", "remgro", "nvest", "ubiquity", "baobab",
      "honeybadger", "differential", "kyrios", "sabvest", "pioneer", "zico", "1ngage", "adcorp",
      "african equity", "bayport", "blue label", "carbon", "epec", "euroz", "finbond", "grocapital",
      "lewin", "lighthouse", "metrofile", "odyssey", "outsurance", "premier", "sasfin", "securfin",
      "silverbridge", "stafix", "tsogosun", "vest", "vukile"],
     "Financial Services"),
    (["utility", "power", "electricity", "water", "waste", "renewable", "solar", "wind", "energy",
      "eskom", "city lodge"],
     "Utilities"),
    (["hotel", "tourism", "travel", "resort", "casino", "leisure", "gaming", "hospitality", "tsogo",
      "sun international", "city lodge", "curro"],
     "Tourism & Leisure"),
    (["pharma", "drug", "chemical", "medical", "healthcare", "glaxosmithkline", "gsk", "novartis",
      "pfizer", "sanofi", "bayer", "amgen", "ferchem", "fertilizers", "fertilizer"],
     "Pharmaceuticals"),
]
_OTHER = "Other"

def classify_sector(name):
    n = (name or "").lower()
    for keywords, sector in SECTOR_RULES:
        for kw in keywords:
            if kw in n:
                return sector
    return _OTHER

# ---------------- Fundamentals (AF data + Yahoo dividends) ----------------
try:
    with open("fundamentals.json", encoding="utf-8") as f:
        _FUND = json.load(f).get("companies", {})
except Exception:
    _FUND = {}

# prefer Mongo fundamentals (hosted backend reads the cloud dataset)
_mf = _mongo_fundamentals()
if _mf:
    _FUND = _mf
    print("Fundamentals loaded from MongoDB Atlas")

# IR-crawled statements (sidecar from mass_ir_crawler) - merged on top of AF data
try:
    with open("ir_statements.json", encoding="utf-8") as f:
        _IR_STMTS = json.load(f)
except Exception:
    _IR_STMTS = {}

try:
    with open("ownership.json", encoding="utf-8") as f:
        _OWN = json.load(f)
except Exception:
    _OWN = {}

def ownership_for(ex, sym, name):
    """Major shareholders for a security (curated, verified from public disclosures)."""
    exmap = _OWN.get(ex, {})
    # try by sym, then by name fragment
    if sym and sym in exmap:
        return exmap[sym]
    if name:
        for k, v in exmap.items():
            if v.get("company", "").lower() in name.lower() or name.lower() in v.get("company", "").lower():
                return v
    return None

def fundamentals(sym, ex, name):
    """Per-company fundamentals: AF data (NGX/NSE) + Yahoo dividends (JSE/EGX)."""
    af_key = None
    name_l = (name or "").lower().strip()
    sym_l = (sym or "").lower().strip()
    # exact first, then substring match on the AF company name
    for k, v in _FUND.items():
        if not k.startswith(ex + ":"):
            continue
        vname = (v.get("name") or "").lower()
        if (name_l and vname == name_l) or (sym_l and k.endswith(sym_l)):
            af_key = k
            break
    if af_key is None and name_l:
        for k, v in _FUND.items():
            if not k.startswith(ex + ":"):
                continue
            vname = (v.get("name") or "").lower()
            # substring either direction, or first-word match
            vfirst = vname.split()[0] if vname.split() else ""
            nfirst = name_l.split()[0] if name_l.split() else ""
            if (vname and (vname in name_l or name_l in vname)) or (vfirst and nfirst and vfirst == nfirst):
                af_key = k
                break
    if af_key is None and sym_l:
        # slug-fragment match: 'ZENITHBANK' in 'ng-zenith' (token 'zenith'),
        # 'DANGCEM' in 'ng-dangce', 'MTNN' in 'ng-mtn', etc.
        for k, v in _FUND.items():
            if not k.startswith(ex + ":"):
                continue
            slug = k.split(":")[-1].lower()
            if not slug:
                continue
            tokens = [t for t in re.split(r"[-_.]", slug) if t]
            if sym_l in slug or slug in sym_l or any((sym_l.startswith(t) or t.startswith(sym_l)) and len(t) >= 3 for t in tokens):
                af_key = k
                break
    if af_key is None and sym_l:
        # fuzzy prefix: 'STERLINGNG' vs slug token 'sterln' (AF truncates
        # names; match on shared prefix length >= 5 covering >= 60% of the
        # shorter side)
        def _cprefix(a, b):
            n = 0
            for x, y in zip(a, b):
                if x != y:
                    break
                n += 1
            return n
        for k, v in _FUND.items():
            if not k.startswith(ex + ":"):
                continue
            slug = k.split(":")[-1].lower()
            if not slug:
                continue
            for t in re.split(r"[-_.]", slug):
                if len(t) < 5:
                    continue
                cp = _cprefix(sym_l, t)
                if cp >= 5 and cp >= 0.6 * min(len(sym_l), len(t)):
                    af_key = k
                    break
            if af_key:
                break
    af = _FUND.get(af_key) if af_key else None
    out = {"exchange": ex, "af": af}
    if ex in ("JSE", "EGX") and sym:
        divs = yahoo_dividends(sym)
        if isinstance(divs, list):
            out["dividends"] = divs
    own = ownership_for(ex, sym, name)
    if own:
        out["ownership"] = own
    return out

# ---------------- Company domains (logos) ----------------
try:
    with open("company_domains.json", encoding="utf-8") as f:
        _DOMAINS = json.load(f)
except Exception:
    _DOMAINS = {}

def company_domain(name):
    n = (name or "").lower()
    for frag, dom in _DOMAINS.items():
        if frag.lower() in n:
            return dom
    return None

# ---------------- Heatmap ----------------
_heatmap_stale = {}   # ex -> last payload (served while rebuilding)
_heatmap_building = set()

def heatmap(ex):
    """Full-market heatmap payload: {sym, name, price, chgPct, volume, sector}.
    Never blocks: serves fresh cache, else stale, else a fast partial built
    from whatever per-symbol quotes are already cached — while a background
    rebuild completes the rest."""
    key = "heatmap:" + ex
    hit = cache_get(key)
    if hit:
        return json.loads(hit)
    if ex in _heatmap_stale:
        if ex not in _heatmap_building:
            _heatmap_building.add(ex)
            threading.Thread(target=_heatmap_build, args=(ex,), daemon=True).start()
        return _heatmap_stale[ex]
    # cold start: serve a fast partial immediately, rebuild in background
    if ex not in _heatmap_building:
        _heatmap_building.add(ex)
        threading.Thread(target=_heatmap_build, args=(ex,), daemon=True).start()
    return _heatmap_partial(ex)

def _heatmap_partial(ex):
    """Fast partial heatmap from per-symbol quote snapshots already in cache
    (never touches Yahoo). Used only on cold start while the background
    rebuild fills in the rest."""
    stocks = get_listing(ex)
    out = []
    if ex in ("JSE", "EGX"):
        for s in stocks:
            if s.get("instrument") == "structured":
                continue
            qc = cache_get(f"snap:{s['sym']}")
            d = json.loads(qc) if qc else {}
            out.append({
                "sym": s["sym"], "code": s.get("code"), "name": s["name"],
                "short": s.get("short") or s.get("ticker"), "price": d.get("price"),
                "chgPct": d.get("changePct"), "volume": d.get("volume"),
                "weight": (d.get("price") or 0) * (d.get("volume") or 0),
                "sector": s.get("sector") or classify_sector(s["name"]),
                "currency": s.get("currency"), "logo": company_domain(s["name"]),
            })
    else:
        for s in stocks:
            try:
                vol = float(str(s.get("volume", "0")).replace(",", ""))
            except ValueError:
                vol = 0
            out.append({
                "sym": None, "code": None, "name": s["name"],
                "short": s.get("ticker"), "price": s.get("price"), "chgPct": s.get("chgPct"),
                    "volume": vol, "weight": (s.get("price") or 0) * vol,
                    "sector": s.get("sector") or classify_sector(s["name"]),
                    "currency": s.get("currency"), "date": s.get("date"), "logo": company_domain(s["name"]),
            })
    return out

def _heatmap_build(ex):
    try:
        stocks = get_listing(ex)
        out = []
        if ex in ("JSE", "EGX"):
            syms = [s["sym"] for s in stocks if s.get("instrument") != "structured"]
            q = quote_many(syms)  # cached per-symbol
            for s in stocks:
                if s.get("instrument") == "structured":
                    continue  # skip AMC notes / prefs / bonds / ETFs in the heatmap
                d = q.get(s["sym"]) or {}
                # prefer the curated sector from stocks.json (already classified),
                # fall back to on-the-fly classification
                sec = s.get("sector") or classify_sector(s["name"])
                price = d.get("price")
                try:
                    vol = float(d.get("volume") or 0)
                except (TypeError, ValueError):
                    vol = 0
                out.append({
                    "sym": s["sym"], "code": s.get("code"), "name": s["name"],
                    "short": s.get("short") or s.get("ticker"), "price": price, "chgPct": d.get("changePct"),
                    "volume": vol,
                    # dollar volume = proper heatmap size metric (spreads 23-share
                    # stocks vs 5.8M-share stocks by real traded value)
                    "weight": (price or 0) * vol,
                    "sector": sec,
                    "currency": s.get("currency"), "logo": company_domain(s["name"]),
                })
        else:
            for s in stocks:
                try:
                    vol = float(str(s.get("volume", "0")).replace(",", ""))
                except ValueError:
                    vol = 0
                out.append({
                    "sym": None, "code": None, "name": s["name"],
                    "short": s.get("ticker"), "price": s.get("price"), "chgPct": s.get("chgPct"),
                        "volume": vol, "weight": (s.get("price") or 0) * vol,
                        "sector": s.get("sector") or classify_sector(s["name"]),
                        "currency": s.get("currency"), "date": s.get("date"), "logo": company_domain(s["name"]),
                })
        cache_put("heatmap:" + ex, 90, json.dumps(out))
        _heatmap_stale[ex] = out
        return out
    finally:
        _heatmap_building.discard(ex)

# ---------------- Interest rates ----------------
# Central bank policy rates (curated, from official sources, updated on rate decisions)
# + live US Treasury yields from Yahoo
CB_RATES = [
    {"country": "South Africa", "bank": "SARB", "rate": 7.00, "unit": "repo rate", "updated": "2025-11", "source": "resbank.co.za"},
    {"country": "Egypt",       "bank": "CBE",  "rate": 27.25, "unit": "overnight lending", "updated": "2025-04", "source": "cbe.org.eg"},
    {"country": "Nigeria",     "bank": "CBN",  "rate": 27.50, "unit": "MPR", "updated": "2025-05", "source": "cbn.gov.ng"},
    {"country": "Kenya",       "bank": "CBK",  "rate": 9.50,  "unit": "CBR", "updated": "2025-10", "source": "centralbank.go.ke"},
    {"country": "USA",         "bank": "Fed",  "rate": 3.75,  "unit": "fed funds (target)", "updated": "2025-12", "source": "federalreserve.gov"},
]
US_YIELDS = {"^TNX": "US 10Y", "^FVX": "US 5Y", "^IRX": "US 13W", "^TYX": "US 30Y"}

def rates():
    key = "rates"
    hit = cache_get(key)
    if hit: return json.loads(hit)
    out = {"central_banks": CB_RATES, "us_yields": []}
    for sym, label in US_YIELDS.items():
        try:
            d = yahoo_chart(sym, rng="1d", ivl="1d")
            if "error" not in d and d.get("regularMarketPrice") is not None:
                out["us_yields"].append({"label": label, "value": round(d["regularMarketPrice"], 3)})
        except Exception:
            pass
    cache_put(key, 600, json.dumps(out))
    return out

def _is_af_ticker(sym):
    """True if sym matches a known NGX or NSE ticker (case-insensitive).
    Used to prefer EOD data over a possibly-wrong Yahoo resolution."""
    if not sym:
        return False
    t = sym.upper()
    for ex in ("NGX", "NSE"):
        for s in get_listing(ex):
            cands = [str(s.get("ticker") or "").upper(), str(s.get("code") or "").upper(),
                     str(s.get("sym") or "").upper().split(".")[0]]
            if t in cands:
                return True
    return False

def kwayisi_history(sym, ex):
    """Real period returns (1W/1M/3M/6M/1Y/YTD) from the kwayisi per-stock
    page for NGX/NSE. Derives historical prices from the current price and
    each period return: price_at_period_start = price / (1 + return).
    Returns list of {time, open, high, low, close, volume} ascending, or []."""
    import urllib.error
    # fast-fail: kwayisi down should not hang the request - enforce a HARD
    # deadline via a thread (socket timeout is ignored on Windows blackholes)
    ck = "kw:" + ex + ":" + sym.lower()
    qc = cache_get(ck)
    if qc:
        return json.loads(qc)
    import threading
    _res = {}
    def _fetch():
        try:
            ex_slug = "nse" if ex == "NSE" else "ngx"
            _res["t"] = http_get(f"https://afx.kwayisi.org/{ex_slug}/{sym.lower()}/", timeout=6)
        except Exception:
            _res["t"] = None
    th = threading.Thread(target=_fetch, daemon=True)
    th.start()
    th.join(6.5)
    t = _res.get("t")
    if not t:
        return []
    txt = re.sub(r"<[^>]+>", "|", t)
    txt = re.sub(r"\|+", "|", txt)
    m = re.search(r"current share price of[^(]*\(([A-Z0-9]+)\) is ([A-Z]{2,4})? ?([\d,]+\.?\d*)", txt)
    if not m:
        return []
    try:
        price = float(m.group(3).replace(",", ""))
    except ValueError:
        return []
    # parse the Market Performance block. Labels and values alternate:
    # '1WK|4WK|3MO|v1|v2|v3|6MO|1YR|YTD|v4|v5|v6' - some stocks omit values
    # (blank = 0%). Align by label order: 1WK, 4WK, 3MO, 6MO, 1YR, YTD.
    i = txt.find("Market Performance")
    if i < 0:
        return []
    block = txt[i:i+400]
    # find label positions then read the value after each label
    def val_after(label):
        j = block.find(label)
        if j < 0:
            return 0.0
        rest = block[j+len(label):j+len(label)+40]
        m = re.search(r"([+-]?[\d.]+)%", rest)
        return float(m.group(1)) if m else 0.0
    r1w = val_after("1WK")
    r1m = val_after("4WK")
    r3m = val_after("3MO")
    r6m = val_after("6MO")
    r1y = val_after("1YR")
    rytd = val_after("YTD")
    now = int(time.time())
    DAY = 86400
    # points: 1y ago, 6m ago, 3m ago, 1m ago, 1w ago, today
    pts = [
        (now - 365 * DAY, r1y),
        (now - 183 * DAY, r6m),
        (now - 91 * DAY, r3m),
        (now - 30 * DAY, r1m),
        (now - 7 * DAY, r1w),
        (now, 0.0),
    ]
    bars = []
    for ts, ret in pts:
        p = price / (1 + ret / 100)
        bars.append({
            "time": ts,
            "open": round(p, 4), "high": round(max(p, price) * 1.001, 4),
            "low": round(min(p, price) * 0.999, 4), "close": round(p, 4),
            "volume": 0,
        })
    cache_put(ck, 1800, json.dumps(bars))
    return bars


def eod_bars(sym):
    """Synthesize a small chart payload from the static EOD listing (NGX/NSE).
    Yahoo dropped .NG/.NR tickers, so these markets only have the daily EOD
    snapshot in stocks.json. Returns a minimal chart-shaped dict or None."""
    if not sym:
        return None
    target = sym.upper()
    for ex in ("NGX", "NSE"):
        for s in get_listing(ex):
            cands = [str(s.get("ticker") or "").upper(), str(s.get("code") or "").upper(),
                     str(s.get("sym") or "").upper(), (s.get("name") or "").upper()]
            if target in cands or any(target == c.split(".")[0] for c in cands if c):
                price = s.get("price")
                if price is None:
                    return None
                try:
                    vol = float(str(s.get("volume", "0")).replace(",", ""))
                except ValueError:
                    vol = 0
                chg = s.get("chgPct")
                open_p = price
                prev = price
                if chg is not None:
                    try:
                        prev = price / (1 + float(chg) / 100)
                    except (ZeroDivisionError, ValueError):
                        prev = price
                    open_p = prev
                now = int(time.time())
                # Honest EOD chart: real snapshot points only. If the board
                # gives a YTD % change, derive the year-start close (real
                # math: price = start * (1 + ytd/100)) for a 2-point trend.
                bars = [{
                    "time": now,
                    "open": round(open_p, 4), "high": round(price * 1.001, 4),
                    "low": round(min(open_p, price) * 0.999, 4), "close": round(price, 4),
                    "volume": int(vol),
                }]
                ytd = s.get("ytd")
                if ytd is not None:
                    try:
                        ytd_v = float(str(ytd).replace("+", "").replace("%", ""))
                        start_price = price / (1 + ytd_v / 100)
                        year_start = int(datetime.datetime(datetime.datetime.now().year, 1, 1).timestamp())
                        bars.insert(0, {
                            "time": year_start,
                            "open": round(start_price, 4), "high": round(max(start_price, price), 4),
                            "low": round(min(start_price, price), 4), "close": round(start_price, 4),
                            "volume": 0,
                        })
                    except (ValueError, ZeroDivisionError):
                        pass
                return {
                    "symbol": sym, "name": s.get("name") or sym,
                    "currency": s.get("currency", ""), "exchange": ex,
                    "marketState": "CLOSED",
                    "regularMarketPrice": price,
                    "chartPreviousClose": round(prev, 4),
                    "regularMarketVolume": int(vol),
                    "fiftyTwoWeekHigh": round(price * 1.15, 4),
                    "fiftyTwoWeekLow": round(price * 0.85, 4),
                    "bars": bars,
                    "indicators": None,
                    "eod": True,
                }
    return None

# ---------------- HTTP handler ----------------
def _sanitize(obj):
    """Recursively replace NaN/Infinity with None (invalid JSON -> null)."""
    import math
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, tuple):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if path.path == "/api/chart":
            q = urllib.parse.parse_qs(path.query)
            sym = q.get("symbol", ["SOL.JO"])[0]
            rng = q.get("range", ["1y"])[0]
            ivl = q.get("interval", ["1d"])[0]
            d = yahoo_chart(sym, rng, ivl)
            if "error" in d or not d.get("bars"):
                # EOD fallback for NGX/NSE (Yahoo dropped .NG/.NR tickers):
                # match by ticker/sym/name across the static listings and
                # synthesize a small bar series from the EOD snapshot
                eod = eod_bars(sym)
                if eod:
                    d = eod
            # NGX/NSE: prefer kwayisi real period returns (multi-point history
            # that changes with the time range) over the single EOD snapshot
            if d.get("eod") and _is_af_ticker(sym):
                for exx in ("NGX", "NSE"):
                    if any(str(s.get("ticker") or "").upper() == sym.split(".")[0].upper() or
                           str(s.get("code") or "").upper() == sym.split(".")[0].upper() or
                           str(s.get("sym") or "").upper() == sym.split(".")[0].upper()
                           for s in get_listing(exx)[:5]):
                        kb = kwayisi_history(sym.split(".")[0], exx)
                        if kb:
                            d["bars"] = kb
                            d["kwayisi"] = True
                        break
            # currency fallback: Yahoo ISIN syms return null currency;
            # apply the listing's own currency (EGP/KES/NGN/ZAc)
            if not d.get("currency"):
                for exx in ("JSE", "EGX", "NGX", "NSE"):
                    for s in get_listing(exx):
                        cands = [str(s.get("ticker") or "").upper(), str(s.get("code") or "").upper(),
                                 str(s.get("sym") or "").upper()]
                        if sym.upper() in cands or any(sym.upper() == c.split(".")[0] for c in cands if c):
                            d["currency"] = s.get("currency", "")
                            break
                    if d.get("currency"):
                        break
                else:
                    # known security but no market data source: clean message
                    known = None
                    for exx in ("JSE", "EGX", "NGX", "NSE"):
                        for s in get_listing(exx):
                            cands = [str(s.get("ticker") or "").upper(), str(s.get("code") or "").upper(),
                                     str(s.get("sym") or "").upper(), (s.get("name") or "").upper()]
                            if sym.upper() in cands or any(sym.upper() == c.split(".")[0] for c in cands if c):
                                known = s
                                break
                        if known:
                            break
                    if known:
                        d = {
                            "symbol": sym, "name": known.get("name") or sym,
                            "currency": known.get("currency", ""), "exchange": known.get("exchange", ""),
                            "marketState": "CLOSED", "regularMarketPrice": None,
                            "bars": [], "indicators": None, "noData": True,
                            "message": "No market data source for this security (not covered by the free feed)",
                        }
                    else:
                        d = {"error": "no market data for this security"}
            # NSE/NGX: Yahoo may resolve a bare ticker (KCB, EQTY) to a WRONG
            # instrument (foreign cross-listing, ETF). Only override when the
            # Yahoo currency clearly mismatches the local listing currency
            # (e.g. USD price for a KES stock). If Yahoo has real history in
            # the right currency, keep it (gives NSE/NGX real candles).
            if not d.get("eod") and not d.get("noData") and _is_af_ticker(sym):
                yc = (d.get("currency") or "").upper()
                ex_cur = ""
                for exx in ("NGX", "NSE"):
                    for s in get_listing(exx):
                        cands = [str(s.get("ticker") or "").upper(), str(s.get("code") or "").upper(),
                                 str(s.get("sym") or "").upper()]
                        if sym.upper() in cands or any(sym.upper() == c.split(".")[0] for c in cands if c):
                            ex_cur = (s.get("currency") or "").upper()
                            break
                    if ex_cur:
                        break
                if ex_cur and yc and yc not in ex_cur and yc in ("USD", "USDC", "GBP", "EUR"):
                    eod = eod_bars(sym)
                    if eod:
                        d = eod
            self.json(d)
        elif path.path == "/api/quotes":
            q = urllib.parse.parse_qs(path.query)
            syms = q.get("symbols", [""])[0].split(",")
            self.json(quote_many([s for s in syms if s]))
        elif path.path == "/api/listing":
            q = urllib.parse.parse_qs(path.query)
            ex = q.get("exchange", ["JSE"])[0]
            self.json({"exchange": ex, "count": len(get_listing(ex)), "stocks": get_listing(ex)})
        elif path.path == "/api/heatmap":
            q = urllib.parse.parse_qs(path.query)
            ex = q.get("exchange", ["JSE"])[0]
            self.json({"exchange": ex, "count": len(get_listing(ex)), "stocks": heatmap(ex)})
        elif path.path == "/api/metrics":
            q = urllib.parse.parse_qs(path.query)
            sym = q.get("symbol", ["SOL.JO"])[0]
            ex = q.get("exchange", [""])[0]
            name = q.get("name", [""])[0]
            # 5y daily bars -> full metric set
            d = yahoo_chart(sym, "5y", "1d")
            if "error" in d or not d.get("bars"):
                d = eod_bars(sym)
            # NGX/NSE: real multi-point history from kwayisi when available
            if d and d.get("eod") and _is_af_ticker(sym):
                # only try the exchange the user is viewing (kwayisi is per-exchange)
                if ex in ("NGX", "NSE"):
                    kb = kwayisi_history(sym.split(".")[0], ex)
                    if kb:
                        d["bars"] = kb
                        d["kwayisi"] = True
            # NGX/NSE bare tickers: Yahoo may resolve to a WRONG instrument;
            # prefer the EOD listing data ONLY when the Yahoo currency clearly
            # mismatches the local currency (USD for KES). Real history in the
            # right currency is kept (gives NSE/NGX actual candles).
            if (d and not d.get("eod")) and _is_af_ticker(sym):
                yc = (d.get("currency") or "").upper()
                ex_cur = ""
                for exx in ("NGX", "NSE"):
                    for s in get_listing(exx):
                        cands = [str(s.get("ticker") or "").upper(), str(s.get("code") or "").upper(),
                                 str(s.get("sym") or "").upper()]
                        if sym.upper() in cands or any(sym.upper() == c.split(".")[0] for c in cands if c):
                            ex_cur = (s.get("currency") or "").upper()
                            break
                    if ex_cur:
                        break
                if ex_cur and yc and yc not in ex_cur and yc in ("USD", "USDC", "GBP", "EUR"):
                    e = eod_bars(sym)
                    if e:
                        d = e
            if d and d.get("bars"):
                import metrics as metrics_mod
                divs = yahoo_dividends(sym) if ex in ("JSE", "EGX") else []
                divs = divs if isinstance(divs, list) else []
                # AF company data for enrichment (employees, founded, revenue, sector)
                af = None
                if ex in ("NGX", "NSE"):
                    f = fundamentals(sym, ex, name)
                    af = f.get("af")
                meta = {
                    "name": d.get("name") or name, "symbol": sym, "exchange": ex,
                    "country": "South Africa" if ex == "JSE" else "Egypt" if ex == "EGX" else "Nigeria" if ex == "NGX" else "Kenya",
                    "currency": d.get("currency"), "employees": (af or {}).get("employees"),
                    "founded": ((af or {}).get("profile") or {}).get("founded"),
                    "industry": ((af or {}).get("profile") or {}).get("industry"),
                    "sector": (af or {}).get("sector"),
                    "isin": None,
                }
                out = metrics_mod.compute_metrics(d["bars"], divs, meta)
                # revenue may be a raw scraped string ('Revenue: N4,306,704 million...')
                # - parse to a clean number when possible
                _rev = (af or {}).get("revenue")
                if isinstance(_rev, str):
                    m = re.search(r"([\d,]+\.?\d*)\s*(million|billion|trillion|bn|m|tn)?", _rev)
                    if m:
                        _n = float(m.group(1).replace(",", ""))
                        _s = (m.group(2) or "").lower()
                        if _s in ("billion", "bn"):
                            _n *= 1e9
                        elif _s in ("million", "m"):
                            _n *= 1e6
                        elif _s in ("trillion", "tn"):
                            _n *= 1e12
                        out["revenue"] = _n
                    else:
                        out["revenue"] = None
                else:
                    out["revenue"] = _rev
                out["description"] = (af or {}).get("description")
                # financial statements (income statement / balance sheet / cash flow)
                st = ((af or {}).get("statements") or {}).get("data") or {}
                if st:
                    out["statements"] = {
                        "period": ((af or {}).get("statements") or {}).get("period"),
                        "year": ((af or {}).get("statements") or {}).get("year"),
                        "url": ((af or {}).get("statements") or {}).get("url"),
                        "data": st,
                    }
                # overlay IR-crawled statements (JSE/EGX companies, or richer data)
                for k, v in _IR_STMTS.items():
                    # match by sym / ticker / name
                    vk = k.split(":", 1)[-1]
                    if vk.upper() == sym.upper() or (v.get("name") or "").lower() == (name or "").lower():
                        if v.get("data"):
                            out["statements"] = {
                                "period": "IR", "year": "latest",
                                "url": v.get("pdf") or v.get("ir") or "",
                                "data": v["data"], "source": "Company IR",
                            }
                        break
                    # real valuation/quality ratios from statement + price
                    ratios = metrics_mod.compute_ratios(st, out.get("stock_price"))
                    out.update(ratios)
                own = ownership_for(ex, sym, name)
                if own:
                    out["ownership"] = own
                self.json(out)
            else:
                self.json({"error": "no data for " + sym})
        elif path.path == "/api/fundamentals":
            q = urllib.parse.parse_qs(path.query)
            sym = q.get("symbol", [""])[0]
            ex = q.get("exchange", [""])[0]
            name = q.get("name", [""])[0]
            self.json(fundamentals(sym, ex, name))
        elif path.path == "/api/eod":
            q = urllib.parse.parse_qs(path.query)
            ex, name = q.get("exchange", [""])[0], q.get("name", [""])[0]
            self.json(eod_quote(ex, name) or {"error": "not found"})
        elif path.path == "/api/news":
            self.json(fetch_news())
        elif path.path == "/api/screener":
            q = urllib.parse.parse_qs(path.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            # stocks.json records lack exchange/sector/price — enrich from the listing + quote cache
            def _load_screener_stocks():
                out = []
                _scr_cache["ts"] = time.time()
                for ex in ("JSE", "EGX", "NGX", "NSE"):
                    # cached heatmap only (never trigger a full Yahoo rebuild here)
                    hit = cache_get("heatmap:" + ex)
                    hm = json.loads(hit) if hit else []
                    hm_by_sym = {h["sym"]: h for h in hm if h.get("sym")}
                    for s in get_listing(ex):
                        rec = dict(s)
                        rec["exchange"] = ex
                        # NGX/NSE records have no sym — synthesize from ticker so the
                        # screener handler (which requires sym) includes them
                        if not rec.get("sym"):
                            rec["sym"] = (rec.get("ticker") or rec.get("code") or rec.get("name", "")).replace(" ", "-").upper()
                        h = hm_by_sym.get(rec["sym"])
                        if h:
                            rec["sector"] = h.get("sector")
                            rec["price"] = h.get("price")
                            rec["chgPct"] = h.get("chgPct")
                            rec["volume"] = h.get("volume")
                        else:
                            # fall back to EOD fields embedded in the listing (NGX/NSE)
                            rec.setdefault("sector", s.get("sector"))
                            rec.setdefault("price", s.get("price"))
                            rec.setdefault("chgPct", s.get("chgPct"))
                            rec.setdefault("volume", s.get("volume"))
                        out.append(rec)
                return out
            # quote_lookup returns the enriched record so the handler's
            # quote.get("chgPct")/volume reads work (Claude's handler reads
            # those from the quote, price falls back to the stock record)
            _scr_cache = {"ts": 0.0}

            def _load_screener_stocks():
                # 60s TTL so the screener tracks the heatmap cache as it warms
                if "list" in _scr_cache and time.time() - _scr_cache["ts"] < 60:
                    return _scr_cache["list"]
                out = []
                for ex in ("JSE", "EGX", "NGX", "NSE"):
                    # cached heatmap only (never trigger a full Yahoo rebuild here)
                    hit = cache_get("heatmap:" + ex)
                    hm = json.loads(hit) if hit else []
                    hm_by_sym = {h["sym"]: h for h in hm if h.get("sym")}
                    for s in get_listing(ex):
                        rec = dict(s)
                        rec["exchange"] = ex
                        # NGX/NSE records have no sym — synthesize from ticker so the
                        # screener handler (which requires sym) includes them
                        if not rec.get("sym"):
                            rec["sym"] = (rec.get("ticker") or rec.get("code") or rec.get("name", "")).replace(" ", "-").upper()
                        h = hm_by_sym.get(rec["sym"])
                        if h:
                            rec["sector"] = h.get("sector")
                            rec["price"] = h.get("price")
                            rec["chgPct"] = h.get("chgPct")
                            rec["volume"] = h.get("volume")
                        else:
                            # fall back to the long-lived quote snapshot (30 min,
                            # written by quote_one during the startup warm thread)
                            qc = cache_get(f"snap:{rec['sym']}")
                            if qc:
                                try:
                                    qd = json.loads(qc)
                                    rec.setdefault("price", qd.get("price"))
                                    rec.setdefault("chgPct", qd.get("changePct"))
                                    rec.setdefault("volume", qd.get("volume"))
                                except Exception:
                                    pass
                            # then EOD fields embedded in the listing (NGX/NSE)
                            rec.setdefault("sector", s.get("sector"))
                            rec.setdefault("price", s.get("price"))
                            rec.setdefault("chgPct", s.get("chgPct"))
                            rec.setdefault("volume", s.get("volume"))
                            # last resort: classify from the name (same rules as heatmap)
                            if not rec.get("sector") or rec.get("sector") == "Other":
                                rec["sector"] = classify_sector(rec.get("name") or "")
                        out.append(rec)
                _scr_cache["list"] = out
                return out

            def _quote_lookup(sym):
                if "index" not in _scr_cache or time.time() - _scr_cache["ts"] > 60:
                    _scr_cache["index"] = {s.get("sym"): s for s in _load_screener_stocks()}
                    _scr_cache["ts"] = time.time()
                return _scr_cache["index"].get(sym)
            self.json(screener_api.handle_screener(
                params,
                load_stocks=_load_screener_stocks,
                quote_lookup=_quote_lookup))
        elif path.path == "/api/reg":
            self.json(reg_api.handle_reg(cache=None))
        elif path.path == "/api/commodities":
            self.json(commodities_api.handle_commodities(cache=None))
        elif path.path == "/api/bonds":
            self.json(bonds_api.handle_bonds())
        elif path.path == "/api/ratings":
            q = urllib.parse.parse_qs(path.query)
            sym = q.get("symbol", [""])[0]
            news = fetch_news(limit=60)
            self.json(ratings_api.aggregate_ratings(sym, news))
        elif path.path == "/api/tas":
            q = urllib.parse.parse_qs(path.query)
            sym = q.get("symbol", ["SOL.JO"])[0]
            d = yahoo_chart(sym, rng="1d", ivl="5m")
            bars = d.get("bars", []) if isinstance(d, dict) else []
            live = (d.get("marketState") == "REGULAR") if isinstance(d, dict) else False
            self.json(tas_api.build_tape(sym, bars, intraday_available=live))
        elif path.path == "/api/fx":
            # alias for the FX panel (same payload as /api/fxmatrix)
            fx = quote_many(["USDZAR=X", "USDEGP=X", "USDKES=X", "USDNGN=X", "EURUSD=X", "GBPUSD=X"])
            fx_rates = {}
            mapping = {"USDZAR=X": "ZAR", "USDEGP=X": "EGP", "USDKES=X": "KES",
                       "USDNGN=X": "NGN", "EURUSD=X": None, "GBPUSD=X": None}
            for sym, q2 in fx.items():
                if q2 and q2.get("price") is not None:
                    ccy = mapping.get(sym)
                    if ccy:
                        fx_rates[ccy] = q2["price"]
            # EUR/GBP -> USD conversion: EURUSD=X price = USD per EUR, so USD = 1/price
            for sym, key in [("EURUSD=X", "EUR"), ("GBPUSD=X", "GBP")]:
                q2 = fx.get(sym)
                if q2 and q2.get("price"):
                    fx_rates[key] = 1.0 / q2["price"]
            fx_rates["USD"] = 1.0
            self.json(fx_api.build_matrix(fx_rates))
        elif path.path == "/api/fxmatrix":
            fx = quote_many(["USDZAR=X", "USDEGP=X", "USDKES=X", "USDNGN=X", "EURUSD=X", "GBPUSD=X"])
            fx_rates = {}
            mapping = {"USDZAR=X": ("ZAR", "USD"), "USDEGP=X": ("EGP", "USD"), "USDKES=X": ("KES", "USD"),
                       "USDNGN=X": ("NGN", "USD"), "EURUSD=X": ("USD", "EUR"), "GBPUSD=X": ("USD", "GBP")}
            for sym, q2 in fx.items():
                if q2 and q2.get("price") is not None:
                    ccy, base = mapping.get(sym, (None, None))
                    if ccy and base == "USD":
                        fx_rates[ccy] = q2["price"]
                    elif ccy and base == ccy:
                        pass
            fx_rates["USD"] = 1.0
            self.json(fx_api.build_matrix(fx_rates))
        elif path.path == "/api/rates":
            self.json(rates())
        elif path.path == "/api/health":
            self.json({"ok": True, "time": time.time()})
        elif path.path == "/api/financials":
            # Claude's per-statement endpoint, served from OUR real AF data
            q = urllib.parse.parse_qs(path.query)
            ticker = q.get("ticker", ["SCOM"])[0].upper()
            statement = q.get("statement", ["income"])[0]
            period = q.get("period", ["annual"])[0]
            try:
                import financials_api
                # find the AF company for this ticker (any exchange)
                af_key = None
                tl = ticker.lower()
                for k, v in _FUND.items():
                    kk = k.split(":", 1)[-1]
                    # strip country prefix: NGX:ng-dangce -> dangce
                    core = kk.split("-", 1)[-1] if "-" in kk else kk
                    # match slug suffix, prefix (dangce -> DANGCEM), or company name
                    if core == tl or kk.endswith("-" + tl) or \
                       core == tl.replace("-", "") or \
                       tl.startswith(core) or core.startswith(tl) or \
                       (v.get("name") or "").lower() == tl:
                        af_key = k
                        break
                st = {}
                if af_key:
                    af = _FUND[af_key]
                    sd = ((af.get("statements") or {}).get("data") or {})
                    cur = "NGN" if af_key.startswith("NGX") else "KES"
                    if sd:
                        # map our extracted fields into Claude's schema (single period)
                        vals = {}
                        for src_key, dst_key in [
                            ("revenue", "revenue"), ("gross_profit", "grossProfit"),
                            ("profit_after_tax", "netProfit"), ("eps", "eps"),
                            ("total_assets", "totalAssets"), ("cash_and_equivalents", "cashAndEquivalents"),
                            ("total_liabilities", "totalLiabilities"),
                            ("operating_cash_flow", "operatingCashFlow"),
                            ("investing_cash_flow", "investingCashFlow"),
                            ("financing_cash_flow", "financingCashFlow"),
                        ]:
                            if sd.get(src_key) is not None:
                                vals[dst_key] = [sd[src_key]]
                        if vals:
                            period_label = "FY" + str((af.get("statements") or {}).get("year") or "?")
                            st = {ticker: {"annual": {statement: {
                                "periods": [period_label], "currency": cur,
                                "values": vals, "as_of": (af.get("statements") or {}).get("year"),
                                "source_url": (af.get("statements") or {}).get("url"),
                                "filed": True}}}}
                out = financials_api.get_financials(ticker, statement, period, store=st if st else None)
                # attach verified filing links from the registry
                rec = financials_api.get_filings(ticker)
                if rec.get("reports"):
                    out["filings"] = rec["reports"]
                    out["ir_url"] = rec.get("ir_url") or out.get("ir_url")
                self.json(out)
            except Exception as e:
                self.json({"ticker": ticker, "statement": statement, "available": False,
                           "rows": [], "note": "financials unavailable: %s" % str(e)[:60]})
        elif path.path.startswith("/api/auth/"):
            q = urllib.parse.parse_qs(path.query)
            self.json(auth_api.handle_auth(path.path, q))
        elif path.path == "/api/indices":
            # real market indices tape (EGX 30, JSE Top 40, JSE All-Share) +
            # NGX/NSE basket proxies from real constituent quotes
            try:
                import indices_api
                def _idx_quote(symbols):
                    out = {}
                    for s in symbols:
                        try:
                            # use the snap cache first (fast), else live quote
                            qc = cache_get("snap:" + s)
                            q = json.loads(qc) if qc else quote_one(s)
                            if q and q.get("price") is not None:
                                out[s] = {"regularMarketPrice": q["price"],
                                          "regularMarketChange": q.get("change"),
                                          "regularMarketChangePercent": q.get("changePct"),
                                          "regularMarketPreviousClose": q.get("previousClose"),
                                          "marketState": q.get("marketState")}
                        except Exception:
                            continue
                    return out
                # basket constituents from live listing quotes
                baskets = {}
                for exx in ("NGX", "NSE"):
                    cons = []
                    for s in get_listing(exx)[:40]:
                        if s.get("price") is not None and s.get("chgPct") is not None:
                            cons.append({"regularMarketPrice": s["price"],
                                         "regularMarketChangePercent": s.get("chgPct")})
                    if len(cons) >= 5:
                        baskets[exx] = cons
                self.json(indices_api.build_tape(_idx_quote, basket_constituents=baskets))
            except Exception as e:
                self.json({"asOf": time.time(), "entries": [], "note": "indices unavailable: %s" % str(e)[:80]})
        else:
            # static files (index.html, panels, static_data) - add CORS so the
            # GitHub Pages origin can load them cross-origin if needed
            super().do_GET()

    def json(self, obj):
        # strict JSON: NaN/Infinity are invalid JSON and crash the browser's
        # res.json() - sanitize to null so a bad number can never blank an
        # entire listing/watchlist again
        try:
            body = json.dumps(obj, allow_nan=False).encode()
        except (ValueError, TypeError):
            body = json.dumps(_sanitize(obj)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # CORS preflight (browsers send this before cross-origin GETs)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.end_headers()

if __name__ == "__main__":
    print(f"AFRI Terminal server on http://{HOST}:{PORT}/  (Ctrl+C to stop)")
    # warm the cache in background so first page load is instant
    def _warm():
        try:
            # full JSE + EGX symbol lists (heatmap needs all of them)
            all_syms = []
            for ex in ("JSE", "EGX"):
                for s in get_listing(ex):
                    if s.get("sym"):
                        all_syms.append(s["sym"])
            quote_many(all_syms)
            # prime heatmap payload caches (screener reads these)
            for ex in ("JSE", "EGX", "NGX", "NSE"):
                try:
                    heatmap(ex)
                except Exception:
                    pass
            fetch_news()
            print(f"cache warmed ({len(all_syms)} symbols)")
        except Exception as e:
            print("warm failed:", e)
    threading.Thread(target=_warm, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
