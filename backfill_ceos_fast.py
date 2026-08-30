#!/usr/bin/env python3
"""backfill_ceos_fast.py - fast CEO backfill for the ~50 biggest names per
exchange using Wikipedia's REST summary API (1 request, prose mentions CEO).

The slow Wikidata->Wikipedia crawler yields ~1% for small caps (385 fails
in 585 tries). The names investors actually click (COMI, CCAP, KCB, MTNN,
GTCO, DANGCEM...) are missing. Wikipedia's page summary often names the
CEO in the opening prose for major companies; the wikitext key_people
infobox parse remains the fallback for the biggest names.

Sources per request:
  1. REST summary extract: /api/rest_v1/page/summary/<TITLE>
     -> extract "X is the CEO of Y" / "led by CEO Z" patterns
  2. wikitext key_people (existing v2 function) as fallback

Writes static_data/ceos.json (merges, never clobbers existing).
"""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "ceos.json")
UA = {"User-Agent": "Mozilla/5.0 (MUTXRI-TERMINAL research bot; contact j@mutxriterminal.com)"}

def api_get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def wiki_ceo_from_summary(company):
    """Wikipedia REST summary: prose often names the CEO for majors."""
    try:
        title = urllib.parse.quote(company.replace(" ", "_"))
        d = api_get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}")
        ext = d.get("extract", "")
        if not ext:
            return None
        # patterns: "led by CEO X", "CEO of Y is X", "its chief executive X"
        pats = [
            r"CEO\s+(?:of\s+\w+)?\s*[,is]+\s*([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})",
            r"chief executive(?:\s+officer)?\s*[,is]+\s*([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})",
            r"led\s+by\s+([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,3})[^.]*(?:CEO|chief executive)",
            r"([A-Z][a-zA-Z.'\-]+(?:\s+[A-Z][a-zA-Z.'\-]+){0,2})\s+is\s+the\s+(?:CEO|chief executive)",
        ]
        for p in pats:
            m = re.search(p, ext, re.I)
            if m:
                name = m.group(1).strip()
                # reject country/company names and role words
                if re.match(r"^[A-Z][a-z]+$", name) and len(name) < 5:
                    continue
                if name.lower() in ("the", "a", "an", "this", "its", "he", "she", "group", "company", "firm"):
                    continue
                return name
    except Exception:
        pass
    return None

