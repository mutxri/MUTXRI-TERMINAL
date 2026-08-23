# MUTXRI CAPITAL — African Markets Research Terminal

A Godel-Terminal-style financial research terminal for African markets: **NSE Nairobi (Kenya), NGX Lagos (Nigeria), JSE Johannesburg (South Africa), EGX Cairo (Egypt)**.

Browser-based, Bloomberg-style command UX, black + mint-green (Godel) theme, 768 listed stocks, live data where free data allows, and zero licensing cost.

> **Name note:** the product name is TBD (pending owner decision). Repo/brand placeholders say "AFRI".

---

## Features

| Area | What it does |
|---|---|
| **Markets** | 768 stocks across JSE (319, live), EGX (259, live, 207 real tickers), NGX (132, EOD), NSE (58, EOD) |
| **Charts** | TradingView lightweight-charts — **AREA / LINE / CANDLE** toggle, ranges 1M–5Y, volume |
| **Heatmap** | TradingView-style sector map: cell size = volume, color = % change, **company logos** (Google favicon) + accurate tickers, click-to-load |
| **FUND panel** | Company profile, financial highlights, **financial statements** (latest filing), **dividends** (full history), **filings** (all documents, clickable PDFs), **major shareholders** (ownership), per-share metrics |
| **RATES tab** | Central bank policy rates (SARB, CBE, CBN, CBK, Fed) + live US Treasury yields |
| **FX tab** | 6 live currency pairs (USD/ZAR, USD/EGP, USD/KES, USD/NGN, EUR/ZAR, GBP/ZAR) |
| **News** | Aggregated from 25+ sources incl. **S&P Global**, MarketWatch, Investing.com, Moneyweb, Business Daily Africa, Enterprise Egypt, TechCabal, African Financials (Google News RSS aggregation + direct RSS) |
| **Indices** | JSE Top 40, EGX30 (live), NSE20, NASI, NGX ASI (strip) |
| **Commands** | Backtick palette: `TICKER DES`, `TICKER HP/C`, `FUND/DIV/CF/FA`, `WEI`, `FX`, `NEWS`, `HELP`, `QM` |
| **Morning brief** | `morning_brief.py` emails the dashboard as an HTML brief (indices, FX, rates, headlines) — scheduled daily 6am |
| **Resilience** | Live data always shows last close when markets are closed; cache + warm-thread handles Yahoo rate limits |

## Stack

- **Backend**: Python 3 stdlib ONLY (`http.server`, `urllib`, `json`, `threading`) — zero pip dependencies for the server
- **Frontend**: single-file `terminal.html` — vanilla JS, TradingView lightweight-charts CDN, Google Fonts (Oxygen Mono / Inter / Sofia Sans)
- **Data**: Yahoo chart API (JSE `.JO` + EGX `.CA` live), TradingView screener (tickers+sectors), African Financials (EOD + fundamentals), Google News RSS (news aggregation), Google favicon (logos), Twelve Data lists

## Run it

```bash
cd /path/to/project
python afri_server.py
# open http://127.0.0.1:8081/terminal.html
```

First load warms the cache (JSE+EGX quotes, ~3 min under datacenter throttling); the page is usable immediately with progressive fill.

### Rebuild data

```bash
python build_stocks.py            # rebuild stocks.json (listings/tickers)
python build_fundamentals.py      # rescrape AF company pages (dividends/filings/profiles)
python fill_financial_summary.py  # financial statements from latest filing meta
```

### Morning brief

```bash
python morning_brief.py --to you@email.com
```

## Data files

| File | Contents |
|---|---|
| `stocks.json` | 768 stocks: sym, code (ISIN for EGX), name, short/ticker, currency |
| `fundamentals.json` | AF company data: profile, dividends, documents, highlights, financial_summary (190 companies) |
| `ownership.json` | Major shareholders for liquid names (sourced from public disclosures) |
| `company_domains.json` | 172 company → domain mappings for heatmap logos |
| `egx_verified_tickers.json` | 217 EGX tickers verified against Yahoo |

## API endpoints

`/api/health` · `/api/listing?exchange=` · `/api/quotes?symbols=` · `/api/chart?symbol=&range=&interval=` · `/api/heatmap?exchange=` · `/api/fundamentals?symbol=&exchange=&name=` · `/api/rates` · `/api/news` · `/api/eod?exchange=&name=`

## Honest limits

- **JSE/EGX income statements**: no free structured source (Yahoo fundamentals 401, others keyed/blocked) — FUND shows dividends + quote data for those; full statements need licensed feeds (Bloomberg/Refinitiv/IRESS)
- **NGX/NSE live quotes**: Yahoo removed `.NG`/`.NR` — EOD from African Financials
- **EGX**: 52/259 names still use ISIN codes (no short ticker in any free source); they still fetch
- **Ownership**: curated for ~26 liquid names (free feeds don't publish all); file is extensible
- **Sector classification** for JSE/EGX is keyword-based (~15% "Other")

## Credits / data sources

Yahoo Finance (quotes, dividends) · TradingView screener (tickers, sectors) · African Financials (fundamentals, filings, dividends) · Google News RSS (news aggregation incl. S&P Global, MarketWatch, Reuters, Bloomberg) · Google favicons (logos) · Twelve Data (exchange lists) · Central banks (policy rates). Research only — not investment advice.
