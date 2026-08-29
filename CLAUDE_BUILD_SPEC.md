# BUILD SPEC for Claude — MUTXRI TERMINAL data pipeline v2
Hand this to Claude Code. Work in D:\mutxri-terminal. Do NOT touch
features/panels/*.html chart logic unless a spec section says so — the
rendering code is now working; the failures are DATA and PIPELINE.

## Why this spec exists (user's exact complaints)
1. "No candlesticks/line graph" — repeated. Root causes were: chart code
   bugs (fixed) AND missing history data (NSE = 1 bar only).
2. "Financial panel never fixed" — was a malformed regex that slipped
   through the build (fixed), but the pipeline has NO verification gate,
   so bugs like it keep shipping.
3. "Prices don't match live" — stale listing vs fresh market snapshot
   (fixed by overlay), but nothing keeps them in sync automatically.

## The ONE missing data source (highest priority)
NSE has NO real OHLC history (only 1 bar/day via the archiver). NGX was
solved the same way — NGX publishes official daily price-list zips at:
  https://doclib.ngxgroup.com/DownloadsContent/GAINERS%20AND%20PRICE%20LIST%20FOR%20<DD-MM-YYYY>.zip
  (SharePoint API: /_api/Web/Lists(guid'dd86e37a-4967-478e-a670-e70e6986138f')/Items
  filter substringof('GAINERS%20AND%20PRICE%20LIST%20FOR%20<date>',Title))
  Each zip: PRICES1.pdf + PRICES_LIST2.pdf, columns:
  S/N COMPANY PCLOSE OOPEN OPEN HIGH LOW %SPREAD OCLOSE CLOSE CHANGE %CHANGE TRADES VOLUME VALUE
  Parser exists: fetch_ngx_history.py (164 symbols, 20+ bars each, works).

TASK 1 (do this FIRST): find the NSE equivalent. The Nairobi Securities
Exchange publishes daily price lists / official list files on nse.co.ke
(data services, dataservices subdomain, WordPress + WooCommerce shop).
The NSE ticker API is snapshot-only (POST https://nsenairobi.nse.co.ke/
nseticker/api/v1/ticker body {"nopage":"true","isinno":"KE3000009674"}).
Hunt for: downloadable daily price files (PDF/Excel/CSV) in the NSE data
services, the "Equity Market Meridian" app API, or any public historical
endpoint. mystocks.co.ke renders charts as PNG only (no data API).
Build fetch_nse_history.py mirroring fetch_ngx_history.py: download each
trading day's file, parse OHLC per symbol, write
static_data/history/NSE_<SYM>.json {bars:[{t,o,h,l,c,v}]}, dedupe,
cap 1500. If truly no free source exists, say so explicitly with proof
(each URL tried + response) — do NOT fabricate bars.

## Task 2 — refresh_all.py (the pipeline that stops regressions)
One script, idempotent, runnable anytime:
1. NSE: official ticker API (change field IS percent already) -> market_NSE.json
2. NGX: today's official price-list zip -> market_NGX.json + append history bars
3. JSE/EGX: Yahoo v8 chart + quote APIs, slow (~4s/symbol), ROUND ALL
   floats to 2dp (EGX had 157.02999877929688 garbage), skip no-data
   symbols with an empty {sym,bars:[]} marker file (honest: no data)
4. Reconcile: for each exchange, overlay market prices onto
   listing_<EX>.json so watchlist == info sheet ALWAYS (the price bug)
5. Rebuild static_index.html (node --check the BUILT file, not just
   source — the regex-escape bug lived in the built artifact)
6. Write deploy manifest; deploy via GitHub contents API (secrets in
   secrets_local.json key "github_pat", repo mutxri/MUTXRI-TERMINAL,
   branch gh-pages, path terminal/static_data/...). Never git push.
7. Print a verification report: counts per exchange, mismatches found,
   and run the Playwright smoke test below.

## Task 3 — Playwright regression gate (scripts/smoke_test.py)
Headless chromium. For each exchange JSE/EGX/NGX/NSE:
- open https://mutxriterminal.com/terminal/?ex=<EX>
- assert watchlist price of a known symbol equals its value in
  market_<EX>.json (the price-match contract)
- open the heatmap panel, click a symbol WITH history, assert
  #cpChart canvas count > 0 AND #cpStat shows "N bars" (not
  "no historical data")
- click a symbol WITHOUT history, assert the EOD card shows
  (honest fallback, never a blank)
- open the FINANCIALS panel, click 4SI.JO income/balance/cashflow,
  assert table rows render with real numbers (not dashes)
Exit non-zero on any failure. This gate runs AFTER every deploy and
blocks "done" claims.

## Task 4 — financials schema contract (finishes the financials panel)
The renderer expects: rows:[{label,values:[...]}] with labels matching
SCHEMA (Revenue, Cost of Sales, Gross Profit, Operating Expenses,
Operating Profit (EBIT), Net Finance Costs, Profit Before Tax, Income
Tax, Net Profit, EPS | balance: Non-current Assets, Cash &
Equivalents, Total Assets, Non-current Liabilities, Total Liabilities,
Total Equity | cashflow: Operating Cash Flow, Capital Expenditure,
Free Cash Flow, Investing Cash Flow, Financing Cash Flow, Net Change
in Cash). Files: static_data/financials/<TICKER>__<statement>.json
{available:true, periods:["FY2026",...], rows:[...]}.
Build a validator (scripts/validate_financials.py) that checks EVERY
file: schema-valid rows, periods length == values length, no NaN, no
fabricated-looking identical rows. Report per-exchange coverage.
For NSE: try AfricanFinancials PDFs (africanfinancials.com/company/
ke-<tkr>/) and the 8 official NSE PDFs in static_data/nse_pdfs/ — but
the 12-column layout made naive extraction WRONG (Total Assets = 9.0
was garbage). Use pdfplumber extract_table with column boundaries or
skip and keep honest filing links. NEVER ship wrong numbers.

## Constraints
- No fabricated data anywhere. Missing = honest marker file or EOD card.
- No em dashes in UI strings. No TradingView widget (free tier has no
  NSE/NGX symbols anyway).
- Node available; python 3.11; playwright installed; pdfplumber installed.
- Verify EVERY claim with a real browser run (playwright) or a live
  HTTP fetch — print the evidence in your final summary.
- Deliver: the scripts, a run of refresh_all.py that SUCCEEDS end to
  end, the smoke test passing, and NSE history status (real bars or
  explicit proof none exist free).
