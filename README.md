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

## Market intelligence bot (`market_bot.py` + `bot/`)

Pulls the financial state of all four exchanges and scans news that can move them,
linking each story to the listed securities and macro themes it actually touches.
Runs as step 7 of `refresh_all.py`; surfaces in the terminal as the **BOT** panel.

```
python market_bot.py                 # full run, writes both JSON files
python market_bot.py --brief         # desk brief only, writes nothing
python market_bot.py --exchange NSE  # focus one market
python market_bot.py --no-social     # skip the X/Twitter tier
```

- `bot/universe.py` — the 922-security match index built from `listing_*`/`market_*`.
  Aliases must be *distinctive*: a surface made only of generic words ("middle east",
  "the egyptian") is dropped, and issuer names that are ordinary English words
  (Equity, Zenith, Discovery, Access, Clicks) require an exchange or country cue in
  the same text before news is pinned on them. Tickers under 4 characters need a cue too.
- `bot/sources.py` — 26 reachability-checked feeds in three tiers: **local** home-market
  press per exchange, **global** macro wires, and **social** (X/Twitter). Google News
  search RSS carries the Kenyan and Egyptian coverage, where the direct feeds are
  404/WAF-gated. Failing sources are reported, never silently dropped.
- `bot/impact.py` — scoring. A story reaches a market either by **entity** (it names a
  listed company, direction from a corporate-event lexicon) or by **theme** (oil, the
  Fed, a currency, a policy rate — each theme carries an exposure map with a sign per
  exchange/sector, so a rising oil price is bullish NGX energy and bearish import-heavy
  NSE/EGX). `impact = relevance × confidence`, confidence blending source weight with a
  48-hour recency half-life. It ranks what to read first; it does not forecast prices.
- `bot/market.py` — consolidated breadth, movers, sectors and cross-asset context.
  Tone reads off a **trimmed mean of rows that actually traded**: a plain mean is
  hostage to one mispriced small cap, and a median is structurally 0 on boards where
  most listings don't trade. Rows printing beyond ±35% are excluded as bad prints and
  reported in `breadth.suspectRows` rather than quietly poisoning the average.

Outputs `static_data/bot_market_state.json` and `static_data/bot_signals.json`.

**X/Twitter tier** needs `X_BEARER_TOKEN` (X has no free search tier and the public
Nitter mirrors are gone). Without it the bot reports the tier as `disabled` rather than
implying the timeline was quiet — the other 25 sources run normally.

## MUTXRI analyst (`mutxri_ai.py` + `bot/statements.py`, `ingest.py`, `analyst.py`, `social.py`)

Reads financial statements — listed **and** private companies — and puts language
around the numbers. Companion to `market_bot.py`, which scans markets and news.

```
python mutxri_ai.py analyse ABG.JO --explain
python mutxri_ai.py ingest accounts.xlsx --name "Savanna Logistics" --save
python mutxri_ai.py ingest filing.pdf --name "Acme Ltd" --read-with-claude
python mutxri_ai.py brief
python mutxri_ai.py ask "which NGX banks show weak cash conversion?"
python mutxri_ai.py social draft --from-signals 5
```

**The load-bearing rule: Python computes, Claude explains.** `bot/statements.py`
calculates every margin, growth rate, return, leverage and liquidity ratio in code;
`bot/analyst.py` only ever interprets figures handed to it. A language model must
never be the thing doing arithmetic on a balance sheet, and the system prompt tells
it not to derive numbers — if a figure is missing it must say so.

- `bot/statements.py` — canonical line-item mapping, ~20 metrics per period, and
  earnings-quality flags (profit rising while operating cash falls, weak cash
  conversion, thin interest cover, margin compression, cash burn, negative equity).
  Growth is computed **only between adjacent fiscal years** — the corpus has gaps
  like FY2026 → FY2025 → FY2022, and a three-year gap is reported, not silently
  treated as one year of growth.
- **Consistency audit** — `verify()` checks the accounting identities (assets =
  liabilities + equity, gross profit = revenue − cost of sales, net profit = PBT −
  tax). This is what makes model-assisted extraction safe: if a digit was misread,
  the identities stop holding and the caller is told, instead of a confident wrong
  ratio reaching a user.
- `bot/ingest.py` — private companies. CSV/XLSX/JSON/PDF into the same canonical
  shape, so a private company gets the same ratios and flags as a listed one.
  Handles accounting negatives in brackets, section headings, and out-of-order
  periods. Ingested private financials live in `static_data/private/`, which is
  **gitignored** — they never enter version control or the deploy.

  **PDFs are read from the text layer, not from extracted tables.** Real filings
  lay statements out with whitespace rather than ruled cells, so `pdfplumber`'s
  table extractor returns value-only columns with every label dropped — it parsed
  0 of 30 real filings. The text layer keeps them (`Net revenue 23,192 25,716`).
  Four things the parser has to get right, each found by running it over
  `_nse_pdf`, `jse_pdfs` and `_ngx_pdf`:
  - A space is only part of a figure when followed by exactly three digits (the
    `7 535` style). Otherwise `35,946 41,083` fuses into one impossible number.
  - Pages print two statements side by side, so one line reads `Profit after tax
    5,246 4,483 Non-current assets 9,687 10,061`. It is scanned
    label-then-figures repeatedly, recovering both rows.
  - Filings print `Label | Note | FY2025 | FY2024`, so rows with more figures
    than periods align to the **trailing** columns — leading ones made
    ArcelorMittal's revenue 4 and Aveng's 27.
  - A stranded note number is only wrong by its size: figures 1000× below the
    document's median are dropped and reported as `droppedOutOfScale` (EPS
    exempt). This caught Africa Prudential's revenue of 6 against a median
    figure of 1,663,845.

  **Honest rate: 23 of 30 real filings parse, with plausible headline figures on
  20 of those.** The rest, and anything scanned (BAMB.pdf has no text layer at
  all), are the model-assisted reader's job. `unmapped` and `droppedOutOfScale`
  are both printed so the output is auditable against the source document.
