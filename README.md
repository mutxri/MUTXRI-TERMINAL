# MUTXRI TERMINAL

Godel-style financial terminal for African markets (NSE Nairobi/KES, NGX Lagos/NGN,
JSE Johannesburg/ZAc, EGX Cairo/EGP; ~1,030 listed securities).
**LIVE at https://mutxriterminal.com** (landing at root, terminal at `/terminal/`).

## Architecture (read this first — avoids 90% of confusion)

- **Browser SPA, zero backend.** Everything is static files on GitHub Pages.
  - `index.html` — terminal shell (watchlist, tape, info sheet, chart panel)
  - `features/panels/afri_heatmap.html` — heatmap with click-to-chart (candles/line/area, 1D/1M/1Y/10Y/ALL)
  - `features/panels/afri_financials.html` — income/balance/cashflow (JSE 276 + EGX 89 securities)
  - `features/panels/afri_corp.html` — corporate actions (NSE 43, NGX 1,000 disclosures), exchange-aware via `?ex=`
  - `features/panels/afri_news.html`, `afri_bnd.html`, `afri_ratings.html`, ... — other panels
- **Charting**: lightweight-charts v4.1.3 (canvas), in-house. TradingView widget was removed —
  it has zero free NSE/NGX symbols (`NAIROBI:SCOM` doesn't exist) and its fallback never rendered.
- **Data**: `static_data/*.json` snapshots, fetched by the `fetch_*.py` scripts.
  - `market_<EX>.json` — THE single source of price truth (watchlist + info sheet + heatmap all read it)
  - `listing_<EX>.json` — security metadata (name/sector/instrument), prices overlaid from market
  - `heatmap_<EX>.json` — heatmap cells (rebuilt FROM market via `rebuild_heatmaps.py` so they can't disagree)
  - `history/NSE_<SYM>.json`, `history/NGX_<SYM>.json`, `history/<SYM>.json` (JSE) — OHLC bars
  - `financials/<TICKER>__<statement>.json` — parsed statements (rows:[{label,values}], periods:[...])
  - `financials_index.json` — which securities have statements
- **Deploy**: `build_static_frontend.py` → `assemble_deploy.py` → GitHub contents API
  (secrets in `secrets_local.json`, gitignored). `git push` to gh-pages BYPASSES the
  Pages webhook — always use the contents API. New panels join `STATIC_PANELS`.
  `deploy_changed.py` = delta deploy (blob-SHA diff) for big data pushes.
- **Cron**: "NSE history archiver" 16:00 Mon–Fri (`build_nse_history.py`).

## Data sources (all official, all honest)

| Exchange | Prices (live snapshot) | History (candles) | Financials |
|---|---|---|---|
| NSE | official ticker API (nsenairobi.nse.co.ke) | **official IR feed** `ir.nse.co.ke/hist/<TKR>?d=YYYY-MM-01;ref=tbl` (referer nse.co.ke/share-price/) — 19 majors have 475-494 real bars | filing links only (no parsed statements yet) |
| NGX | official daily price-list zips (doclib.ngxgroup.com, every trading day since 2014) | same zips → 146/156 cells with real bars | 1,000 official disclosures in CORP |
| JSE | Yahoo v8 chart API (~4s/symbol throttle) | 256/327 cells (rest: Yahoo has no data — delisted/renamed) | 276 parsed statements |
| EGX | Yahoo (tickers need `.CA` suffix) | 214/374 cells (rest: Yahoo dropped EGS-coded names) | 89 parsed statements |

## Honest ceilings (verified, NOT bugs — do not "fix" by fabricating)

- **NSE history is exchange-sold** (Ksh 350/download; evaluation form on nse.co.ke dataservices).
  The IR feed covers only tickers with an IR page on ir.nse.co.ke (KCB/BAT/BAMB fail — verified every variant).
- **JSE/EGX gaps**: companies Yahoo genuinely doesn't carry. Tested live: no data anywhere free.
- **No source credits in UI** (user: "dont credit my stock"). EOD/DELAYED honesty labels stay.
- **Never fabricate bars/statements.** Missing → honest EOD card ("NO FREE OHLC FEED · SYM · EOD")
  or `data-empty`. The EOD card shows the real board price/change/volume from the snapshot.

## Rules that must never be broken (user-enforced)

1. No fake data. Missing = honest empty state. Verify in a real browser (Playwright) before claiming done.
2. Credentials stay in `secrets_local.json` (gitignored). Never ask the user to paste tokens.
3. `users.json`, `static_data/`, `ceos.json` NEVER committed — data ships via contents API.
4. No em dashes in UI strings. No TradingView widget. Godel palette (mint #33e29a / teal #1ecfb0 on black, Oxygen Mono).
5. Landing page must match terminal reality (no "real-time" claims over snapshots).

## Known active scripts

- `fetch_nse_history_fast.py` — threaded NSE IR-feed history (24 months, 19 majors)
- `fetch_ngx_history.py` — NGX official price-list zips → per-symbol OHLC (3 PDF formats)
- `fetch_nse_official.py` / `fetch_nse_mystocks.py` — NSE market snapshots
- `refresh_history.py` — JSE/EGX Yahoo history (never overwrites good data with empty)
- `rebuild_heatmaps.py` — heatmaps from market files (single source of truth)
- `build_nse_history.py` — daily official-bar archiver (cron)
- `append_nse_bars.py` — append today's official bar per NSE symbol
- `deploy_changed.py` / `push_atomic.py` — contents-API deploy helpers
- `nse_ir_adapter.js` (static_data) — browser-side adapter: static history first, IR-feed fallback

## Deploy checklist

1. Edit source (`features/panels/*.html` or `static_data/*`)
2. `python build_static_frontend.py` (rebuilds static_index.html)
3. `python assemble_deploy.py` (builds gh_pages_deploy/)
4. Contents-API push (core files + changed data; `deploy_changed.py` for big batches)
5. Wait for Pages build (5–10 min), verify live URLs, Playwright-render check
6. `git commit` (source only — static_data is gitignored)
