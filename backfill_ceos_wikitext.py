#!/usr/bin/env python3
"""backfill_ceos_wikitext.py - targeted CEO backfill for the ~80 biggest
missing names using the PROVEN wikitext key_people parser (the method that
produced the existing 170 JSE names). Runs each title through the
title-matching ladder, then extracts the CEO from the infobox.

Rate: ~1.5s/symbol + retries -> ~3-4 min for 80 targets. Writes
static_data/ceos.json (merges).
"""
import json, os, re, sys, time, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "ceos.json")
UA = {"User-Agent": "Mozilla/5.0 (MUTXRI-TERMINAL research bot; contact j@mutxriterminal.com)"}

def api_get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def get_wikitext(title):
    """fetch page wikitext, return None on failure"""
    try:
        t = urllib.parse.quote(title.replace(" ", "_"))
        d = api_get(f"https://en.wikipedia.org/w/api.php?action=parse&page={t}&prop=wikitext&format=json&formatversion=2")
        return d.get("parse", {}).get("wikitext", "")
    except Exception:
        return None

def extract_ceo(wt):
    """parse key_people infobox, return the CEO name or None"""
    if not wt:
        return None
    m = re.search(r"\|\s*key_people\s*=\s*((?:[^\n]|\n\*)[^\n]*){1,6}", wt, re.I)
    if not m:
        return None
    val = m.group(1)
    parts = re.split(r"<br\s*/?>|\n\*", val)
    for part in parts:
        p = part.strip()
        if re.search(r"\bCEO\b|chief executive", p, re.I):
            # strip wiki markup
            p = re.sub(r"\[\[([^|\]]*\|)?([^\]]*)\]\]", r"\2", p)
            p = re.sub(r"\{\{[^{}]*\}\}", "", p)
            p = re.sub(r"\(([^)]*)\)", "", p)
            p = re.sub(r"\b(CEO|Chief Executive Officer|Chief Executive)\b.*$", "", p, flags=re.I)
            p = re.sub(r"[,\s]+$", "", p)
            p = p.strip()
            if p and len(p) > 3:
                return p
    return None

