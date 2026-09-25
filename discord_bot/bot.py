#!/usr/bin/env python3
"""MUTXRI TERMINAL Discord bot.

Reads the same static_data/ JSON the terminal serves and answers commands in
your server. $0 to run — just Python + discord.py + a free bot token.

Commands (prefix "!"):
  !help                this list
  !quote <ticker>      last price / change / volume for any NSE·NGX·JSE·EGX ticker
  !f <ticker>          key income figures (revenue, gross/operating profit, PBT, net, EPS)
  !gains [ex]          today's top gainers (ex = NSE|NGX|JSE|EGX, default: all)
  !losers [ex]         today's top losers
  !idx                 the four exchange indices
  !digest              full market overview (indices + top movers), on demand

Setup: see README.md. Token lives in a local .env file (never in chat).
"""
import os
import json
import re
import time
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = os.environ.get("MUTXRI_DATA", r"D:\mutxri-terminal\static_data")
TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()

EXCHANGES = ("NSE", "NGX", "JSE", "EGX")
PREFIX = "!"
CURRENCY_SYM = {"KES": "KSh", "NGN": "₦", "ZAR": "R", "ZAc": "R", "EGP": "£E",
                "USD": "$", "GBP": "£", "FRW": "FRw", "UGX": "USh", "TZS": "TSh"}

# income-statement label aliases (same map the panel uses, key rows only)
INCOME_ALIASES = {
    "revenue": ["revenue", "total revenue", "revenue total", "total operating income",
                "total income", "net interest income", "turnover", "sales", "net sales",
                "gross sales", "total interest income", "trading income", "trading revenue"],
    "grossProfit": ["gross profit", "gross profit total"],
    "operatingProfit": ["operating profit (ebit)", "operating profit", "operating loss",
                        "results from operating activities"],
    "profitBeforeTax": ["profit before tax", "profit before income tax", "loss before tax",
                        "profit before taxation"],
    "taxExpense": ["income tax", "income tax expense", "tax expense", "taxation", "tax"],
    "netProfit": ["net profit", "net income", "profit for the year", "profit after tax",
                  "profit attributable to owners of the company", "loss for the year",
                  "total comprehensive income", "total profit/loss", "profit/loss"],
    "eps": ["eps", "earnings per share", "basic earnings per share", "basic eps"],
}

# ratio / balance labels (same map the panel uses)
RATIO_ALIASES = {
    "roe": ["roe (%)", "roe"],
    "roa": ["roa (%)", "roa"],
    "netMargin": ["net margin (%)", "net margin"],
    "debtEquity": ["debt to equity"],
    "totalEquity": ["total equity", "total shareholders' equity",
                    "total shareholders equity", "shareholders' equity", "capital and reserves"],
    "totalLiabilities": ["total liabilities"],
}

# ---------------------------------------------------------------------------
# Data loading (cached, reloaded when a file's mtime changes)
# ---------------------------------------------------------------------------
_CACHE = {}          # path -> (mtime, parsed)


def _load(path):
    mtime = os.path.getmtime(path) if os.path.exists(path) else 0
    hit = _CACHE.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    if not os.path.exists(path):
        _CACHE[path] = (mtime, None)
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _CACHE[path] = (mtime, data)
    return data


def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).upper()


def listings():
    """All stocks across the four exchanges, with a canonical ticker + aliases."""
    out = []
    for ex in EXCHANGES:
        d = _load(os.path.join(DATA_DIR, f"listing_{ex}.json"))
        if not d:
            continue
        for s in d.get("stocks", []):
            if not isinstance(s, dict):
                continue
            ticker = s.get("ticker") or s.get("sym") or s.get("code") or ""
            sym = s.get("sym") or ticker
            code = s.get("code") or ""
            short = s.get("short") or ""
            out.append({
                "ex": ex,
                "ticker": ticker,          # canonical display ticker
                "name": s.get("name") or ticker,
                "sector": s.get("sector") or "",
                "currency": s.get("currency") or "",
                "instrument": s.get("instrument") or "",
                "price": s.get("price"),
                "chgPct": s.get("chgPct"),
                "volume": s.get("volume"),
                "ytd": s.get("ytd"),
                "aliases": {_norm(a) for a in (ticker, sym, code, short, sym.replace(".JO", "").replace(".CA", "")) if a},
                # financials files are keyed by sym (NSE/JSE/EGX) or ticker (NGX)
                "file_key": sym if (ex in ("NSE", "JSE", "EGX")) else ticker,
            })
    return out


def indices():
    d = _load(os.path.join(DATA_DIR, "indices.json"))
    return (d or {}).get("entries", [])


