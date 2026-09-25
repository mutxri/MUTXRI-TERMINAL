#!/usr/bin/env python3
"""apply_delisted_filter.py - remove delisted/suspended companies from the
terminal's market data. VERIFIED delisted/suspended lists (public records):

NSE (Kenya): ARM (ARM Cement, delisted 2020), MSC (Mumias Sugar, suspended
2019), DCON (Deacons, delisted 2017), UCHM (Uchumi, receivership/delisted),
OCH (Olympia, suspended). Junk/placeholder tickers with no real listing are
also dropped (FAHR, NBK, HFCK, SMWF, ALP, TRFC).

Also flags securities with no price (suspended listings show price null).

Applies to static_data/market_<EX>.json + static_data/screener_<EX>.json.
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))

DELISTED = {
    "NSE": {
        "ARM": "ARM Cement (delisted 2020)",
        "MSC": "Mumias Sugar (suspended 2019)",
        "DCON": "Deacons East Africa (delisted 2017)",
        "UCHM": "Uchumi Supermarket (receivership)",
        "OCH": "Olympia Capital (suspended)",
    },
    "NGX": {
        # space-variant duplicate of MOFIREIF (same fund, NGX lists it once)
        "MOFI REIF": "duplicate row of MOFIREIF (MOFI Real Estate Income Fund)",
        "ASSOCIATED": "legacy row for ABC Transport Plc: the NGX official price list for 18 September 2026 quotes ABCTRANS and carries no ASSOCIATED line at all, and ABC Transport Plc own audited financial statements record that the company was changed from Associated Bus Company Plc to ABC Transport Plc at the annual general meeting of 12 August 2011. The row carries no price history of its own and no filing of its own, while ABCTRANS carries the live row, the history and the statements.",
        "SET": "legacy code for Secure Electronic Technology Plc, which the exchange now quotes as NSLTECH: the NGX official price list for 18 September 2026 quotes NSLTECH and carries no SET line at all, and the terminal own statement file held under the SET code names the same issuer (Secure Electronic Technology Plc, formerly National Sports Lottery Plc, renamed 6 January 2012). The row carries no price history of its own, while NSLTECH carries the live row, the history and the statements.",
        "ABBEYBANK": "stale misspelling row of ABBEYBDS (Abbey Mortgage Bank Plc); the statement file keyed ABBEYBANK is hollow (one HY 2026 column, every figure null)",
        "AREDEL": "stale misspelling row of ARADEL (Aradel Holdings Plc); duplicate of the priced ARADEL line",
        "INTERBREW": "stale misspelling row of INTBREW (International Breweries Plc); duplicate of the priced INTBREW line",
        "DUNLOP": "DN Tyre and Rubber Plc, delisted from NGX effective 9 April 2026 for operating below the listing standards, per the NGX weekly market report for the week ended 10 April 2026 (Greif Nigeria Plc was delisted the same day)",
        "UBN": "Union Bank of Nigeria Plc, delisted from NGX at the close on 24 November 2023 after the Titan Trust acquisition; no current quotation or statement exists",
        "UNITYBNK": "Unity Bank Plc, suspended from trading on NGX since the close on 25 September 2025 during the Providus Bank amalgamation; no current statement can be collected",
        "DEAPCAP": "legacy NGX ticker of Deap Capital Management & Trust Plc, which completed its corporate transformation and changed its ticker to CMFC in June 2026; the NGX official daily price list quotes DEAPCAP for the last time on 29 June 2026 (3.80 naira) and quotes CMFC from 5 August 2026 onward, and the exchange files the company's audited accounts under the CMFC code (africanfinancials attributes the Deap Capital 2025 abridged report to Critical Minerals Financing Corporation Plc). CMFC carries the live row and the statement",
        "CWAREHOUSE": "phantom NGX code with no quotation: the official daily price list for 18 September 2026, 5 August 2026 and 29 June 2026 carries CWG Plc (formerly Computer Warehouse Group Plc) and no CWAREHOUSE line at all, and the stored CWAREHOUSE row repeats CWG's own 5 August 2026 session (19.20 naira, down 1.79 percent, 1,364,395 shares). CWG carries the live row and the statement",
    },
    "JSE": {
        "NHM": "legacy JSE code of Northam Platinum, renamed Northam Platinum Holdings and now traded as NPH (NPH.JO carries the statement)",
        "AMS": "legacy JSE code of Anglo American Platinum, renamed Valterra Platinum and now traded as VAL (VAL.JO carries the statement)",
        "EOH": "legacy JSE code of EOH Holdings, which now trades as iOCO Limited (IOC); eoh.co.za redirects to ioco.tech",
        "TCP": "legacy JSE code of Transaction Capital, renamed Nutun Limited on 18 March 2025 and now traded as NTU (NTU.JO carries the statement)",
        "GLI": "legacy JSE code of Numeral Ltd, previously Go Life International; the company now trades on the JSE as XII (XII.JO carries the priced row and the statement), per Numeral's audited results for the year ended 28 February 2026 filed with the Stock Exchange of Mauritius, which name JSE share code XII",
        "DIA": "Dipula Income Fund A shares, bought back and cancelled on 6 June 2022 when Dipula collapsed its A and B share structure into a single class; DIB carries the live row and the statement",
        "IPF": "legacy JSE code of Investec Property Fund, renamed Burstone Group Limited and now traded as BTN (BTN.JO carries the statement); JSE SENS documents carry the line Burstone Group Limited (Previously Investec Property Fund)",
        "FVT": "Fairvest Property Holdings, delisted from the JSE at the close on 31 January 2022 after the combination with Arrowhead; Fairvest Limited now trades as FTA and FTB, which carry the statements",
        "AHL": "AH-Vest Limited, delisted from the JSE at the close on 25 August 2025 when Eastern Trading Company took the company private; last trading day 19 August 2025",
        "CUL": "Cullinan Holdings ordinary shares, listing terminated under the 2018 scheme of arrangement (termination of listing at the commencement of trade on 20 March 2018); the CULP preference shares were the line left listed",
        "KBO": "Kibo Energy Plc, suspended from trading on the JSE since the close on 12 August 2025; the audited accounts for the year ended 31 December 2025 are overdue, so no statement can be collected",
    },
    "EGX": {
        "ESRS": "Ezz Steel (delisted from EGX 13 March 2025, moved to OTC)",
        "OCIC": "Orascom Construction Industries SAE (legacy pre-2015 ticker, absent from the EGX current list; successor ORAS.CA is a different entity)",
        "SLTD": "no Mubasher profile; last quoted price July 2016",
        "PSAD": "renamed Rekaz Holding for Investment (RKAZ) Jan 2023; PSAD no longer trades",
        "UNBE": "Union National Bank Egypt (legacy ticker; the entity now operates as Abu Dhabi Commercial Bank-Egypt)",
        "ODID": "Odin for Investment & Development (a different company from EGX:ODIN; merged into Egyptians Housing Development & Reconstruction, EHDR, Sept 2022)",
        "SBAG": "Suez Bags (Mondi acquired 96% Aug 2018; the EGX line no longer trades)",
    },
}

# placeholder/junk tickers with no real company behind them
JUNK = {"FAHR", "NBK", "HFCK", "SMWF", "ALP", "TRFC", "BACC", "BACB"}

def prune_source_files(ex, bad):
    """listing_<EX>.json and stocks.json are REGENERATED by the chain every cycle,
    so a removal applied only to market_/screener_ is silently reverted on the next
    run (and a misspelled duplicate row reappears on the board). Strip the same keys
    from both sources here, so this step enforces the cleanup durably."""
    total = 0
    for path in (os.path.join(BASE, "static_data", f"listing_{ex}.json"),
                 os.path.join(BASE, "stocks.json")):
        if not os.path.exists(path):
            continue
        doc = json.load(open(path, encoding="utf-8"))
        container = doc.get("stocks", doc) if isinstance(doc, dict) else doc
        if isinstance(container, dict):
            if ex not in container or not isinstance(container[ex], list):
                continue
            rows = container[ex]
        elif isinstance(container, list) and os.path.basename(path).startswith("listing_"):
            rows = container
        else:
            continue
        before = len(rows)
        kept = [r for r in rows
                if (r.get("ticker") or (r.get("sym") or "").split(".")[0] or r.get("code")) not in bad]
        if len(kept) != before:
            if isinstance(container, dict):
                container[ex] = kept
            else:
                doc["stocks"] = kept
                if isinstance(doc, dict) and "count" in doc:
                    doc["count"] = len(kept)
            json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"   source: {os.path.basename(path)} {before} -> {len(kept)}")
            total += before - len(kept)
    return total


def apply(ex):
    mpath = os.path.join(BASE, "static_data", f"market_{ex}.json")
    if not os.path.exists(mpath):
        return
    m = json.load(open(mpath, encoding="utf-8"))
    before = len(m.get("stocks", []))
    removed = []
    kept = []
    for s in m.get("stocks", []):
        tkr = s.get("ticker") or (s.get("sym") or "").split(".")[0]
        if tkr in DELISTED.get(ex, {}):
            removed.append((tkr, DELISTED[ex][tkr]))
            continue
        if tkr in JUNK:
            removed.append((tkr, "placeholder"))
            continue
        kept.append(s)
    m["stocks"] = kept
    json.dump(m, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{ex}: {before} -> {len(kept)} ({len(removed)} delisted/junk removed)")
    for t, why in removed:
        print(f"   - {t}: {why}")

    # also apply to screener
    spath = os.path.join(BASE, "static_data", f"screener_{ex}.json")
    if os.path.exists(spath):
        sc = json.load(open(spath, encoding="utf-8"))
        rows = sc.get("rows", sc.get("stocks", []))
        bad = {t for t, _ in removed}
        if isinstance(rows, list):
            kept_rows = [r for r in rows if (r.get("ticker") or (r.get("sym") or "").split(".")[0]) not in bad]
            if "rows" in sc: sc["rows"] = kept_rows
            else: sc["stocks"] = kept_rows
            json.dump(sc, open(spath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"   screener: {len(rows)} -> {len(kept_rows)}")

    # durable: also strip from the two regenerated sources
    prune_source_files(ex, {t for t, _ in removed})

for ex in ["JSE", "EGX", "NGX", "NSE"]:
    apply(ex)
    # The durable source strip used to fire only for keys the MARKET loop had just
    # removed, so a dead ticker that had already left market_<EX>.json on an earlier
    # run stayed in listing_<EX>.json (and stocks.json) forever: EGX showed 373
    # listing rows against 367 market rows, and the seven extras (ESRS, OCIC, ODID,
    # PSAD, SBAG, SLTD, UNBE) kept re-entering every coverage denominator and every
    # gap count. Prune the full verified list, not just this run's removals.
    prune_source_files(ex, set(DELISTED.get(ex, {})) | JUNK)
print("DONE")