def search_title(name):
    """find the best Wikipedia title for a company name"""
    try:
        d = api_get("https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=" +
                    urllib.parse.quote(name) + "&format=json&srlimit=3")
        for hit in d.get("query", {}).get("search", []):
            t = hit.get("title", "")
            # skip disambiguation / lists
            if any(x in t.lower() for x in ["disambiguation", "list of", "template"]):
                continue
            return t
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

    targets = {
        "JSE": {
            "CPF.JO": "Investec", "IMP.JO": "Impala Platinum", "DRD.JO": "DRDGOLD",
            "SNH.JO": "Sanlam", "REM.JO": "Remgro", "EXX.JO": "Exxaro Resources",
            "BGA.JO": "Bidvest Group", "TKG.JO": "Tongaat Hulett", "CLS.JO": "Clicks Group",
            "MNP.JO": "Mondi", "TBS.JO": "Tiger Brands", "SHP.JO": "Shoprite Holdings",
            "WHL.JO": "Woolworths Holdings", "MRP.JO": "Mr Price", "PPC.JO": "PPC (company)",
            "SAP.JO": "Sappi", "AVI.JO": "AVI Limited", "TFG.JO": "The Foschini Group",
            "SPP.JO": "SPAR Group", "DTC.JO": "Datatec", "OMN.JO": "Omnia Holdings",
            "ARI.JO": "African Rainbow Minerals", "ALT.JO": "Altron", "CML.JO": "Coronation Fund Managers",
            "NTC.JO": "Netcare", "LHC.JO": "Life Healthcare", "TRU.JO": "Truworths",
            "GND.JO": "Grindrod", "BVT.JO": "Bidcorp", "QIN.JO": "Quilter",
            "JSE.JO": "JSE Limited", "NED.JO": "Nedbank", "SBK.JO": "Standard Bank",
            "FSR.JO": "FirstRand", "SOL.JO": "Sasol", "AGL.JO": "Anglo American plc",
            "GLN.JO": "Glencore", "MTN.JO": "MTN Group", "VOD.JO": "Vodacom",
            "RMI.JO": "Rand Merchant Investment Holdings", "AMS.JO": "Anglo American Platinum",
            "KIO.JO": "Kumba Iron Ore", "NHM.JO": "Northam Platinum", "GFI.JO": "Gold Fields",
            "HAR.JO": "Harmony Gold", "CFR.JO": "Compagnie Financiere Richemont",
            "BTI.JO": "British American Tobacco", "AEE.JO": "African Equity Empowerment Investments",
        },
        "EGX": {
            "COMI.CA": "Commercial International Bank", "CCAP.CA": "Credit Agricole Egypt",
            "ESRS.CA": "Ezz Steel", "TMGH.CA": "Talaat Moustafa Group", "EFIH.CA": "EFG Hermes",
            "SWDY.CA": "El Sewedy Electric", "JUFO.CA": "Juhayna Food Industries",
            "ORWE.CA": "Orascom Construction", "AMOC.CA": "Alexandria Mineral Oils",
            "PHDC.CA": "Palm Hills Developments", "HELI.CA": "Heliopolis Housing",
            "EAST.CA": "Eastern Company", "ADIB.CA": "Abu Dhabi Islamic Bank",
            "EKHO.CA": "El Ezz Dekheila", "CIB.CA": "Commercial International Bank",
        },
        "NGX": {
            "MTNN": "MTN Nigeria", "DANGCEM": "Dangote Cement", "GTCO": "Guaranty Trust Holding Company",
            "ACCESSCORP": "Access Holdings", "SEPLAT": "Seplat Energy", "NB": "Nigerian Breweries",
            "FBNH": "FBN Holdings", "ETI": "Ecobank Transnational Incorporated",
            "WAPCO": "Lafarge Africa", "FLOURMILL": "Flour Mills of Nigeria",
            "DANGSUGAR": "Dangote Sugar Refinery", "NASCON": "Nascon Allied Industries",
            "TRANSCORP": "Transnational Corporation of Nigeria", "BUACEMENT": "BUA Cement",
            "BUAFOODS": "BUA Foods", "STANBIC": "Stanbic IBTC Holdings", "NESTLE": "Nestle Nigeria",
            "INTBREW": "International Breweries", "OANDO": "Oando", "TOTAL": "TotalEnergies",
            "UACN": "UAC of Nigeria", "FCMB": "FCMB Group", "FIDELITYBK": "Fidelity Bank Nigeria",
            "STERLINGNG": "Sterling Bank", "UNILEVER": "Unilever Nigeria", "GEREGU": "Geregu Power",
            "NGXGROUP": "Nigerian Exchange Group", "CADBURY": "Cadbury Nigeria",
            "GUINNESS": "Guinness Nigeria", "AIICO": "AIICO Insurance", "CONOIL": "Conoil",
            "PZ": "PZ Cussons Nigeria", "JAIZBANK": "Jaiz Bank", "UBA": "United Bank for Africa",
            "VERITASKAP": "Veritas Kapital", "ETRANZACT": "eTranzact", "MANSARD": "Mansard Insurance",
            "WAPIC": "Wapic Insurance", "SUNUASSUR": "Sunu Assurances",
        },
        "NSE": {
            "KCB": "KCB Group", "EABL": "East African Breweries", "COOP": "Co-operative Bank of Kenya",
            "NCBA": "NCBA Group", "SCBK": "Standard Chartered Kenya", "KPLC": "Kenya Electricity Generating Company",
            "KNRE": "Kenya Reinsurance", "KEGN": "Kenya Electricity Generating Company",
            "CIC": "CIC Insurance Group", "IMH": "I&M Holdings", "JUB": "Jubilee Insurance",
            "CARB": "Carbacid Investments", "BAT": "British American Tobacco Kenya",
            "BAMB": "Bamburi Cement", "TOTL": "TotalEnergies Kenya", "UNGA": "Unga Group",
            "WTK": "WPP Scangroup", "CGEN": "Car and General", "EVRD": "Eveready East Africa",
            "HAFR": "HF Group", "LIMT": "Limuru Tea", "LBTY": "Liberty Kenya",
            "SMER": "Sameer Africa", "PORT": "East African Portland Cement",
            "KAPC": "Kapchorua Tea", "EGAD": "Eaagads", "TPSE": "TPS Eastern Africa",
            "TCL": "Trans-Century", "LKL": "Longhorn Publishers", "NBV": "Nairobi Business Ventures",
            "SCAN": "Scangroup", "SGL": "Safaricom", "FTGH": "Furniture Dealers",
            "KURV": "Kurvitsa", "HBE": "Home Afrika", "UMME": "Ummeme",
            "AMAC": "Amaco Insurance", "SKL": "Sasini", "KPC": "Kenya Pipeline",
            "LAPR": "Laptrust", "ORCH": "Orchard Fund",
        },
    }
    todo = []
    for ex, d in targets.items():
        for sym, name in d.items():
            if sym not in existing:
                todo.append((ex, sym, name))
    print(f"todo: {len(todo)} (existing {len(existing)})", flush=True)

    found = 0
    for i, (ex, sym, name) in enumerate(todo):
        ceo = None
        # title ladder: exact -> normalized -> search
        title = search_title(name)
        if title:
            ceo = extract_ceo(get_wikitext(title))
        time.sleep(0.8)
        if not ceo and ex in ("NGX", "NSE"):
            # try the exchange short name
            title2 = search_title(name.split(" ")[0] + " " + name.split(" ")[1] if len(name.split()) > 1 else name)
            if title2 and title2 != title:
                ceo = extract_ceo(get_wikitext(title2))
                time.sleep(0.8)
        if ceo:
            existing[sym] = ceo
            found += 1
            print(f"  + {ex} {sym}: {ceo}", flush=True)
        else:
            print(f"  - {ex} {sym}: no CEO found", flush=True)
        if (i + 1) % 10 == 0:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=1)
            print(f"  ... {i+1}/{len(todo)} (found {found})", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
    print(f"DONE: {found} new CEOs, total {len(existing)}", flush=True)

if __name__ == "__main__":
    main()