def _find_stock(query):
    q = _norm(query)
    stocks = listings()
    # Pass 1: exact ticker/alias match wins (so EGX "INFI" beats NGX "INFINITY" by name)
    for s in stocks:
        if q == _norm(s["ticker"]) or q in s["aliases"]:
            return s
    # Pass 2: name substring fallback
    for s in stocks:
        if q and q in _norm(s["name"]):
            return s
    return None


def _financials_file(stock, statement):
    key = _norm(stock["file_key"]).replace("/", "_")
    return os.path.join(DATA_DIR, "financials", f"{key}__{statement}.json")


def _row_value(row, idx):
    vals = row.get("values") or []
    if idx < len(vals) and vals[idx] is not None:
        try:
            return float(vals[idx])
        except (TypeError, ValueError):
            return None
    return None


def _latest_val(rows, aliases):
    """First non-null value across the rows matching any alias (most recent first)."""
    norm_als = {_norm(a) for a in aliases}
    for r in (rows or []):
        if _norm(r.get("label")) in norm_als:
            for v in (r.get("values") or []):
                if isinstance(v, (int, float)) and not (isinstance(v, float) and v != v):
                    return float(v)
            break
    return None


def _hist_series(stock):
    """date -> close for a stock, preferring the full-history (.max) file."""
    ex = stock["ex"]
    if ex == "NSE":
        paths = [os.path.join(DATA_DIR, "history", f"NSE_{stock['ticker']}.json")]
    elif ex == "NGX":
        paths = [os.path.join(DATA_DIR, "history", f"NGX_{stock['ticker']}.json")]
    else:
        key = _norm(stock["file_key"])
        paths = [os.path.join(DATA_DIR, "history", f"{key}.max.json"),
                 os.path.join(DATA_DIR, "history", f"{key}.json")]
    for p in paths:
        d = _load(p)
        if d and d.get("bars"):
            out = {}
            for b in d["bars"]:
                t = b.get("t")
                c = b.get("c")
                if t is not None and isinstance(c, (int, float)):
                    out[str(t)[:10]] = float(c)
            if out:
                return out
    return None


def _compare_metrics(stock):
    m = {"ticker": stock["ticker"], "ex": stock["ex"], "cur": stock["currency"],
         "price": stock.get("price"), "chgPct": stock.get("chgPct"), "ytd": stock.get("ytd")}
    inc = _load(_financials_file(stock, "income"))
    bal = _load(_financials_file(stock, "balance"))
    if inc and inc.get("rows"):
        m["roe"] = _latest_val(inc["rows"], RATIO_ALIASES["roe"])
        m["roa"] = _latest_val(inc["rows"], RATIO_ALIASES["roa"])
        m["netMargin"] = _latest_val(inc["rows"], RATIO_ALIASES["netMargin"])
        m["eps"] = _latest_val(inc["rows"], INCOME_ALIASES["eps"])
        m["netProfit"] = _latest_val(inc["rows"], INCOME_ALIASES["netProfit"])
    if bal and bal.get("rows"):
        te = _latest_val(bal["rows"], RATIO_ALIASES["totalEquity"])
        tl = _latest_val(bal["rows"], RATIO_ALIASES["totalLiabilities"])
        de = _latest_val(bal["rows"], RATIO_ALIASES["debtEquity"])
        if de is None and tl and te:
            de = tl / te
        m["debtEquity"] = de
    if m.get("price") and m.get("eps") and m["eps"] > 0:
        m["pe"] = m["price"] / m["eps"]
    return m


def financials_summary(stock, periods=3):
    """Latest `periods` periods of key income rows for a stock."""
    d = _load(_financials_file(stock, "income"))
    if not d or not d.get("rows"):
        return None
    labels = d.get("periods") or []
    n = len(labels)
    # map alias -> list of values
    found = {}
    for key, als in INCOME_ALIASES.items():
        for r in d["rows"]:
            if _norm(r.get("label")) in {_norm(a) for a in als}:
                vals = r.get("values") or []
                found[key] = vals
                break
    if "revenue" not in found and "netProfit" not in found:
        return None
    out = {"periods": labels[-periods:], "currency": d.get("currency") or stock["currency"], "rows": {}}
    for key, vals in found.items():
        out["rows"][key] = vals[-periods:]
    return out


def fmt_num(v, cur=""):
    if v is None:
        return "—"
    v = float(v)
    neg = v < 0
    av = abs(v)
    if av >= 1e9:
        s = f"{av/1e9:.2f}B"
    elif av >= 1e6:
        s = f"{av/1e6:.2f}M"
    elif av >= 1e3:
        s = f"{av/1e3:.1f}K"
    else:
        s = f"{av:,.2f}"
    sym = CURRENCY_SYM.get(cur, cur or "")
    return ("-" if neg else "") + sym + s


