#!/usr/bin/env python3
"""update_eod_prices.py - pull the live kwayisi boards (NSE + NGX) and merge
current prices/volumes/change into stocks.json. Fills the stocks that had no
price (new listings) and refreshes the rest. Run: python update_eod_prices.py
"""
import json, re, urllib.request, os, time

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"}
BASE = os.path.dirname(os.path.abspath(__file__))
STOCKS = os.path.join(BASE, "stocks.json")

def fetch_board(ex):
    url = f"https://afx.kwayisi.org/{ex}/"
    req = urllib.request.Request(url, headers=UA)
    t = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    txt = re.sub(r"<[^>]+>", "|", t)
    txt = re.sub(r"\|+", "|", txt)
    rows = re.findall(r"\|\s*([A-Z0-9-]+)\s*\|\s*\|?\s*([^|]{3,60})\s*\|\s*([\d,]*)\s*\|\s*([\d.]+)\s*\|\s*([+-]?[\d.]+)", txt)
    out = {}
    for tkr, name, vol, price, chg in rows:
        try:
            out[tkr] = {
                "price": float(price.replace(",", "")),
                "chgPct": float(chg) if chg else None,
                "volume": vol.strip(),
            }
        except ValueError:
            pass
    return out


def fetch_nse_nsenairobi():
    """Official NSE ticker snapshot (nsenairobi.nse.co.ke). The kwayisi mirror
    goes stale for some symbols (EQTY sat at 93.25 while the exchange printed
    107.75), so NSE prices come straight from the exchange's own feed."""
    url = "https://nsenairobi.nse.co.ke/nseticker/api/v1/ticker"
    body = json.dumps({"nopage": "true", "isinno": "KE3000009674"}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Origin": "https://nsenairobi.nse.co.ke",
        "Referer": "https://nsenairobi.nse.co.ke/"}, method="POST")
    d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    items = (d.get("message") or [{}])[0].get("snapshot") or []
    out = {}
    for it in items:
        iss = (it.get("issuer") or "").upper()
        px = it.get("price")
        out[iss] = {
            "price": float(px) if isinstance(px, (int, float)) else None,
            "chgPct": float(it["change"]) if isinstance(it.get("change"), (int, float)) else None,
            "volume": it.get("volume"),
        }
    return out


def main():
    db = json.load(open(STOCKS, encoding="utf-8"))
    print("fetching boards...")
    nse_board = fetch_nse_nsenairobi()
    ngx_board = fetch_board("ngx")
    print(f"NSE board: {len(nse_board)} | NGX board: {len(ngx_board)}")

    # NSE
    nse = db["stocks"]["NSE"]
    nse_filled = nse_updated = 0
    for s in nse:
        t = (s.get("ticker") or "").upper()
        b = nse_board.get(t)
        if not b:
            continue
        if s.get("price") is None:
            nse_filled += 1
        else:
            nse_updated += 1
        s["price"] = b["price"]
        s["chgPct"] = b["chgPct"]
        s["volume"] = b["volume"]
        s["date"] = "live board"
    print(f"NSE: filled {nse_filled} missing, updated {nse_updated}")

    # NGX (board may use different ticker style; match by name too)
    ngx = db["stocks"]["NGX"]
    ngx_filled = ngx_updated = 0
    for s in ngx:
        t = (s.get("ticker") or "").upper()
        b = ngx_board.get(t)
        if not b:
            continue
        if s.get("price") is None:
            ngx_filled += 1
        else:
            ngx_updated += 1
        s["price"] = b["price"]
        s["chgPct"] = b["chgPct"]
        s["volume"] = b["volume"]
        s["date"] = "live board"
    print(f"NGX: filled {ngx_filled} missing, updated {ngx_updated}")

    json.dump(db, open(STOCKS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # summary
    for ex in ("NSE", "NGX"):
        stocks = db["stocks"][ex]
        wp = sum(1 for s in stocks if s.get("price") is not None)
        print(f"{ex}: {len(stocks)} stocks, {wp} with price")

if __name__ == "__main__":
    main()
