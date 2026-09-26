#!/usr/bin/env python3
"""tv_fill_missing.py - fill candle series that are EMPTY (or stale) from TradingView.

The free Yahoo / StockAnalysis routes 404 on part of the EGX and JSE tail, but
TradingView lists those issuers under a DIFFERENT trading code than the one the
terminal file is named for (the terminal keys EGX history by its own listing sym,
e.g. `ALEXA.CA`, while TradingView carries the issuer as `EGX:ALEX`). So the code
cannot simply be reused as the TradingView symbol - it has to be RESOLVED.

Resolution goes through TradingView's own symbol search, and the hit must be:
  * on the RIGHT exchange (EGX for a `.CA` file, JSE for `.JO`), and
  * the SAME issuer - a significant word of the listed company name must appear
    in the exchange's own description for that symbol.

A hit that fails either test is rejected and reported, never written: EGX and JSE
recycle tickers, and a plausible-looking code that belongs to a renamed issuer
puts another company's prices on the chart.

Writes `<sym>.json` (daily) + `<sym>.max.json` (monthly) - the exact names the
chart panel requests - and never shrinks an existing series.

Usage: python3 tv_fill_missing.py [--apply] [--stale] [--limit N]
"""
import difflib, importlib.util, json, os, sys, time, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
APPLY = "--apply" in sys.argv
INCLUDE_STALE = "--stale" in sys.argv
LIMIT = 0
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

_spec = importlib.util.spec_from_file_location("tv", os.path.join(BASE, "tv_backfill.py"))
tv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tv)

EXOF = {".CA": ("EGX", "EGX"), ".JO": ("JSE", "JSE")}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
STOP = {"egypt", "egyptian", "co", "company", "for", "the", "and", "of", "limited",
        "ltd", "holding", "holdings", "group", "industries", "industry", "sae",
        "investment", "investments", "development", "real", "estate", "national",
        "international", "south", "africa", "african", "corporation", "inc"}