- `bot/analyst.py` — Claude Opus 5 with adaptive thinking; the system prompt is
  cached across calls. Also does **model-assisted transcription** of the filings
  the deterministic reader cannot handle — scanned pages, and layouts too broken
  for the text-layer parser. Claude reads the document into a strict schema and
  every number is then recomputed and audited in Python.
- `bot/social.py` — drafting and publishing, below.

### Social cards: real photographs only (`bot/images.py`, `bot/cards.py`)

```
python mutxri_ai.py card --signal 0 --draft
python mutxri_ai.py card --headline "Safaricom appoints Jane Mwangi to the board" \
    --company Safaricom --ticker SCOM --exchange NSE \
    --person "Jane Wanjiru Mwangi:Incoming non-executive director" \
    --person "Peter Ndegwa:Chief Executive" --draft
```

Builds a 1200×675 card from the company logo and photographs of the people a story
names. **No image is ever generated** — every picture is a real photo or logo from a
source that states who made it and on what terms.

Two problems this solves, both of which bite hard:

- **Identity.** An image search for a person's name matches the *description* of a
  photo, not the person in it — searching Commons for "Peter Ndegwa" returns a
  Nigerian civil-society photo with his name nowhere in it. So people are never
  resolved by image search. Instead: find the person's Wikipedia article, confirm
  it is about a person and that it corroborates the company, and take that
  article's lead image. A further check requires *both* given name and surname in
  the filename — "Al Shabani at the acquisition of Dangote Cement" contains
  "Dangote" because that is the company, and a surname-only test would wave it
  through as a portrait of Aliko Dangote. When it fails, confidence drops and the
  card is flagged `VERIFY: may not be a portrait`.
- **Licensing.** Republishing a press photo under a brand account is a copyright
  act. Wikimedia returns machine-readable licence metadata, so each asset is
  graded: CC0/public-domain and CC BY(-SA) are publishable; anything whose terms
  cannot be read is `unknown` and **blocked** unless you pass `--allow-unlicensed`
  and take responsibility for clearing it. Credits are drawn *into the pixels*,
  because CC BY requires attribution and a caption is stripped when a post is
  reshared.

**Often there is no licensed photograph of an African executive — including
Safaricom's own CEO.** In that case the card draws a typographic initials tile with
the person's name. A monogram is obviously a monogram; it is not a picture of some
other person, and the alt text says so too. The bot never substitutes a different
face and never invents one.

Reading *who* a story is about works with or without a model: the company comes
from the securities the signal is already linked to (computed against the real
listing), and names come from Claude when a key is set, or a capitalised-run
heuristic otherwise — cross-checked against the listing index so "Dangote Refinery"
is not read as a person.

### Social posting: drafted by the bot, published only by a person

The bot writes posts. It does not decide to publish them. Every draft lands in a
review queue at `static_data/social_queue.json` with status `pending`, and there is
**no scheduled path from "the bot noticed something" to "it went out under MUTXRI's
name"** — `refresh_all.py` never calls the publisher. A market account that posts
unattended can be wrong in public, at speed, about real companies.

Three gates:

1. **Grounding** — a draft is built from a scored signal or a computed analysis and
   carries the source URL and figures it came from.
2. **Screen** — compliance screen rejects buy/sell instructions, price targets and
   return promises, and enforces length. X counts every URL as 23 characters via
   t.co, so `post_length()` counts the way the platform does.
3. **Approval** — a person approves a named draft id, then publishes it in a
   separate command with an interactive confirmation. Both are appended to
   `static_data/social_audit.log`. The text is **re-screened at publish**, so
   editing a draft after approval blocks it rather than posting it.

Posting to X needs user-context OAuth 1.0a (`X_API_KEY`/`X_API_SECRET`/
`X_ACCESS_TOKEN`/`X_ACCESS_SECRET`) — the read-only `X_BEARER_TOKEN` used by the
news scan cannot post. LinkedIn needs `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_URN`.

Cards attach to drafts and upload with the post (X image upload is implemented
via the v1.1 media endpoint with OAuth 1.0a; LinkedIn image posts need the
assets `registerUpload` flow and are refused rather than silently posted as
text-only).

Dependencies: `pip install anthropic pdfplumber openpyxl pillow`.

## Known active scripts

- `mutxri_ai.py` — statement analysis, private-company ingest, briefs, post drafting
- `market_bot.py` — market intelligence bot (exchange state + news signals), see above
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
