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

### The metric engine, and proving it (`bot/statements.py`, `bot/selftest.py`)

```
python mutxri_ai.py selftest          # 47 checks against worked examples
python mutxri_ai.py analyse ABG.JO    # margins, DuPont, ROCE/ROIC, P/E, CAGR
```

**Python computes, Claude interprets.** The model is explicitly barred from
re-deriving any figure, and its system prompt carries the definition of every
metric so it reads them correctly. An LLM doing arithmetic on a balance sheet is
how you get a confident wrong P/E.

What is computed: margins; **ROE** with a **DuPont** split (margin x asset
turnover x equity multiplier); **ROCE and ROIC** on capital employed, which
unlike ROE are not flattered by leverage; **P/E, P/B, P/S, earnings yield,
EV/EBIT**; CAGR; interest cover; quick and current ratios; inventory and
receivable days; effective tax rate; cash conversion.

Several of these need judgment the formula alone does not encode:

- **P/E is computed two ways** - market cap / net profit, and price / EPS - and
  the pair is reported. They should agree; where they do not, a share count or a
  currency unit is wrong upstream, and `peCrossCheck` says so instead of asking
  you to trust one.
- **Valuation is attached to the latest period only.** Market cap is a snapshot
  of today; pairing it with FY2023 earnings would invent a ratio that was never
  true.
- **EBIT is rebuilt** as PBT + net finance costs when a condensed filing omits
  it, but only up to 60% of revenue. Above that the finance line is a bank's
  interest expense, which is a cost of revenue, not financing - Absa's rebuild
  comes to 121.6bn against 115.2bn of revenue, which is the tell.
- **Capital employed has two bases** (assets less current liabilities, or equity
  plus debt) because most filings here never print a current-liabilities line.
  The basis is recorded so two companies are never silently compared on
  different ones. This took ROCE coverage from 0% to 56%.

`selftest` is what "self-improving" honestly means for calculation: not a model
that learns arithmetic, but a fixed engine whose arithmetic is measurably
correct. A fixture of round numbers with every answer worked out by hand, plus
identities that must hold whatever the numbers (DuPont reconciling to ROE, the
two P/E routes agreeing, the balance sheet balancing), plus the edge cases that
produced wrong answers before: negative equity, a loss, liabilities in brackets,
a gap in the fiscal years, a bank's EBIT. **47/47 pass.** Writing it immediately
caught a live boundary bug - the EBIT gate admitted a rebuild worth exactly 100%
of revenue, which implies a company with no costs.

### Named models (`bot/models.py`)

Ratios describe a company; these score it, using published methods with cited
thresholds rather than house rules invented here.

- **Piotroski F-Score** — nine binary tests of profitability, leverage and
  efficiency. Scored only over the signals the data supports, and the score
  says so (`4/8`). The share-issuance signal needs a share count for two years
  and these filings carry one, so it is reported unavailable rather than assumed
  clean — assuming it would inflate every score by a point.
- **Altman Z''-score**, emerging-market variant, which drops the sales/assets
  term and adds a constant precisely so it works outside US manufacturing. It
  **refuses to compute without retained earnings** rather than dropping a term:
  a partial Z'' looks like a Z-score and is not one.
- **Sloan accruals** — the gap between reported profit and cash over average
  assets. High accruals predict weaker earnings next period.
- **Cost-to-income** — what banks are actually judged on, and banks are a large
  share of these markets by value.
- **Graham number** and book value per share; **operating leverage**.

Deliberately **not** implemented, because this corpus cannot support them
honestly — the line items are not in the filings:

| Model | Missing |
|---|---|
| Beneish M-Score | receivables, depreciation, SG&A across two periods |
| Cash conversion cycle | inventory, receivables, payables |
| Dividend cover and yield | a dividends-paid line in the cash flow statement |

Those items are mapped in `statements.py` anyway, so each model activates by
itself for a private company whose accounts do carry them. Reporting "not
computable, and here is what was missing" beats a number built from substitutes.

**A coverage fix worth more than any single model:** only 7% of these filings
print a current-assets line, but 63% print non-current assets against a total —
and current is the remainder by definition. Deriving it took the current ratio,
working capital and everything built on them from ~0% of the corpus to 56%.

### Screening and peers (`bot/screen.py`)

`analyse` reads one company; this reads all 557 at once.

```
python mutxri_ai.py screen --list-flags
python mutxri_ai.py screen --exchange JSE --sector mining --flag cash_burn
python mutxri_ai.py screen --where "roe>15" --where "ocf_to_net_profit<0.8"
python mutxri_ai.py peers ABG.JO
```

A ratio without a peer group means little — 12% net margin is excellent for a
retailer and poor for a bank — so `peers` gives the sector median and a
percentile beside the company's own figure. Two honesty rules: a percentile from
fewer than 5 peers is marked `*` as an ordering rather than a measurement, and
where a sector group is too small (Safaricom is the NSE's only telecom) the
comparison widens to the whole exchange and **says so** instead of showing
blanks. The corpus takes ~40s to build and is cached until the statement files
change.

Across the corpus today: 90 companies with thin interest cover, 77 with
persistently weak cash conversion, 60 loss-making, 8 with negative equity.

### Watchlist alerts (`bot/watch.py`)

```
python mutxri_ai.py watch add --ticker SCOM --ticker ACL.JO --min-impact 45
python mutxri_ai.py watch check
python mutxri_ai.py watch check --dry-run
```

Every other part of this package produces a snapshot — run the scan twice and
you see the same stories twice. This reports **only what is new since the last
check**, for the securities you actually hold: news signals above your impact
floor, and statement flags as they appear *or clear* (a going-concern flag
lifting is news too). Seen-state is held for 30 days, deliberately longer than
the 7-day news window, so nothing can expire from state while still in the scan
and re-fire as new. `--dry-run` previews without consuming.

### Data health (`bot/health.py`)

```
python mutxri_ai.py doctor
```

Stale data fails quietly: a three-week-old price file still parses, still
renders, and reports last month's market with total confidence. `doctor` grades
every input by age against a per-file expectation (prices go stale in a day,
parsed annual statements do not), reports per-exchange price coverage and
suspect rows, whether the last news scan reached its feeds, and which optional
capabilities are switched on. It fixes nothing — it tells you which collector to
run.

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