def search(q):
    u = ("https://symbol-search.tradingview.com/symbol_search/?text=%s&type=stock"
         % urllib.parse.quote(q))
    req = urllib.request.Request(u, headers={
        "User-Agent": UA, "Referer": "https://www.tradingview.com/",
        "Origin": "https://www.tradingview.com"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode())
        return d if isinstance(d, list) else (d.get("symbols") or [])
    except Exception:
        return []


def words(s):
    out = []
    for w in "".join(ch if ch.isalnum() or ch == " " else " " for ch in (s or "").lower()).split():
        if len(w) > 3 and w not in STOP:
            out.append(w)
    return out


def norm(s):
    return " ".join(words(s))


# Words that do NOT identify an issuer: a shared city or nation, and a shared
# sector. "Cairo For Investment" vs "Cairo Poultry" share only a city;
# "Riva Pharma" vs "Ibnsina Pharma" share only an industry; "Union Foods" vs
# "Edita Food Industries" share only a sector. None of those are the same issuer.
GENERIC = {"egypt", "egyptian", "egyptians", "arab", "arabian", "gulf", "islamic",
           "islam", "national", "first", "general", "united", "modern", "middle",
           "east", "north", "upper", "lower", "delta", "misr", "masr",
           "cairo", "alexandria", "giza", "suez", "assiut", "ismailia", "tanta",
           "damietta", "port", "said", "city", "new", "west", "south", "qatar",
           "kuwait", "saudi", "emirates"}
SECTOR = {"pharma", "pharmaceutical", "pharmaceuticals", "food", "foods", "cement",
          "bank", "banking", "textile", "textiles", "steel", "chemical",
          "chemicals", "petroleum", "oil", "gas", "mining", "telecom",
          "telecommunications", "insurance", "engineering", "construction",
          "agriculture", "agricultural", "tourism", "hotel", "hotels", "paper",
          "packaging", "plastics", "glass", "cables", "electrical", "motors",
          "automotive", "shipping", "logistics", "computer", "computers",
          "software", "education", "healthcare", "medical", "entertainment",
          "media", "retail", "clothing", "furniture", "printing", "services",
          "industry", "industries", "products", "resources", "energy",
          "technology", "systems", "housing", "trading", "contracting",
          "aluminum", "aluminium", "materials", "universal", "printing",
          "metal", "metals", "leather", "cotton", "sugar", "dairy", "flour"}

# A near-identical name is accepted on its own; a looser one needs a shared word
# that is neither a place nor a sector.
EXACT_RATIO = 0.85
LOOSE_RATIO = 0.55


def resolve(listed_name, ex):
    """Return (tv_full_symbol, description, ratio) for the SAME issuer.

    Matching on a shared word is NOT enough on these exchanges: AITG ("Assiut
    Islamic National Trading") and "Gharbia Islamic Housing Development" share
    the token "islamic" and are different companies, as do ABRD ("Egyptians
    Abroad") and "Egyptians Housing Development". So a near-identical full name
    is accepted directly, while a looser match must share a word that is neither
    a place nor a sector.
    """
    n = norm(listed_name)
    if not n:
        return None, "no usable name tokens", 0.0
    best = (0.0, None, "")
    for hit in search(listed_name):
        if (hit.get("exchange") or "").upper() != ex:
            continue
        sym = hit.get("symbol") or ""
        desc = hit.get("description") or ""
        if not sym:
            continue
        dn = norm(desc)
        r = difflib.SequenceMatcher(None, n, dn).ratio()
        if r < LOOSE_RATIO:
            continue
        if r < EXACT_RATIO:
            shared = [w for w in n.split() if w in dn.split()]
            distinctive = [w for w in shared if w not in GENERIC and w not in SECTOR]
            if not distinctive:
                continue
        if r > best[0]:
            best = (r, "%s:%s" % (ex, sym), desc)
    if best[1]:
        return best[1], best[2], best[0]
    return None, "no name-matching %s hit" % ex, 0.0


def monthly(bars):
    return tv.aggregate_monthly(bars)


def main():
    listing = {}
    for ex in ("EGX", "JSE"):
        d = json.load(open(os.path.join(BASE, "static_data", "listing_%s.json" % ex),
                           encoding="utf-8"))
        for r in (d.get("stocks") or []):
            if r.get("sym"):
                listing[r["sym"]] = r

    targets = []
    for f in sorted(os.listdir(HIST)):
        if not f.endswith(".json") or f.endswith(".max.json") or "__" in f:
            continue
        base = f[:-5]
        if base not in listing:
            continue
        head = os.path.splitext(base)[1]
        if head not in EXOF:
            continue
        try:
            bars = (json.load(open(os.path.join(HIST, f), encoding="utf-8")).get("bars") or [])
        except Exception:
            continue
        if bars and not INCLUDE_STALE:
            continue
        targets.append((base, listing[base]))
    if LIMIT:
        targets = targets[:LIMIT]

    print("files to resolve: %d  (mode: %s)" % (
        len(targets), "empty + stale" if INCLUDE_STALE else "empty only"))
    ok = rej = fail = 0
    for base, row in targets:
        ex = EXOF[os.path.splitext(base)[1]][0]
        name = row.get("name") or ""
        full, desc, ratio = resolve(name, ex)
        if not full:
            rej += 1
            print("  REJECT %-18s %s" % (base, desc))
            time.sleep(0.8)
            continue
        try:
            raw, err = tv.fetch_tv(full, timeout=30)
        except Exception as e:
            fail += 1
            print("  FAIL   %-18s %s -> %s" % (base, full, str(e)[:40]))
            time.sleep(0.8)
            continue
        time.sleep(0.8)
        if err or not raw:
            fail += 1
            print("  NODATA %-18s %s (%s)" % (base, full, (err or "empty")[:40]))
            continue
        seen, iso = set(), []
        for b in raw:
            d = tv.to_iso(b["t"])
            if d in seen:
                continue
            seen.add(d)
            cb = tv.clean_bar(d, b["o"], b["h"], b["l"], b["c"], b["v"])
            if cb:
                iso.append(cb)
        iso.sort(key=lambda x: x["t"])
        if len(iso) < 2:
            fail += 1
            print("  THIN   %-18s %s only %d bars" % (base, full, len(iso)))
            continue
        try:
            prev = json.load(open(os.path.join(HIST, base + ".json"),
                                  encoding="utf-8")).get("bars") or []
        except Exception:
            prev = []
        if INCLUDE_STALE and len(prev) > len(iso):
            rej += 1
            print("  KEEP   %-18s existing %d > tv %d" % (base, len(prev), len(iso)))
            continue
        # Second, INDEPENDENT check when the security still trades: the freshest
        # TradingView close must agree with the price the terminal already shows.
        # This catches a same-name-but-different-listing match that the text
        # similarity alone would have let through.
        price = row.get("price")
        if price not in (None, "", 0):
            last = iso[-1]["c"]
            try:
                if not last or abs(float(last) - float(price)) / float(price) > 0.10:
                    rej += 1
                    print("  REJECT %-18s %s terminal price %s vs tv last %s"
                          % (base, full, price, last))
                    continue
            except (TypeError, ValueError):
                pass
        print("  OK     %-18s %-16s %4d bars  %s -> %s  ratio=%.2f  [%s]" % (
            base, full, len(iso), iso[0]["t"], iso[-1]["t"], ratio, desc[:30]))
        ok += 1
        if APPLY:
            json.dump({"sym": base, "bars": iso},
                      open(os.path.join(HIST, base + ".json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
            json.dump({"sym": base, "bars": monthly(iso)},
                      open(os.path.join(HIST, base + ".max.json"), "w", encoding="utf-8"),
                      ensure_ascii=False)

    print()
    print("filled: %d   rejected: %d   failed: %d" % (ok, rej, fail))
    print("DRY RUN - nothing written" if not APPLY else "APPLIED")


if __name__ == "__main__":
    main()
