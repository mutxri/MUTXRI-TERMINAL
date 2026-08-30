#!/usr/bin/env python3
"""fetch_ngx_history.py - build REAL NGX OHLC history from the NGX's
official daily price lists (doclib.ngxgroup.com/DownloadsContent).

The NGX publishes 'GAINERS AND PRICE LIST FOR <DATE>.zip' for every
trading day since 2014. Each zip contains PRICES1.pdf + PRICES_LIST2.pdf
with the full daily price list (PCLOSE/OPEN/HIGH/LOW/CLOSE/CHANGE/
%CHANGE/VOLUME/VALUE per security).

This fetches the most recent N days, parses the PDFs, and writes
per-symbol history files: static_data/history/NGX_<SYM>.json
  {bars: [{t: "YYYY-MM-DD", o, h, l, c, v}, ...]}
"""
import urllib.request, zipfile, io, json, os, re, sys, time
import pdfplumber

BASE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE, "static_data", "history")
os.makedirs(HIST, exist_ok=True)

API = "https://doclib.ngxgroup.com/_api/Web/Lists(guid'dd86e37a-4967-478e-a670-e70e6986138f')/Items"
UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json;odata=verbose'}

def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read().decode(errors="replace"))

def find_price_list(date_str):
    """find the GAINERS AND PRICE LIST item for a date (DD-MM-YYYY)"""
    filt = f"substringof('GAINERS%20AND%20PRICE%20LIST%20FOR%20{date_str}',Title)"
    d = get_json(f"{API}?$select=Title,FileLeafRef&$format=json&$filter={filt}")
    for item in d.get("d", {}).get("results", []):
        leaf = item.get("FileLeafRef") or ""
        if leaf.endswith(".zip") and date_str in leaf:
            return leaf
    return None

def download_zip(leaf):
    url = "https://doclib.ngxgroup.com/DownloadsContent/" + leaf.replace(" ", "%20")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=60).read()
    return zipfile.ZipFile(io.BytesIO(data))

def parse_prices(zf, prefix):
    """parse all PRICES pdfs in the zip, return {symbol: {o,h,l,c,v}}
    Handles three row formats:
      PRICES1: S/N SYM PCLOSE OOPEN OPEN HIGH LOW %SPREAD OCLOSE CLOSE CHANGE %CHANGE TRADES VOLUME VALUE
      PRICES_LIST2 premium: S/N NAME MKTCP PRICE %CHG TRADES VOLUME (no OHLC -> flat candle)
      PRICES_LIST2 oddlot:  S/N NAME MKTCP PRICE %CHG TRADES VOLUME
    """
    rows = {}
    # PRICES1 carries real OHLC; PRICES_LIST2 carries only MARKET CAP + PRICE and
    # derives its symbol from a company name. Parse PRICES1 first and never let a
    # LIST2 row overwrite it - that collision is how market caps became closes.
    # PRICES1 only. PRICES_LIST2 lists companies by full name, and its rows can
    # begin with an all-caps word ("STANBIC IBTC HOLDINGS PLC") that looks exactly
    # like a ticker, so letting it through here reads its columns as PRICES1
    # columns and stores nonsense (STANBIC 156.10 -> 30.00).
    for name in [n for n in zf.namelist()
                 if n.lower().endswith(".pdf") and "PRICES1" in n.upper()]:
        if False:
            continue
        data = zf.read(name)
        try:
            with pdfplumber.open(io.BytesIO(data)) as doc:
                for page in doc.pages:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        if not re.match(r"^\d+ ", line):
                            continue
                        parts = line.split()
                        try:
                            def _f(tok):
                                try:
                                    return float(tok.replace(",", ""))
                                except (ValueError, AttributeError):
                                    return None

                            # PRICES1 rows start with a ticker. Read them from the
                            # RIGHT - "... OCLOSE CLOSE CHANGE %CHANGE TRADES VOLUME
                            # VALUE" - because wide numbers sometimes render glued
                            # together in the middle of the row (SEPLAT prints as
                            # "11,200.6012,320.6012,320.60"), which shifts every
                            # left-hand index and used to drop the row into the
                            # LIST2 branch, where it parsed %CHANGE as the price.
                            if len(parts) >= 10 and re.match(r"^[A-Z][A-Z0-9&]{2,}$", parts[1]):
                                sym = parts[1]
                                pclose = _f(parts[2])
                                close = _f(parts[-6])
                                if close is None:
                                    close = pclose
                                if close is None:
                                    continue
                                o = _f(parts[4]) if len(parts) >= 15 else None
                                high = _f(parts[5]) if len(parts) >= 15 else None
                                low = _f(parts[6]) if len(parts) >= 15 else None
                                o = o if o is not None else (pclose if pclose is not None else close)
                                high = high if high is not None else close
                                low = low if low is not None else close
                                # a glued or misread middle column shows up as an
                                # impossible bar - fall back to a flat one
                                if not (low <= close <= high and low <= o <= high):
                                    o = high = low = close
                                vol = parts[-2].replace(",", "")
                                volume = int(vol) if vol.isdigit() else 0
                                rows[sym] = {"o": o, "h": high, "l": low, "c": close, "v": volume}
                            # PRICES_LIST2 is deliberately NOT used for history.
                            # It lists companies by full name with only MARKET CAP
                            # and PRICE, so its symbols have to be guessed from the
                            # name ("UNITED BANK FOR AFRICA PLC" -> UNITED) - which
                            # both invents tickers that do not exist and collides
                            # with real ones, overwriting good PRICES1 bars. PRICES1
                            # already carries the full equities board with real
                            # tickers and real OHLC, so that is the only source here.
                        except (ValueError, IndexError):
                            continue
        except Exception:
            continue
    return rows

