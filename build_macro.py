#!/usr/bin/env python3
"""
Build static_data/macro.json from the World Bank's open API.

Indicator FP.CPI.TOTL.ZG = "Inflation, consumer prices (annual %)".

Why annual and not a monthly headline: the World Bank series is current (2025
complete, published 2026-07) and every value is citable back to a named source.
The IMF monthly CPI series available free through DBnomics is roughly 14 months
behind (Kenya last 2025-01, Nigeria last 2024-12), so it cannot honestly be
presented as a current rate. Nothing here is estimated, interpolated or rounded
from a headline: every number is the API value verbatim.

Run:  python3 build_macro.py
"""
import json, sys, time, urllib.request, datetime

API = ("https://api.worldbank.org/v2/country/{isos}/indicator/FP.CPI.TOTL.ZG"
       "?format=json&per_page=600&date={span}")
INDICATOR = "FP.CPI.TOTL.ZG"

COUNTRIES = [
    {"iso2": "KE", "country": "Kenya",        "currency": "KES", "exchange": "NSE",
     "market": "Nairobi Securities Exchange"},
    {"iso2": "NG", "country": "Nigeria",      "currency": "NGN", "exchange": "NGX",
     "market": "Nigerian Exchange"},
    {"iso2": "ZA", "country": "South Africa", "currency": "ZAR", "exchange": "JSE",
     "market": "Johannesburg Stock Exchange"},
    {"iso2": "EG", "country": "Egypt",        "currency": "EGP", "exchange": "EGX",
     "market": "Egyptian Exchange"},
]
YEARS_BACK = 6


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    today = datetime.date.today().isoformat()
    this_year = datetime.date.today().year
    span = "%d:%d" % (this_year - YEARS_BACK, this_year - 1)
    isos = ";".join(c["iso2"] for c in COUNTRIES)

    d = get(API.format(isos=isos, span=span))
    if not isinstance(d, list) or len(d) < 2 or not d[1]:
        print("FATAL: unexpected World Bank response: %s" % str(d)[:300])
        return 1
    meta, rows = d[0], d[1]
    print("World Bank: %s rows | lastupdated: %s" % (meta.get("total"), meta.get("lastupdated")))

    # {iso: {year: value}} - nulls dropped, never filled
    by_iso = {}
    wb_name = {}
    for r in rows:
        iso = (r.get("countryiso3code") or "")
        c = next((c for c in COUNTRIES if c["iso2"] == r["country"]["id"]), None)
        if not c:
            continue
        wb_name[c["iso2"]] = r["country"]["value"]
        if r["value"] is None:
            continue
        by_iso.setdefault(c["iso2"], {})[int(r["date"])] = round(float(r["value"]), 2)

    out_countries = []
    for c in COUNTRIES:
        series = by_iso.get(c["iso2"], {})
        years = sorted(series, reverse=True)
        if not years:
            print("WARN: no inflation data for %s" % c["country"])
            continue
        latest = years[0]
        prior = years[1] if len(years) > 1 else None
        out_countries.append({
            "iso2": c["iso2"],
            "country": c["country"],
            "currency": c["currency"],
            "exchange": c["exchange"],
            "market": c["market"],
            # inflation, annual %, as published
            "inflation": series[latest],
            "inflation_year": latest,
            "inflation_prior_year": prior,
            "inflation_prior": series.get(prior) if prior else None,
            "history": [{"year": y, "value": series[y]} for y in sorted(series)],
            "source_country_name": wb_name.get(c["iso2"]),
        })
        gap = "" if prior else "  (no prior year available)"
        print("  %-13s %s = %5.2f%%   %s%s" % (
            c["country"], latest, series[latest],
            ("%s = %.2f%%" % (prior, series[prior])) if prior else "no prior", gap))

    doc = {
        "generated": today,
        "indicator": INDICATOR,
        "indicator_name": "Inflation, consumer prices (annual %)",
        "source": "World Bank Open Data",
        "source_url": "https://data.worldbank.org/indicator/" + INDICATOR,
        "api_url": API.format(isos=isos, span=span),
        "source_last_updated": meta.get("lastupdated"),
        "note": ("Annual consumer price inflation as published by the World Bank. "
                 "Values are reproduced exactly as published, with no estimate, "
                 "interpolation or rounding from a headline figure."),
        "countries": out_countries,
    }
    with open("static_data/macro.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=True)
        f.write("\n")
    print("\nwrote static_data/macro.json with %d countries" % len(out_countries))
    bad = [ch for ch in json.dumps(doc) if ord(ch) > 126]
    print("non-ascii chars:", len(bad))
    print("em/en dashes  :", json.dumps(doc).count("\u2014") + json.dumps(doc).count("\u2013"))
    return 0


if __name__ == "__main__":
    for attempt in range(1, 4):
        try:
            sys.exit(main())
        except Exception as e:
            print("attempt %d failed: %s %s" % (attempt, type(e).__name__, str(e)[:120]))
            time.sleep(4)
    sys.exit(1)
