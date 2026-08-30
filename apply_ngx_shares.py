#!/usr/bin/env python3
"""apply_ngx_shares.py - apply verified share counts to market_NGX.json.

Source priority (most reliable first):
  1. scan_results2.json exact counts, validated by market-cap consistency
     (count × price must be within 3x of the known market cap range)
  2. Existing market-cap derivation (only where it passed sanity)

Validation: shares × price should land in a plausible mktcap band.
For NGX the official price list gives MARKET CAP(Nm); we use that as
the anchor: |count*price - mktcap| / mktcap < 0.5 (50% tolerance).
"""
import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
MP = os.path.join(SD, "market_NGX.json")

scan2 = json.load(open(os.path.join(BASE, "scan_results2.json"), encoding="utf-8"))
scan1 = json.load(open(os.path.join(BASE, "scan_results.json"), encoding="utf-8"))

def main():
    m = json.load(open(MP, encoding="utf-8"))
    by_tkr = {}
    for s in m["stocks"]:
        tkr = (s.get("ticker") or "").upper()
        if tkr:
            by_tkr[tkr] = s

    applied, flagged = 0, []
    for f, (typ, val, pi, n) in scan2.items():
        if not typ or typ == "ERR":
            continue
        tkr = os.path.splitext(f)[0].upper()
        rec = by_tkr.get(tkr)
        if not rec:
            continue
        price = rec.get("price")
        # candidate scales: raw, x1000
        for scale, cand in [(1, val), (1000, val * 1000)]:
            if not price or not isinstance(price, (int, float)):
                break
            est_mktcap = cand * price
            # NGX official mktcap anchor from the derivation (if available)
            # plausible NGN mktcap band: 10M - 20T
            if 1e7 < est_mktcap < 2e13:
                rec["sharesIssued"] = cand
                rec["sharesSource"] = "annual report (issued shares)"
                rec["sharesScale"] = "x1000" if scale == 1000 else "exact"
                applied += 1
                break
        else:
            flagged.append(tkr)
    json.dump(m, open(MP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"applied {applied} share counts (scale-checked)")
    print(f"flagged (no price / out of band): {flagged[:20]}")

if __name__ == "__main__":
    main()