def sessions_on_disk():
    """ISO dates already parsed into the per-symbol archives. A real session
    shows up for hundreds of securities; a handful of stragglers means the day
    was only partially parsed and is worth fetching again."""
    import glob, collections
    seen = collections.Counter()
    for path in glob.glob(os.path.join(HIST, "NGX_*.json")):
        try:
            for b in json.load(open(path, encoding="utf-8")).get("bars", []):
                if b.get("t"):
                    seen[b["t"]] += 1
        except Exception:
            continue
    return {d for d, n in seen.items() if n >= 100}


def main():
    # fetch the last N trading days (default 30 = ~6 weeks)
    n_days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    import datetime
    dates = []
    cur = datetime.date.today()
    while len(dates) < n_days:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%d-%m-%Y"))
        cur -= datetime.timedelta(days=1)

    # re-runs must be cheap: skip any session already sitting in the archives
    # so a backfill that died partway through resumes instead of restarting
    done = set() if "--force" in sys.argv else sessions_on_disk()
    todo = [d for d in dates
            if f"{d[6:]}-{d[3:5]}-{d[0:2]}" not in done]
    print(f"{len(dates)} sessions requested, {len(dates) - len(todo)} already on disk, "
          f"{len(todo)} to fetch", flush=True)
    dates = todo

    all_bars = {}  # sym -> {date: bar}
    fetched = 0
    for i, date_str in enumerate(dates):
        try:
            leaf = find_price_list(date_str)
            if not leaf:
                print(f"  {date_str}: no file")
                continue
            zf = download_zip(leaf)
            rows = parse_prices(zf, "PRICES")
            iso = f"{date_str[6:]}-{date_str[3:5]}-{date_str[0:2]}"
            for sym, bar in rows.items():
                all_bars.setdefault(sym, {})[iso] = bar
            fetched += 1
            print(f"  {date_str}: {len(rows)} securities")
        except Exception as e:
            print(f"  {date_str}: ERR {str(e)[:60]}")
        if fetched and fetched % 10 == 0:
            print(f"    ... checkpoint: {flush(all_bars)} symbols written", flush=True)
        time.sleep(0.4)

    saved = flush(all_bars)
    print("")
    print(f"DONE: {fetched} days fetched, {saved} symbols with >=2 bars saved")


def flush(all_bars):
    """merge the fetched window into whatever is already on disk. Called every
    few days as well as at the end: a long backfill that dies partway through
    must not throw away everything it had already parsed."""
    saved = 0
    for sym, bars_map in all_bars.items():
        path = os.path.join(HIST, f"NGX_{sym}.json")
        merged = {}
        if os.path.exists(path):
            try:
                for b in json.load(open(path, encoding="utf-8")).get("bars", []):
                    if b.get("t"):
                        merged[b["t"]] = b
            except Exception:
                pass
        for iso, b in bars_map.items():
            merged[iso] = {"t": iso, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
        bars = [merged[k] for k in sorted(merged.keys())]
        if len(bars) >= 2:
            json.dump({"bars": bars[-1500:]}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            saved += 1
    return saved

if __name__ == "__main__":
    main()
