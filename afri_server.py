#!/usr/bin/env python3
"""
AFRI Terminal v2 - local server
Serves the terminal UI + proxies live market data (Yahoo chart API) and news RSS.
Run:  python afri_server.py   (then open http://127.0.0.1:8081/)
Stdlib only - no pip installs needed.
"""
import json, time, urllib.request, urllib.parse, threading, sys, os
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

HOST, PORT = "127.0.0.1", 8081
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
    except Exception as ex:
        return {"error": str(ex)}
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

# ---------------- Full listings (stocks.json) ----------------
try:
    with open("stocks.json", encoding="utf-8") as f:
        _LISTINGS = json.load(f)["stocks"]
except Exception:
    _LISTINGS = {}

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
    for k, v in _FUND.items():
        if k.startswith(ex + ":") and (name and v.get("name", "").lower() == name.lower() or k.endswith(sym.lower())):
            af_key = k
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
            qc = cache_get(f"snap:{s['sym']}")
            d = json.loads(qc) if qc else {}
            out.append({
                "sym": s["sym"], "code": s.get("code"), "name": s["name"],
                "short": s.get("short") or s.get("ticker"), "price": d.get("price"),
                "chgPct": d.get("changePct"), "volume": d.get("volume"),
                "sector": classify_sector(s["name"]),
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
                "volume": vol, "sector": s.get("sector") or classify_sector(s["name"]),
                "currency": s.get("currency"), "date": s.get("date"), "logo": company_domain(s["name"]),
            })
    return out

def _heatmap_build(ex):
    try:
        stocks = get_listing(ex)
        out = []
        if ex in ("JSE", "EGX"):
            syms = [s["sym"] for s in stocks]
            q = quote_many(syms)  # cached per-symbol
            for s in stocks:
                d = q.get(s["sym"]) or {}
                out.append({
                    "sym": s["sym"], "code": s.get("code"), "name": s["name"],
                    "short": s.get("short") or s.get("ticker"), "price": d.get("price"), "chgPct": d.get("changePct"),
                    "volume": d.get("volume"), "sector": classify_sector(s["name"]),
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
                    "volume": vol, "sector": s.get("sector") or classify_sector(s["name"]),
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
                bars = []
                for i in range(6):
                    t = now - (6 - i) * 86400
                    drift = 1 + (i - 3) * 0.004
                    c = round(price * drift, 4)
                    o = round(open_p * drift, 4)
                    bars.append({
                        "time": t,
                        "open": o, "high": round(max(o, c) * 1.002, 4),
                        "low": round(min(o, c) * 0.998, 4), "close": c,
                        "volume": int(vol),
                    })
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
            _scr_cache = {}

            def _load_screener_stocks():
                if "list" in _scr_cache:
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
                if "index" not in _scr_cache:
                    _scr_cache["index"] = {s.get("sym"): s for s in _load_screener_stocks()}
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
        else:
            super().do_GET()

    def json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
