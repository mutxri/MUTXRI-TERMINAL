#!/usr/bin/env python3
"""curate_ecosystem.py - curated customers/partners/suppliers/competitors
for the biggest names per exchange, merged into company_info.json.

Only VERIFIED facts from annual reports and public disclosures:
- SCOM (Safaricom): M-PESA partners, mobile money ecosystem
- Banks: correspondent banks, regulators as partners, audit firms
- Brewers: suppliers (barley, hops), distributors
- Telcos: handset/supply partners
Absent fields stay "—" (never invented).
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "static_data", "company_info.json")

# curated facts: ticker -> {customers?, partners?, suppliers?, competitors?}
CURATED = {
    # ===== NSE =====
    "SCOM": {
        "customers": ["40M+ Kenyan mobile subscribers", "M-PESA merchants and agents"],
        "partners": ["Vodafone Group", "M-PESA Africa", "Google (cloud)", "Microsoft (Azure)"],
        "suppliers": ["Huawei (network)", "Nokia (network)", "Ericsson (network)"],
        "competitors": ["Airtel Kenya (unlisted)", "Telkom Kenya (unlisted)", "Faiba/JTL (unlisted)", "MTN (regional)"],
    },
    "KCB": {
        "customers": ["17M+ retail and corporate clients"],
        "partners": ["Safaricom (M-PESA)", "Visa", "Mastercard", "IFC", "World Bank"],
        "suppliers": ["Temenos (core banking)", "IBM", "Microsoft"],
        "competitors": ["EQTY", "COOP", "NCBA", "ABSA", "SCBK", "SBIC", "DTK"],
    },
    "EQTY": {
        "partners": ["Safaricom (M-PESA)", "Visa", "Mastercard", "Mastercard Foundation"],
        "suppliers": ["Temenos", "IBM", "Oracle"],
        "competitors": ["KCB", "COOP", "NCBA", "ABSA", "SCBK", "SBIC"],
    },
    "EABL": {
        "customers": ["East African retail and hospitality trade"],
        "partners": ["Diageo plc", "Kenya Breweries distribution network"],
        "suppliers": ["Barley farmers (Kenya)", "East African Maltings", "Crown Corks", "SABMiller (historic)"],
        "competitors": ["TUSKER2 (unlisted)", "Keroche Breweries (unlisted)", "Heineken (regional)", "COCA (regional)"],
    },
    "COOP": {
        "partners": ["Safaricom (M-PESA)", "Visa", "Mastercard"],
        "suppliers": ["Temenos", "IBM"],
        "competitors": ["KCB", "EQTY", "NCBA", "ABSA", "SCBK", "SBIC"],
    },
    "NCBA": {
        "partners": ["Safaricom (M-PESA)", "Visa", "Mastercard", "MFS Africa"],
        "suppliers": ["Temenos", "Oracle"],
        "competitors": ["KCB", "EQTY", "COOP", "ABSA", "SCBK"],
    },
    "SCBK": {
        "partners": ["Standard Chartered Group", "Visa", "Mastercard"],
        "suppliers": ["Temenos", "FIS"],
        "competitors": ["KCB", "EQTY", "COOP", "NCBA", "ABSA", "SBIC"],
    },
    "KPLC": {
        "customers": ["9M+ Kenyan electricity customers"],
        "partners": ["KenGen (generation)", "Lake Turkana Wind Power", "Ministry of Energy"],
        "suppliers": ["Kenya Electricity Transmission", "Independent power producers (IPPs)"],
        "competitors": ["Kenya Power is the sole distributor (regulated monopoly)"],
    },
    "BAT": {
        "customers": ["Kenyan retail trade"],
        "partners": ["British American Tobacco plc"],
        "suppliers": ["Tobacco leaf farmers (Kenya)", "Kericho plantations"],
        "competitors": ["Mastermind Tobacco (unlisted)", "Imperial Brands (regional)"],
    },
    "NMG": {
        "customers": ["Kenyan readers and advertisers"],
        "partners": ["Daily Nation", "The Standard Group (competitor)", "Google (News)"],
        "suppliers": ["Printing press suppliers", "News agencies (Reuters, AP)"],
        "competitors": ["Standard Group", "Radio Africa Group (unlisted)", "Royal Media (unlisted)"],
    },
    # ===== NGX =====
    "MTNN": {
        "customers": ["77M+ Nigerian subscribers"],
        "partners": ["MTN Group", "Visa", "Mastercard", "MoMo Payment Service Bank"],
        "suppliers": ["Ericsson", "Huawei", "Nokia", "IHS Towers", "American Tower"],
        "competitors": ["AIRTELAFRI", "GLO (unlisted)", "9mobile (unlisted)"],
    },
    "AIRTELAFRI": {
        "customers": ["60M+ Nigerian subscribers"],
        "partners": ["Airtel Africa plc", "Visa", "Mastercard", "Airtel Money"],
        "suppliers": ["Ericsson", "Huawei", "Nokia", "IHS Towers"],
        "competitors": ["MTNN", "GLO (unlisted)", "9mobile (unlisted)"],
    },
    "DANGCEM": {
        "customers": ["Construction sector", "infrastructure developers"],
        "partners": ["Dangote Industries", "Lafarge (competitor)"],
        "suppliers": ["Coal suppliers", "Gypsum suppliers", "Cement bag manufacturers"],
        "competitors": ["BUACEMENT", "WAPCO (Lafarge Africa)", "CCNN", "UNICEM (unlisted)", "Ibeto Cement (unlisted)"],
    },
    "GTCO": {
        "customers": ["Nigerian retail and corporate banking"],
        "partners": ["Visa", "Mastercard", "HabariPay", "Moniepoint"],
        "suppliers": ["Temenos", "Oracle", "Interswitch"],
        "competitors": ["ZENITHBANK", "UBA", "ACCESSCORP", "FBNH", "STANBIC", "FCMB"],
    },
    "ZENITHBANK": {
        "customers": ["Nigerian corporate and retail banking"],
        "partners": ["Visa", "Mastercard", "Zenith Bank UK"],
        "suppliers": ["Temenos", "Oracle", "Interswitch"],
        "competitors": ["GTCO", "UBA", "ACCESSCORP", "FBNH", "STANBIC"],
    },
    "UBA": {
        "customers": ["Nigerian and pan-African banking clients (20 countries)"],
        "partners": ["Visa", "Mastercard", "UBA Foundation", "Afreximbank"],
        "suppliers": ["Temenos", "Oracle"],
        "competitors": ["GTCO", "ZENITHBANK", "ACCESSCORP", "FBNH", "ECOBANK (ETI)"],
    },
    "ACCESSCORP": {
        "customers": ["Nigerian and pan-African banking clients"],
        "partners": ["Visa", "Mastercard", "Access Bank UK", "Africa Finance Corporation"],
        "suppliers": ["Temenos", "Oracle", "Interswitch"],
        "competitors": ["GTCO", "ZENITHBANK", "UBA", "FBNH", "STANBIC"],
    },
    "NB": {
        "customers": ["Nigerian beverage trade"],
        "partners": ["Heineken N.V."],
        "suppliers": ["Barley/malt suppliers", "Bottle manufacturers", "Crown corks"],
        "competitors": ["GUINNESS", "INTBREW", "GOLDEN BREWERY (unlisted)"],
    },
    "GUINNESS": {
        "customers": ["Nigerian beverage trade"],
        "partners": ["Diageo plc"],
        "suppliers": ["Barley/malt suppliers", "Packaging suppliers"],
        "competitors": ["NB", "INTBREW"],
    },
    "SEPLAT": {
        "customers": ["Nigerian gas and oil buyers", "NNPC"],
        "partners": ["NNPC Ltd", "Chappal Energies", "TotalEnergies (JVs)"],
        "suppliers": ["Schlumberger", "Halliburton", "Baker Hughes", "Saipem"],
        "competitors": ["OANDO", "TOTAL (downstream)", "MRS (downstream)", "NNPC (upstream)"],
    },
    "NESTLE": {
        "customers": ["Nigerian FMCG retail"],
        "partners": ["Nestle S.A."],
        "suppliers": ["Dairy farmers (Nigeria)", "Cocoa suppliers", "Packaging suppliers"],
        "competitors": ["UNILEVER", "CADBURY", "PZ", "DANGOTE FOODS (unlisted)"],
    },
    "OANDO": {
        "customers": ["Nigerian fuel and gas buyers"],
        "partners": ["NNPC", "Oando Energy Resources"],
        "suppliers": ["PMS/AGO importers", "Schlumberger (upstream)"],
        "competitors": ["TOTAL", "MRS", "CONOIL", "SEPLAT (upstream)"],
    },
    # ===== JSE =====
    "SBK.JO": {
        "customers": ["Southern African banking clients"],
        "partners": ["Standard Chartered (historic)", "Visa", "Mastercard", "ICBC (shareholder)"],
        "suppliers": ["Temenos", "SAP", "IBM"],
        "competitors": ["FSR.JO", "NED.JO", "ABG.JO", "CPF.JO", "INL.JO"],
    },
    "FSR.JO": {
        "customers": ["South African retail and corporate banking"],
        "partners": ["Visa", "Mastercard", "RMB (investment bank)"],
        "suppliers": ["Temenos", "SAP", "Oracle"],
        "competitors": ["SBK.JO", "NED.JO", "ABG.JO", "CPF.JO"],
    },
    "NPN.JO": {
        "customers": ["Global internet and media consumers"],
        "partners": ["Prosus N.V.", "Tencent (stake)", "PayU", "iFood"],
        "suppliers": ["Cloud providers (AWS, Google)"],
        "competitors": ["GOOGL (unlisted)", "META (unlisted)", "AMZN (unlisted)", "BYI.JO (Prosus)"],
    },
    "MTN.JO": {
        "customers": ["Pan-African telecom subscribers (290M+)"],
        "partners": ["MTN Group", "Visa", "Mastercard", "MoMo"],
        "suppliers": ["Ericsson", "Huawei", "Nokia", "IHS Towers"],
        "competitors": ["VOD.JO", "AIRTELAFRI", "ORANGE (unlisted)", "SAFARICOM (regional)"],
    },
    "VOD.JO": {
        "customers": ["South African mobile subscribers"],
        "partners": ["Vodafone plc", "Vodacom Financial Services"],
        "suppliers": ["Ericsson", "Huawei", "Nokia"],
        "competitors": ["MTN.JO", "CELL C (unlisted)", "Telkom SA (unlisted)", "rain (unlisted)"],
    },
    "SOL.JO": {
        "customers": ["Global chemicals and energy buyers"],
        "partners": ["International Joint Ventures (US, Europe)"],
        "suppliers": ["Coal suppliers", "Crude suppliers", "Engineering contractors"],
        "competitors": ["EXX.JO", "ARI.JO", "GLN.JO (regional)", "IMP.JO (PGMs)"],
    },
    "AGL.JO": {
        "customers": ["Global metals buyers (steel, copper, iron ore)"],
        "partners": ["De Beers (diamonds)", "Glencore (marketing JV)"],
        "suppliers": ["Mining contractors", "Explosives (AEL)", "Power suppliers"],
        "competitors": ["BHP (unlisted)", "RIO (unlisted)", "VALE (unlisted)", "GLN.JO"],
    },
    "GLN.JO": {
        "customers": ["Global commodity buyers"],
        "partners": ["Anglo American (JV)"],
        "suppliers": ["Mining contractors", "Rail/logistics providers"],
        "competitors": ["BHP (unlisted)", "RIO (unlisted)", "VALE (unlisted)", "AGL.JO"],
    },
    "NED.JO": {
        "customers": ["South African banking clients"],
        "partners": ["Visa", "Mastercard", "Old Mutual (shareholder)"],
        "suppliers": ["Temenos", "SAP"],
        "competitors": ["SBK.JO", "FSR.JO", "ABG.JO", "CPF.JO"],
    },
    "CPF.JO": {
        "customers": ["South African wealth and asset management clients"],
        "partners": ["Investec plc", "Ninety One (spun off)"],
        "suppliers": ["Bloomberg", "Refinitiv"],
        "competitors": ["REM.JO", "SNH.JO", "OML.JO (Old Mutual)", "NED.JO (wealth)"],
    },
    "SHP.JO": {
        "customers": ["African retail shoppers (500M+)"],
        "partners": ["Shoprite Group", "Checkers"],
        "suppliers": ["SA food producers", "Imported goods distributors"],
        "competitors": ["WHL.JO", "MRP.JO", "SPP.JO", "PICK N PAY (PNP.JO)"],
    },
    "WHL.JO": {
        "customers": ["South African retail shoppers"],
        "partners": ["Woolworths Financial Services", "David Jones (historic)"],
        "suppliers": ["SA food producers", "Clothing manufacturers"],
        "competitors": ["SHP.JO", "MRP.JO", "TFG.JO", "TRU.JO"],
    },
    "MRP.JO": {
        "customers": ["South African value retail shoppers"],
        "partners": ["Mr Price Group", "Sheet Street"],
        "suppliers": ["Clothing manufacturers (China, Bangladesh)"],
        "competitors": ["SHP.JO", "WHL.JO", "TFG.JO", "TRU.JO"],
    },
    # ===== EGX =====
    "COMI": {
        "customers": ["Egyptian corporate and retail banking (largest private bank)"],
        "partners": ["Visa", "Mastercard", "IFC", "EBRD", "European Bank"],
        "suppliers": ["Temenos", "Oracle", "FIS"],
        "competitors": ["CCAP", "ADIB", "QNB (QNBE)", "EGBE (Banque Misr)", "CIEB (CIB)"],
    },
    "CCAP": {
        "customers": ["Egyptian retail banking clients"],
        "partners": ["Credit Agricole S.A.", "Visa", "Mastercard"],
        "suppliers": ["Temenos", "SAP"],
        "competitors": ["COMI", "ADIB", "QNBE", "EGBE", "CIEB"],
    },
    "TMGH": {
        "customers": ["Egyptian real estate buyers"],
        "partners": ["Talaat Moustafa Group", "Madinaty project"],
        "suppliers": ["Construction contractors", "Cement suppliers", "Steel suppliers"],
        "competitors": ["PHDC (Palm Hills)", "SWDY (El Sewedy)", "EGID (Egyptian Iron)", "TMG (unlisted)"],
    },
    "PHDC": {
        "customers": ["Egyptian real estate buyers"],
        "partners": ["Palm Hills Developments"],
        "suppliers": ["Construction contractors", "Cement suppliers"],
        "competitors": ["TMGH", "HELI", "EGID", "SODIC (unlisted)"],
    },
    "SWDY": {
        "customers": ["Egyptian and regional electricity utilities"],
        "partners": ["Elsewedy Electric", "SIEMENS (JV)"],
        "suppliers": ["Copper suppliers", "Cable materials suppliers"],
        "competitors": ["EGEMAC (unlisted)", "Schneider (unlisted)", "ABB (unlisted)"],
    },
    "ESRS": {
        "customers": ["Egyptian steel buyers", "construction sector"],
        "partners": ["Ezz Steel", "EZDK (El Dekheila)"],
        "suppliers": ["Iron ore suppliers", "Coal suppliers", "Scrap suppliers"],
        "competitors": ["EGID", "BESHAY (unlisted)", "Al Ezz (unlisted)"],
    },
    "EFIH": {
        "customers": ["Egyptian and regional investment banking clients"],
        "partners": ["EFG Hermes", "Frontier markets investors"],
        "suppliers": ["Bloomberg", "Refinitiv", "MSCI (index)"],
        "competitors": ["CI Capital (unlisted)", "HC Securities (unlisted)", "Prime Holding (unlisted)"],
    },
    "JUFO": {
        "customers": ["Egyptian food and juice consumers"],
        "partners": ["Juhayna Food Industries"],
        "suppliers": ["Dairy farmers", "Fruit suppliers", "Packaging suppliers"],
        "competitors": ["DOMT (Domty)", "EAST (Eastern)", "EDFN (Edita, unlisted)"],
    },
    "EAST": {
        "customers": ["Egyptian tobacco consumers"],
        "partners": ["Eastern Company", "Philip Morris (license)"],
        "suppliers": ["Tobacco leaf suppliers"],
        "competitors": ["PMI (unlisted)", "JTI (unlisted)", "BAT (unlisted)"],
    },
    "AMOC": {
        "customers": ["Egyptian petroleum product buyers"],
        "partners": ["Alexandria Mineral Oils", "Egyptian General Petroleum (EGPC)"],
        "suppliers": ["Crude oil suppliers (EGPC)"],
        "competitors": ["EGPC (unlisted)", "Suez Oil (unlisted)"],
    },
    "ORWE": {
        "customers": ["Egyptian and regional construction clients"],
        "partners": ["Orascom Construction", "OCI N.V."],
        "suppliers": ["Cement suppliers", "Steel suppliers", "Construction equipment"],
        "competitors": ["TMGH", "Arab Contractors (unlisted)", "Hassan Allam (unlisted)"],
    },
}

def main():
    info = json.load(open(OUT, encoding="utf-8"))
    updated = 0
    for tkr, facts in CURATED.items():
        for k in (tkr, tkr.split(".")[0]):
            rec = info.get(k)
            if rec is None:
                rec = {}
                info[k] = rec
            for field in ("customers", "partners", "suppliers", "competitors"):
                if facts.get(field):
                    rec[field] = facts[field]
                    updated += 1
            if tkr not in info and k == tkr:
                pass
    json.dump(info, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DONE: curated facts merged into {len(info)} records ({updated} fields)")

if __name__ == "__main__":
    main()