def fmt_pct(v):
    if v is None:
        return "—"
    return f"{float(v):+.2f}%"


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)


def _embed(title, color=0x33E29A):
    return discord.Embed(title=title, color=color)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")


@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    content = msg.content.strip()
    if not content.startswith(PREFIX):
        return
    parts = content[1:].split()
    cmd = parts[0].lower()
    arg = " ".join(parts[1:]).strip() if len(parts) > 1 else ""

    try:
        if cmd in ("help", "m", "?"):
            await msg.channel.send(embed=_embed("MUTXRI TERMINAL commands").add_field(
                name="Commands",
                value=("`!quote SCOM` — last price / change / volume\n"
                       "`!f EABL` — income figures\n"
                       "`!gains [NSE|NGX|JSE|EGX]` — top gainers\n"
                       "`!losers [NSE|NGX|JSE|EGX]` — top losers\n"
                       "`!compare EQTY KCB` — side-by-side metrics + price return\n"
                       "`!idx` — indices\n"
                       "`!digest` — full market overview"),
                inline=False))
        elif cmd in ("q", "quote", "p", "price"):
            await _quote(msg, arg)
        elif cmd in ("f", "fin", "financials", "fs"):
            await _financials(msg, arg)
        elif cmd in ("gains", "gainers", "up"):
            await _movers(msg, arg, top=True)
        elif cmd in ("losers", "down"):
            await _movers(msg, arg, top=False)
        elif cmd in ("idx", "indices", "index"):
            await _indices(msg)
        elif cmd in ("digest", "overview"):
            await _digest(msg)
        elif cmd in ("compare", "cmp", "cmpare", "vs"):
            await _compare(msg, arg)
        else:
            await msg.channel.send(f"Unknown command `{PREFIX}{cmd}`. Try `{PREFIX}help`.")
    except Exception as e:
        await msg.channel.send(f"Error: {type(e).__name__}: {str(e)[:200]}")


async def _quote(msg, arg):
    s = _find_stock(arg)
    if not s:
        await msg.channel.send(f"No match for `{arg}`. Try a ticker like `SCOM`, `ZENITHBANK`, `4SI.JO`, `INFI`.")
        return
    em = _embed(f"{s['ticker']} — {s['name']}").add_field(
        name="Quote",
        value=(f"**Price:** {fmt_num(s['price'], s['currency'])}\n"
               f"**Change:** {fmt_pct(s['chgPct'])}\n"
               f"**Volume:** {s['volume']:,.0f}" if isinstance(s['volume'], (int, float)) else f"**Volume:** {s['volume']}\n"
               f"**Exchange:** {s['ex']}  •  **Sector:** {s['sector'] or '—'}"),
        inline=False)
    if s.get("ytd") is not None:
        em.add_field(name="YTD", value=fmt_pct(s["ytd"]), inline=True)
    await msg.channel.send(embed=em)


async def _financials(msg, arg):
    s = _find_stock(arg)
    if not s:
        await msg.channel.send(f"No match for `{arg}`.")
        return
    fs = financials_summary(s)
    if not fs:
        await msg.channel.send(f"No filed income statement for **{s['ticker']}** yet.")
        return
    cur = fs["currency"]
    labels = fs["periods"]
    name_map = {
        "revenue": "Revenue", "grossProfit": "Gross profit", "operatingProfit": "Operating profit",
        "profitBeforeTax": "Profit before tax", "taxExpense": "Income tax", "netProfit": "Net profit",
        "eps": "EPS",
    }
    lines = []
    for key, disp in name_map.items():
        vals = fs["rows"].get(key)
        if not vals or all(v is None for v in vals):
            continue
        col = "  ".join(fmt_num(v, cur if key != "eps" else "") for v in vals)
        lines.append(f"**{disp}:** {col}")
    if not lines:
        await msg.channel.send(f"No income figures for **{s['ticker']}**.")
        return
    header = "  ".join(f"`{p}`" for p in labels)
    em = _embed(f"{s['ticker']} — income statement").add_field(
        name="Periods", value=header, inline=False).add_field(
        name="Figures", value="\n".join(lines), inline=False)
    await msg.channel.send(embed=em)