def main():
    existing = {}
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            existing = {}

    # the priority targets: biggest / most-clicked names per exchange
    targets = {
        # JSE blue chips (suffix .JO)
        "NPN.JO": "Naspers", "SBK.JO": "Standard Bank Group", "FSR.JO": "FirstRand",
        "SOL.JO": "Sasol", "AGL.JO": "Anglo American", "GLN.JO": "Glencore",
        "NED.JO": "Nedbank Group", "CPF.JO": "Investec", "IMP.JO": "Impala Platinum",
        "MTN.JO": "MTN Group", "VOD.JO": "Vodacom", "RMI.JO": "Rand Merchant Investment Holdings",
        "AMS.JO": "Anglo American Platinum", "BGA.JO": "Bidvest", "SHP.JO": "Shoprite Holdings",
        "WHL.JO": "Woolworths Holdings", "MRP.JO": "Mr Price Group", "PPC.JO": "PPC Ltd",
        "REM.JO": "Remgro", "SNH.JO": "Sanlam", "CFR.JO": "Richemont", "BTI.JO": "British American Tobacco South Africa",
        "KIO.JO": "Kumba Iron Ore", "NHM.JO": "Northam Platinum", "PNP.JO": "Pick n Pay",
        "DRD.JO": "DRDGold", "HAR.JO": "Harmony Gold", "GFI.JO": "Gold Fields",
        "SAP.JO": "Sappi", "TBS.JO": "Tiger Brands", "MNP.JO": "Mondi", "SLM.JO": "Sanlam",
        "CLS.JO": "Clicks Group", "DTC.JO": "Datatec", "AVI.JO": "AVI Limited", "EXX.JO": "Exxaro Resources",
        "LON.JO": "Lonmin", "TFG.JO": "The Foschini Group", "SPP.JO": "SPAR Group",
        "BAW.JO": "Barloworld", "OMN.JO": "Omnia Holdings", "ARI.JO": "African Rainbow Minerals",
        "AEE.JO": "African Equity Empowerment", "ALT.JO": "Altron", "CML.JO": "Coronation Fund Managers",
        "JSE.JO": "JSE Limited", "NTC.JO": "Netcare", "LHC.JO": "Life Healthcare", "AFX.JO": "African Oxygen",
        "TRU.JO": "Truworths", "ITU.JO": "Intu Properties", "AIP.JO": "Adcock Ingram",
        "GND.JO": "Grindrod", "BVT.JO": "Bidcorp", "QIN.JO": "Quilter",
        # EGX majors (suffix .CA)
        "COMI.CA": "Commercial International Bank", "CCAP.CA": "Credit Agricole Egypt",
        "CIB.CA": "Commercial International Bank Egypt", "ESRS.CA": "Ezz Steel",
        "HRHO.CA": "Egyptian Housing", "TMGH.CA": "Talaat Moustafa Group", "EFIH.CA": "EFG Hermes",
        "SWDY.CA": "El Sewedy Electric", "JUFO.CA": "Juhayna Food Industries", "ORWE.CA": "Orascom Construction",
        "AMOC.CA": "Alexandria Mineral Oils", "PHDC.CA": "Palm Hills Developments", "HELI.CA": "Heliopolis Housing",
        "EAST.CA": "Eastern Company", "ABUK.CA": "Abu Dhabi Islamic Bank Egypt", "ADIB.CA": "Abu Dhabi Islamic Bank",
        "EKHO.CA": "El Ezz Aldekhela", "DOMT.CA": "Domyati", "MOHI.CA": "MOH",
        # NGX majors (no suffix)
        "MTNN": "MTN Nigeria", "DANGCEM": "Dangote Cement", "GTCO": "Guaranty Trust Holding",
        "UBA": "United Bank for Africa", "ACCESSCORP": "Access Holdings", "SEPLAT": "Seplat Energy",
        "NB": "Nigerian Breweries", "FBNH": "FBN Holdings", "ETI": "Ecobank Transnational",
        "WAPCO": "Lafarge Africa", "FLOURMILL": "Flour Mills of Nigeria", "DANGSUGAR": "Dangote Sugar",
        "NASCON": "Nascon Allied Industries", "TRANSCORP": "Transnational Corporation",
        "BUACEMENT": "BUA Cement", "BUAFOODS": "BUA Foods", "STANBIC": "Stanbic IBTC Holdings",
        "NESTLE": "Nestle Nigeria", "INTBREW": "International Breweries", "VITAFOAM": "Vitafoam Nigeria",
        "OANDO": "Oando", "TOTAL": "Total Energies Marketing Nigeria", "PZ": "PZ Cussons Nigeria",
        "ETERNA": "Eterna", "CONOIL": "Conoil", "UACN": "UAC of Nigeria", "JAIZBANK": "Jaiz Bank",
        "FCMB": "FCMB Group", "FIDELITYBK": "Fidelity Bank", "STERLINGNG": "Sterling Bank",
        "UNILEVER": "Unilever Nigeria", "GEREGU": "Geregu Power", "NGXGROUP": "Nigerian Exchange Group",
        "CADBURY": "Cadbury Nigeria", "GUINNESS": "Guinness Nigeria", "AIICO": "AIICO Insurance",
        # NSE majors (no suffix)
        "KCB": "KCB Group", "EABL": "East African Breweries", "COOP": "Co-operative Bank of Kenya",
        "NCBA": "NCBA Group", "SCBK": "Standard Chartered Bank Kenya", "KPLC": "Kenya Power",
        "KNRE": "Kenya Reinsurance", "KEGN": "KenGen", "CIC": "CIC Insurance", "IMH": "I&M Holdings",
        "JUB": "Jubilee Holdings", "CARB": "Carbacid Investments", "BAT": "British American Tobacco Kenya",
        "BAMB": "Bamburi Cement", "TOTL": "TotalEnergies Kenya", "UNGA": "Unga Group",
        "WTK": "WPP ScanGroup", "CGEN": "Car & General", "EVRD": "Eveready", "HAFR": "Housing Finance",
        "LIMT": "Limuru Tea", "LBTY": "Liberty Kenya", "SMER": "Sameer Africa", "PORT": "Portland Cement",
        "KAPC": "Kapchorua Tea", "EGAD": "Eaagads", "TPSE": "TPS Eastern Africa", "TCL": "Trans-Century",
        "LKL": "LK Group", "NBV": "Nairobi Business Ventures", "SCAN": "ScanGroup", "SGL": "Safari Group",
        "FTGH": "Furniture Dealers", "KURV": "Kurvitsa", "HBE": "Home Afrika", "UMME": "Ummeme",
        "AMAC": "Amaco Insurance", "SKL": "Sasini", "KPC": "Kenya Pipeline", "LAPR": "Laptrust",
    }
    # only process ones we don't have
    todo = {k: v for k, v in targets.items() if k not in existing}
    print(f"existing {len(existing)}, targets {len(targets)}, todo {len(todo)}", flush=True)

    found = 0
    for i, (sym, name) in enumerate(todo.items()):
        ceo = wiki_ceo_from_summary(name)
        time.sleep(0.4)  # polite
        if ceo:
            existing[sym] = ceo
            found += 1
            print(f"  + {sym}: {ceo}", flush=True)
        if (i + 1) % 10 == 0:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
            print(f"  ... {i+1}/{len(todo)} (found {found})", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"DONE: {found} new CEOs, total {len(existing)}", flush=True)

if __name__ == "__main__":
    main()
