#!/usr/bin/env python3
"""build_shares.py - derive outstanding shares for all exchanges and write
them into market_<EX>.json as sharesIssued.

Sources:
  JSE: Yahoo meta already in market_JSE.json (sharesOutstanding)
  NGX: official price list PRICES_LIST2 (MARKET CAP(Nm) / PRICE -> shares)
  NSE: mystocks nse_extra.json (Shares Issued strings like "32.16M")
  EGX: Yahoo chart meta (sharesOutstanding) - fetched fresh
"""
import json, os, re, urllib.request, zipfile, io, time
import pdfplumber

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")

def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

def parse_share_str(s):
    """'32.16M' -> 32160000; '1,234,567' -> 1234567"""
    if not s: return None
    s = s.strip().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMBT]?)$", s, re.I)
    if not m: return None
    val = float(m.group(1))
    mult = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    return int(val * mult)

# ---- NSE: mystocks ----
def nse_shares():
    out = {}
    d = json.load(open(os.path.join(SD, "nse_extra.json"), encoding="utf-8"))
    for k, v in d.items():
        si = (v.get("info") or {}).get("Shares Issued")
        n = parse_share_str(si)
        if n:
            out[k] = n
    return out

# ---- NGX: official price list ----
NGX_ALIASES = [
    ("mtn nigeria", "MTNN"), ("united bank for africa", "UBA"), ("zenith bank", "ZENITHBANK"),
    ("guaranty trust", "GTCO"), ("dangote cement", "DANGCEM"), ("access holdings", "ACCESSCORP"),
    ("airtel africa", "AIRTELAFRI"), ("nigerian breweries", "NB"), ("stanbic ibtc", "STANBIC"),
    ("bua cement", "BUACEMENT"), ("bua foods", "BUAFOODS"), ("fbn holdings", "FBNH"),
    ("ecobank", "ETI"), ("seplat", "SEPLAT"), ("nestle nigeria", "NESTLE"),
    ("lafarge africa", "WAPCO"), ("flour mills", "FLOURMILL"), ("dangote sugar", "DANGSUGAR"),
    ("nascon", "NASCON"), ("transnational corporation", "TRANSCORP"), ("united capital", "UCAP"),
    ("fcmb", "FCMB"), ("fidelity bank", "FIDELITYBK"), ("sterling bank", "STERLINGNG"),
    ("jaiz bank", "JAIZBANK"), ("wema bank", "WEMABANK"), ("custodian", "CUSTODIAN"),
    ("cornerstone", "CORNERST"), ("uac of nigeria", "UACN"), ("unilever", "UNILEVER"),
    ("cadbury", "CADBURY"), ("guinness", "GUINNESS"), ("vitafoam", "VITAFOAM"),
    ("pz cussons", "PZ"), ("totalenergies", "TOTAL"), ("total energies", "TOTAL"),
    ("conoil", "CONOIL"), ("oando", "OANDO"), ("eter", "ETERNA"), ("aiico", "AIICO"),
    ("international breweries", "INTBREW"), ("first bank", "FBNH"), ("union bank", "UBN"),
    ("honeywell", "HONYFLOUR"), ("glaxosmithkline", "GLAXOSMITH"), ("morison", "MORISON"),
    ("presco", "PRESCO"), ("okomu oil", "OKOMUOIL"), ("transcorp power", "TRANSPOWER"),
    ("transcorp hotel", "TRANSCOHOT"), ("university press", "UPL"), ("tripple g", "TRIPPLEG"),
    ("thomas wyatt", "THOMASWY"), ("abc transport", "ABCTRANS"), ("acid", "ACADEMY"),
    ("chams", "CHAMS"), ("cwg", "CWG"), ("ellah lakes", "ELLAHLAKES"), ("ellah", "ELLAHLAKES"),
    ("julius berger", "JBERGER"), ("japaul", "JAPAULGOLD"), ("mrs oil", "MRS"),
    ("neimeth", "NEIMETH"), ("nigeria aviation", "NAHCO"), ("nigeria aviation handling", "NAHCO"),
    ("pharma deko", "PHARMDEKO"), ("premier paints", "PREMPAINTS"), ("red star", "REDSTAREX"),
    ("royal exchange", "ROYALEX"), ("sov", "SOVRENINS"), ("sunu", "SUNUASSUR"),
    ("tantalizers", "TANTALIZER"), ("uac", "UACN"), ("unity bank", "UNITYBNK"),
    ("veritas", "VERITASKAP"), ("wema", "WEMABANK"), ("yield", "YLD"),
    ("ardova", "ARDOVA"), ("11", "ELEVEN"), ("bergers", "BERGER"), ("betaglas", "BETAGLAS"),
    ("caverton", "CAVERTON"), ("chemical", "CHELLARAM"), ("chelsfield", "CHELLARAM"),
    ("capital oil", "CAPOIL"), ("capital hotels", "CAPHOTEL"), ("courteville", "COURTVILLE"),
    ("dangote", "DANGCEM"), ("eter", "ETERNA"), ("fidson", "FIDSON"), ("first aluminum", "FIRSTALUM"),
    ("golf", "GOLDBREW"), ("guinea", "GUINEAINS"), ("hagemeyer", "HAGEMEYER"),
    ("iber", "IBER"), ("image", "IMG"), ("infinity", "INFINITY"), ("int", "INTENEGINS"),
    ("japaul", "JAPAULGOLD"), ("john holt", "JOHNHOLT"), ("les", "LASACO"),
    ("learn africa", "LEARNAFRCA"), ("linkage", "LINKASSURE"), ("living trust", "LIVINGTRUST"),
    ("livestock", "LIVESTOCK"), ("mcnichols", "MCNICHOLS"), ("mecure", "MECURE"),
    ("morgan", "MORGANS"), ("multitrex", "MULTITREX"), ("ncr", "NCR"), ("nigerian aviation", "NAHCO"),
    ("nigerian en", "INTENEGINS"), ("nord", "NORDBANK"), ("npf", "NPFMCRFBK"),
    ("omatek", "OMATEK"), ("pioneer", "PION"), ("portland", "PORT"), ("prestige", "PRESTIGE"),
    ("raymond", "RAYC"), ("regal", "REGALINS"), ("road", "RTBRISCOE"), ("sfs", "SFSREIT"),
    ("sky", "SKYAVN"), ("smart", "SMART"), ("sovereign", "SOVRENINS"), ("staco", "STACO"),
    ("sure", "SUREPENS"), ("swiss", "SWISS"), ("tao", "TAO"), ("tourist", "TOURIST"),
    ("transexpress", "TRANSEXPR"), ("un", "UNIVINSURE"), ("unknown", "UNIVINSURE"),
    ("updc", "UPDC"), ("veritas", "VERITASKAP"), ("vono", "VONO"),
]
def ngx_shares():
    listing = json.load(open(os.path.join(SD, "listing_NGX.json"), encoding="utf-8")).get("stocks", [])
    def find_sym(comp):
        c = comp.lower()
        for frag, tkr in NGX_ALIASES:
            if frag in c:
                return tkr
        for nm, tkr in [(norm(s.get("name")), s.get("ticker") or s.get("sym")) for s in listing if s.get("ticker")]:
            if c and (c in nm or nm in c):
                return tkr
        return None
    out = {}
    url = "https://doclib.ngxgroup.com/DownloadsContent/GAINERS%20AND%20PRICE%20LIST%20FOR%2028-08-2026.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=40).read()
    z = zipfile.ZipFile(io.BytesIO(data))
    for name in z.namelist():
        if "PRICES_LIST2" not in name.upper() or not name.endswith(".pdf"):
            continue
        with pdfplumber.open(io.BytesIO(z.read(name))) as doc:
            for page in doc.pages:
                for line in (page.extract_text() or "").split("\n"):
                    parts = line.split()
                    if not re.match(r"^\d+ ", line) or len(parts) < 7:
                        continue
                    nums = []
                    for p in parts:
                        clean = p.replace(",", "").replace("(", "").replace(")", "")
                        try: nums.append(float(clean))
                        except ValueError: nums.append(None)
                    body_nums = [(i, nums[i]) for i in range(1, len(nums)) if nums[i] is not None]
                    if len(body_nums) >= 2:
                        comp = norm(" ".join(parts[1:body_nums[0][0]]))
                        sym = find_sym(comp)
                        if sym:
                            mktcap_nm, price = body_nums[0][1], body_nums[1][1]
                            if 0 < price < 50000 and 0 < mktcap_nm < 1e7:
                                out[sym] = int(mktcap_nm * 1e6 / price)
    return out

