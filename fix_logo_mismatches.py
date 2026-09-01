#!/usr/bin/env python3
"""fix_logo_mismatches.py - remove company logos matched to the wrong company.

logos.json was built by matching security names to a domain list, which pairs
any security with "Equity" in its name to Equity Group Holdings of Kenya and
puts an Egyptian spinning mill behind AVI's South African logo. A wrong logo is
worse than no logo - the monogram fallback is honest, a rival's mark is not.

Removals are listed explicitly rather than inferred, so the file stays
reviewable; the two replacements are same-group domains that are not in doubt.
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(BASE, "static_data", "logos.json")

# symbol -> the domain it is wrongly pointed at (checked before removing, so a
# rebuilt logos.json that fixed one of these on its own is left alone)
WRONG = {
    "ABAM1.JO": "equitygroupholdings.com",   # ABSA INVEST EQUITY AMC, matched on "Equity"
    "AMC009.JO": "equitygroupholdings.com",  # SB Baobab Equity AMC
    "AEE.JO": "equitygroupholdings.com",     # African Equity Empowerment Investments
    "SPIN": "avi.co.za",                     # Alex Spinning & Weaving (Egypt)
    "APSW": "avi.co.za",                     # Arab Polvara Spinning & Weaving (Egypt)
    "LCSW": "cic.co.ke",                     # Lecico Egypt
    "ELEC": "cabltd.co.ke",                  # Electro Cable Egypt
    "EOSB": "ubagroup.com",                  # El Orouba Securities Brokerage (Egypt)
    "LBH.JO": "libertykenya.com",            # Liberty Holdings (South Africa)
    "L2D.JO": "libertykenya.com",            # Liberty Two Degrees (South Africa)
}

# same group, different country - the right domain is not in doubt
REPLACE = {
    "ABSP.JO": ("absa.co.ke", "absa.africa"),        # ABSA Bank preference shares, JSE
    "STANBIC": ("stanbic.co.ke", "stanbicibtc.com"),  # Stanbic IBTC, NGX
}


def main():
    logos = json.load(open(PATH, encoding="utf-8"))
    removed, fixed, untouched = [], [], []

    for sym, dom in WRONG.items():
        if logos.get(sym) == dom:
            del logos[sym]
            removed.append(sym)
        elif sym in logos:
            untouched.append(f"{sym}={logos[sym]}")

    for sym, (old, new) in REPLACE.items():
        if logos.get(sym) == old:
            logos[sym] = new
            fixed.append(f"{sym} {old} -> {new}")
        elif sym in logos:
            untouched.append(f"{sym}={logos[sym]}")

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(logos, f, ensure_ascii=False)

    print(f"logos: {len(removed)} wrong mappings removed -> monogram fallback")
    for s in removed:
        print(f"    - {s}")
    for s in fixed:
        print(f"    ~ {s}")
    if untouched:
        print(f"  {len(untouched)} already differ from the recorded bad value: {untouched}")
    print(f"logos.json now holds {len(logos)} mappings")


if __name__ == "__main__":
    main()