async def _compare(msg, arg):
    toks = [p for p in re.split(r"[\s,]+", arg.strip()) if p and _norm(p) not in ("VS", "AND", "&")]
    if len(toks) < 2:
        await msg.channel.send("`!compare EQTY KCB` — give two tickers (or `EQTY vs KCB`).")
        return
    a = _find_stock(toks[0])
    b = _find_stock(toks[1])
    if not a or not b:
        miss = toks[0] if not a else toks[1]
        await msg.channel.send(f"No match for `{miss}`.")
        return
    ma, mb = _compare_metrics(a), _compare_metrics(b)

    def cell(m):
        lines = [f"Price {fmt_num(m['price'], m['cur'])}",
                 f"Day {fmt_pct(m['chgPct'])}",
                 f"YTD {fmt_pct(m['ytd'])}"]
        if m.get("eps") is not None:
            lines.append(f"EPS {m['eps']:.2f}")
        if m.get("pe") is not None:
            lines.append(f"P/E {m['pe']:.1f}x")
        if m.get("roe") is not None:
            lines.append(f"ROE {m['roe']:.2f}%")
        if m.get("roa") is not None:
            lines.append(f"ROA {m['roa']:.2f}%")
        if m.get("netMargin") is not None:
            lines.append(f"Net margin {m['netMargin']:.2f}%")
        if m.get("debtEquity") is not None:
            lines.append(f"D/E {m['debtEquity']:.2f}x")
        if m.get("netProfit") is not None:
            lines.append(f"Net profit {fmt_num(m['netProfit'], m['cur'])}")
        return "\n".join(lines)

    sec = a["sector"] if (a["sector"] and a["sector"] == b["sector"]) else ""
    em = _embed(f"{a['ticker']} vs {b['ticker']}" + (f" — {sec}" if sec else ""))
    em.add_field(name=f"{a['ticker']} ({a['ex']})", value=cell(ma), inline=True)
    em.add_field(name=f"{b['ticker']} ({b['ex']})", value=cell(mb), inline=True)
    ha, hb = _hist_series(a), _hist_series(b)
    if ha and hb:
        common = sorted(set(ha) & set(hb))
        if len(common) >= 2:
            ra = (ha[common[-1]] / ha[common[0]] - 1) * 100
            rb = (hb[common[-1]] / hb[common[0]] - 1) * 100
            win = a["ticker"] if ra > rb else (b["ticker"] if rb > ra else None)
            lead = f"**{win}** led." if win else "Dead heat."
            em.add_field(name="Price return", value=(
                f"{a['ticker']} {ra:+.1f}% · {b['ticker']} {rb:+.1f}%\n"
                f"{common[0]} to {common[-1]}\n{lead}"), inline=False)
    await msg.channel.send(embed=em)


def _filter_stocks(arg):
    stocks = listings()
    if arg:
        a = _norm(arg)
        stocks = [s for s in stocks if s["ex"] == a]
        if not stocks:
            # allow a full name like "nairobi"
            stocks = [s for s in listings() if _norm(s["ex"]) == a or a in _norm(s["ex"])]
    return stocks


async def _movers(msg, arg, top=True):
    stocks = _filter_stocks(arg)
    scoped = [s for s in stocks if isinstance(s.get("chgPct"), (int, float)) and s.get("price")]
    scoped.sort(key=lambda s: s["chgPct"], reverse=top)
    scoped = scoped[:8]
    if not scoped:
        await msg.channel.send("No movers found for that scope.")
        return
    lines = []
    for s in scoped:
        lines.append(f"`{s['ticker']}` {fmt_pct(s['chgPct'])} — {fmt_num(s['price'], s['currency'])}  ({s['ex']})")
    em = _embed("Top gainers" if top else "Top losers", color=0x33E29A if top else 0xD02F2A).add_field(
        name="By % change today", value="\n".join(lines), inline=False)
    await msg.channel.send(embed=em)


async def _indices(msg):
    entries = indices()
    if not entries:
        await msg.channel.send("Indices not available right now.")
        return
    lines = []
    for e in entries:
        lines.append(f"**{e.get('label')}** ({e.get('market')}): {fmt_num(e.get('price'), e.get('currency'))} "
                     f"({fmt_pct(e.get('changePct'))})")
    em = _embed("Exchange indices").add_field(name="Live", value="\n".join(lines), inline=False)
    if entries and entries[0].get("asOf"):
        pass
    await msg.channel.send(embed=em)


async def _digest(msg):
    await _indices(msg)
    for ex in EXCHANGES:
        stocks = [s for s in listings() if s["ex"] == ex and isinstance(s.get("chgPct"), (int, float))]
        if not stocks:
            continue
        stocks.sort(key=lambda s: s["chgPct"], reverse=True)
        g = stocks[0]
        l = stocks[-1]
        em = _embed(f"{ex}").add_field(
            name="Movers",
            value=(f"▲ `{g['ticker']}` {fmt_pct(g['chgPct'])}\n"
                   f"▼ `{l['ticker']}` {fmt_pct(l['chgPct'])}"),
            inline=False)
        await msg.channel.send(embed=em)


def main():
    if not TOKEN:
        print("DISCORD_TOKEN not set. Put it in discord_bot/.env (see README).")
        return
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