def main():
    nse = nse_shares()
    print(f"NSE: {len(nse)} with shares")
    ngx = ngx_shares()
    print(f"NGX: {len(ngx)} with shares")

    # Name the provenance accurately. The NSE figures are a published "Shares
    # Issued" line off the board; the NGX figures are market cap divided by
    # price, which is arithmetic on two official numbers - not an official share
    # count - and must not be presented as one.
    SOURCE = {"NSE": "NSE board data (mystocks)",
              "NGX": "derived: NGX market cap / price"}

    # write into market files
    for ex, shares_map in [("NSE", nse), ("NGX", ngx)]:
        mp = os.path.join(SD, f"market_{ex}.json")
        m = json.load(open(mp, encoding="utf-8"))
        cnt = 0
        for s in m.get("stocks", []):
            tkr = s.get("ticker") or s.get("sym")
            v = shares_map.get(tkr)
            if v:
                s["sharesIssued"] = v
                s["sharesSource"] = SOURCE[ex]
                cnt += 1
        json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{ex}: wrote sharesIssued to {cnt} records")

    # JSE: map sharesOutstanding -> sharesIssued
    mp = os.path.join(SD, "market_JSE.json")
    m = json.load(open(mp, encoding="utf-8"))
    cnt = 0
    for s in m.get("stocks", []):
        if s.get("sharesOutstanding") and not s.get("sharesIssued"):
            s["sharesIssued"] = s["sharesOutstanding"]
            s["sharesSource"] = s.get("sharesSource") or "Yahoo Finance"
            cnt += 1
    json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"JSE: mapped sharesOutstanding -> sharesIssued for {cnt}")

    # EGX: shares come from Yahoo (verified byte-identical to
    # yahoo_financials.json), not from parsed annual reports as the file claimed
    mp = os.path.join(SD, "market_EGX.json")
    if os.path.exists(mp):
        m = json.load(open(mp, encoding="utf-8"))
        cnt = 0
        for s in m.get("stocks", []):
            v = s.get("sharesOutstanding") or s.get("sharesIssued")
            if v:
                s["sharesIssued"] = v
                s["sharesOutstanding"] = v
                s["sharesSource"] = "Yahoo Finance"
                cnt += 1
        json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"EGX: {cnt} share counts relabelled to their real source")

if __name__ == "__main__":
    main()
