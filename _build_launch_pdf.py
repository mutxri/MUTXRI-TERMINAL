#!/usr/bin/env python3
"""_build_launch_pdf.py - render the launch-readiness solutions document."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, KeepTogether)

OUT = "MUTXRI_Launch_Readiness.pdf"

INK   = colors.HexColor("#14181d")
MUTED = colors.HexColor("#5b6672")
RULE  = colors.HexColor("#d7dde3")
BAND  = colors.HexColor("#f2f5f8")
GOOD  = colors.HexColor("#1a7f4f")
WARN  = colors.HexColor("#b06a12")
BAD   = colors.HexColor("#b3261e")
ACC   = colors.HexColor("#0f766e")

ss = getSampleStyleSheet()

def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5,
                textColor=INK, alignment=TA_LEFT)
    base.update(kw)
    return ParagraphStyle(name, **base)

BODY    = S("body", spaceAfter=5)
SMALL   = S("small", fontSize=8.4, leading=11.6, textColor=MUTED)
CELL    = S("cell", fontSize=8.4, leading=11.4)
CELLB   = S("cellb", fontSize=8.4, leading=11.4, fontName="Helvetica-Bold")
MONO    = S("mono", fontName="Courier", fontSize=8.2, leading=11.2)
H1      = S("h1", fontSize=19, leading=23, fontName="Helvetica-Bold", spaceAfter=3)
H2      = S("h2", fontSize=12.5, leading=16, fontName="Helvetica-Bold",
            spaceBefore=15, spaceAfter=6, textColor=ACC)
H3      = S("h3", fontSize=10, leading=13.5, fontName="Helvetica-Bold", spaceBefore=9, spaceAfter=3)
LEAD    = S("lead", fontSize=10, leading=15, textColor=MUTED, spaceAfter=2)

story = []
A = story.append


def rule(space_before=3, space_after=7):
    t = Table([[""]], colWidths=[170 * mm], rowHeights=[0.6])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
    A(Spacer(1, space_before)); A(t); A(Spacer(1, space_after))


def table(rows, widths, header=True, zebra=True, align_right=()):
    st = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), BAND),
               ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE)]
    if zebra:
        for i in range(2 if header else 1, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfc")))
    for c in align_right:
        st.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(st))
    return t


def tag(text, color):
    return Paragraph(f'<font color="{color.hexval()}"><b>{text}</b></font>', CELL)


# ─────────────────────────────────────────────────────────── cover
A(Paragraph("MUTXRI TERMINAL", S("brand", fontSize=8.5, leading=11,
                                 textColor=ACC, fontName="Helvetica-Bold")))
A(Spacer(1, 3))
A(Paragraph("Launch Readiness &amp; Solutions", H1))
A(Paragraph("Verified against the live site at mutxriterminal.com on 30 August 2026. "
            "Every figure below was measured, not estimated.", LEAD))
rule()

A(Paragraph("Verdict", H2))
A(Paragraph(
    "The data layer is sound and ready to show people. Prices are exact against both independent "
    "sources, the panels agree with each other, and there is no fabricated data anywhere in the "
    "1,465 financial statement files. <b>Two things block launch:</b> nobody can sign up, and four "
    "shipped features have been reverted on production. Neither is a data problem.", BODY))

A(Spacer(1, 6))
A(table([
    [Paragraph("<b>Area</b>", CELLB), Paragraph("<b>State</b>", CELLB), Paragraph("<b>Evidence</b>", CELLB)],
    [Paragraph("Prices", CELL), tag("PASS", GOOD),
     Paragraph("145/145 NGX match the exchange's own price list; 8/8 JSE match Yahoo to the cent", CELL)],
    [Paragraph("Panel consistency", CELL), tag("PASS", GOOD),
     Paragraph("821 heatmap cells vs watchlist — 0 disagreements, 0 impossible moves", CELL)],
    [Paragraph("Financial statements", CELL), tag("PASS", GOOD),
     Paragraph("540 index entries, 0 with no file behind them; 1,465 files, 0 artefact values", CELL)],
    [Paragraph("Charts", CELL), tag("PASS", GOOD),
     Paragraph("682 chartable, 339 showing the honest no-history card, 0 corrupt files", CELL)],
    [Paragraph("Sign-up", CELL), tag("BLOCKER", BAD),
     Paragraph("Calls /api/auth/ — no backend deployed. Returns “Could not reach the server.”", CELL)],
    [Paragraph("Shipped features", CELL), tag("BLOCKER", BAD),
     Paragraph("4 features reverted on production by a concurrent deploy", CELL)],
    [Paragraph("Secondary panels", CELL), tag("GAPS", WARN),
     Paragraph("CORP indices blank, GLCO gold has no price, NEWS empty", CELL)],
    [Paragraph("Logos", CELL), tag("GAPS", WARN),
     Paragraph("648/1,021 have a logo; 252 EGX securities have no domain source", CELL)],
], [30 * mm, 22 * mm, 118 * mm], align_right=()))

# ─────────────────────────────────────────────── blockers
A(Paragraph("Blockers — fix before anyone gets the URL", H2))

A(Paragraph("1. Nobody can sign up", H3))
A(Paragraph(
    "The landing page collects an email and a password, posts to <font face='Courier' size='8.2'>/api/auth/</font>, "
    "and shows “Could not reach the server. Try again shortly.” The endpoint lives in "
    "<font face='Courier' size='8.2'>auth_api.py</font>, which is not deployed anywhere. Every sign-up fails.", BODY))
A(Paragraph("<b>Solution — no backend, no monthly cost:</b>", BODY))
A(table([
    [Paragraph("<b>Step</b>", CELLB), Paragraph("<b>What to do</b>", CELLB)],
    [Paragraph("1", CELL), Paragraph("Create a free Supabase project. It gives you Postgres plus hosted auth "
                                     "(email verification, password reset, OAuth) — none of which auth_api.py has.", CELL)],
    [Paragraph("2", CELL), Paragraph("Point the landing form at Supabase's client library instead of /api/auth/. "
                                     "The browser talks to it directly with a public anon key; no server process.", CELL)],
    [Paragraph("3", CELL), Paragraph("Enable Row Level Security on the users table before going live — it is off by default.", CELL)],
], [14 * mm, 156 * mm]))
A(Spacer(1, 4))
A(Paragraph("This also retires a latent bug: <font face='Courier' size='8.2'>_SESSIONS = {}</font> in auth_api.py is an "
            "in-process dictionary, so every restart would log out all users and it breaks outright on a second instance.", SMALL))

A(Paragraph("2. Four shipped features are reverted on production", H3))
A(Paragraph(
    "A second agent working in this repository deployed <font face='Courier' size='8.2'>index.html</font> over the "
    "version carrying these features. All four are confirmed absent from the live site right now.", BODY))
A(table([
    [Paragraph("<b>Feature</b>", CELLB), Paragraph("<b>Was working</b>", CELLB), Paragraph("<b>Live now</b>", CELLB)],
    [Paragraph("Financial statements in the Market rail", CELL), tag("yes", GOOD), tag("gone", BAD)],
    [Paragraph("Per-security chart in the Market rail", CELL), tag("yes", GOOD), tag("gone", BAD)],
    [Paragraph("FINANCIALS panel follows the watchlist selection", CELL), tag("yes", GOOD), tag("gone", BAD)],
    [Paragraph("“(derived)” label on estimated share counts", CELL), tag("yes", GOOD), tag("gone", BAD)],
], [95 * mm, 37 * mm, 38 * mm]))
A(Spacer(1, 4))
A(Paragraph(
    "<b>Solution:</b> stop the second agent, or give it and this session separate files. Re-applying the features "
    "without that produces a fourth revert. The code is recoverable from git history — the loss is the deploy race, "
    "not the work. Shares outstanding survives because the other agent implemented its own version of that row.", BODY))

# ─────────────────────────────────────────────── secondary
A(Paragraph("Secondary fixes — worth doing, not blocking", H2))

A(table([
    [Paragraph("<b>Issue</b>", CELLB), Paragraph("<b>What a user sees</b>", CELLB), Paragraph("<b>Solution</b>", CELLB)],
    [Paragraph("CORP indices", CELLB),
     Paragraph("“FTSE/JSE All Share — —”. Gainers, losers and movers below it all work.", CELL),
     Paragraph("Point the block at indices.json, which already carries JSE Top 40, All-Share and Top40 USD.", CELL)],
    [Paragraph("GLCO gold", CELLB),
     Paragraph("Gold shows no price; platinum, silver, Brent and WTI all show one.", CELL),
     Paragraph("One missing symbol in the commodities fetch. Also review the +12% and +15% metal moves — those look like period changes labelled as daily.", CELL)],
    [Paragraph("NEWS panel", CELLB),
     Paragraph("“no free news feed for JSE” — honest, but empty on every exchange.", CELL),
     Paragraph("Either wire a free RSS source or drop the tab until it has content. An empty tab reads as broken.", CELL)],
    [Paragraph("EGX logos", CELLB),
     Paragraph("252 of 374 EGX securities show a letter monogram.", CELL),
     Paragraph("No domain source exists — company_info.json holds zero EGX entries. Needs a one-off domain list. Do not guess: name-matching is what previously put Equity Group's logo on three unrelated securities.", CELL)],
    [Paragraph("Airtel Africa", CELLB),
     Paragraph("Figures labelled NGN; the company reports in USD.", CELL),
     Paragraph("AfricanFinancials leaves currency null and the build defaults by exchange. Add a per-security currency override.", CELL)],
], [26 * mm, 58 * mm, 86 * mm]))

# ─────────────────────────────────────────────── ceilings
A(Paragraph("Data ceilings — not bugs, and already labelled honestly", H2))
A(Paragraph(
    "These are the limits of what is publicly available for free. The terminal already tells the user rather than "
    "filling the gap with an estimate, which is the right behaviour. They are listed so you are not surprised when "
    "a customer asks.", BODY))
A(Spacer(1, 4))
A(table([
    [Paragraph("<b>Coverage</b>", CELLB), Paragraph("<b>JSE</b>", CELLB), Paragraph("<b>EGX</b>", CELLB),
     Paragraph("<b>NGX</b>", CELLB), Paragraph("<b>NSE</b>", CELLB), Paragraph("<b>Why</b>", CELLB)],
    [Paragraph("Listed", CELL), Paragraph("431", CELL), Paragraph("374", CELL), Paragraph("152", CELL), Paragraph("64", CELL), Paragraph("—", CELL)],
    [Paragraph("With a price", CELL), Paragraph("360", CELL), Paragraph("251", CELL), Paragraph("149", CELL), Paragraph("61", CELL),
     Paragraph("EGX gap is ISIN-coded lines Yahoo does not carry", CELL)],
    [Paragraph("Chartable", CELL), Paragraph("285", CELL), Paragraph("243", CELL), Paragraph("135", CELL), Paragraph("19", CELL),
     Paragraph("NSE: ir.nse.co.ke now serves only its own ticker", CELL)],
    [Paragraph("Statements", CELL), Paragraph("276", CELL), Paragraph("89", CELL), Paragraph("123", CELL), Paragraph("52", CELL),
     Paragraph("NGX/NSE from AfricanFinancials filings", CELL)],
    [Paragraph("Share count", CELL), Paragraph("271", CELL), Paragraph("88", CELL), Paragraph("127", CELL), Paragraph("61", CELL),
     Paragraph("NGX derived from market cap / price", CELL)],
    [Paragraph("Logo", CELL), Paragraph("327", CELL), Paragraph("122", CELL), Paragraph("136", CELL), Paragraph("63", CELL),
     Paragraph("Monogram fallback where absent", CELL)],
], [26 * mm, 15 * mm, 15 * mm, 15 * mm, 15 * mm, 84 * mm],
    align_right=(1, 2, 3, 4)))

A(Spacer(1, 6))
A(Paragraph("NSE Kenya history cannot be backfilled", H3))
A(Paragraph(
    "The archive was built from ir.nse.co.ke, which now returns 406 for every symbol except the NSE's own — its "
    "widget builds the URL from a client code, not the ticker. mystocks' history pages are 404, afx.kwayisi is "
    "unreachable, and Yahoo does not list Nairobi at all. <b>Solution:</b> append_nse_bars.py records one official "
    "board bar per run, so the archive grows forward from today. The 19 deep names are intact. To fix it faster you "
    "need a paid feed or a data-sharing arrangement with the exchange.", BODY))

# ─────────────────────────────────────────────── infra
A(Paragraph("Infrastructure — the $0 launch path", H2))
A(Paragraph(
    "You do not need to run a backend. The terminal is fully static, already live on GitHub Pages behind "
    "Cloudflare, and reads JSON snapshots with no API calls. A server process is the only thing here that would "
    "cost money, so do not have one yet.", BODY))
A(Spacer(1, 5))
A(table([
    [Paragraph("<b>Piece</b>", CELLB), Paragraph("<b>Where</b>", CELLB), Paragraph("<b>Cost</b>", CELLB)],
    [Paragraph("Terminal + landing page", CELL), Paragraph("GitHub Pages — already there", CELL), Paragraph("$0", CELL)],
    [Paragraph("Database + auth", CELL), Paragraph("Supabase free tier", CELL), Paragraph("$0", CELL)],
    [Paragraph("Payments", CELL), Paragraph("Stripe Checkout / Payment Links", CELL), Paragraph("~2.9% + 30¢ per sale", CELL)],
    [Paragraph("Stripe webhook", CELL), Paragraph("Supabase Edge Function or Cloudflare Worker", CELL), Paragraph("$0", CELL)],
], [45 * mm, 85 * mm, 40 * mm]))

A(Spacer(1, 6))
A(Paragraph("Why Postgres and not MongoDB", H3))
A(Paragraph(
    "Mongo is already scaffolded here, so this is a deliberate change of direction. Payments need guarantees that "
    "Postgres gives for free and Mongo makes you hand-roll: a unique constraint on email, a foreign key from "
    "subscription to user, a check constraint on status, and <font face='Courier' size='8.2'>INSERT … ON CONFLICT "
    "DO NOTHING</font> on the Stripe event id — that one line is your entire webhook idempotency story. Stripe "
    "retries aggressively; without it you double-credit people. Volume is irrelevant either way at hundreds of "
    "users, so choose on correctness.", BODY))
A(Spacer(1, 3))
A(Paragraph(
    "<b>Keep market data out of the database entirely.</b> sync_to_mongodb.py exists to avoid shipping large JSON "
    "files, but that trades a free CDN read for a paid round trip and adds a failure mode where the terminal goes "
    "blank if the database hiccups. The deploy-size problem it solves is already handled by deploy_changed.py, "
    "which pushes only changed files.", BODY))
A(Spacer(1, 3))
A(Paragraph("<b>Never store card data.</b> Stripe Checkout, and you keep only the customer id and subscription status.", BODY))

A(Spacer(1, 6))
A(Paragraph("Render vs Vercel, when you do need a backend", H3))
A(Paragraph(
    "Render. afri_server.py is a stdlib ThreadingHTTPServer — one long-running process. Vercel runs serverless "
    "functions and would need every route rewritten. Render runs it as-is, and backend_render/ already holds "
    "render.yaml, a Dockerfile, requirements.txt and a health check. Budget ~$7/month for the Starter plan: the "
    "free tier sleeps after 15 minutes, so your first visitor waits 50+ seconds, and Render's free Postgres "
    "expires after 30 days. The only thing that forces this decision is wanting live intraday quotes instead of "
    "end-of-day snapshots — a product choice, not a launch requirement.", BODY))

# ─────────────────────────────────────────────── caveat
A(Paragraph("One caveat on the day-change figure", H2))
A(Paragraph(
    "Yahoo leaves the last session or two null in its daily array while still knowing their closes. The change was "
    "being recomputed against the previous <i>populated</i> bar, so it silently spanned the gap — Sasol read +4.90% "
    "for a two-session move. This is fixed: each bar now carries the provider's own reported day change and the "
    "build uses it.", BODY))
A(Paragraph(
    "<b>Stated precisely:</b> the number is now the provider's own day figure rather than our arithmetic across a "
    "hole, which is better provenance. It is <i>not</i> independently verified — Yahoo is the only source for JSE "
    "and EGX, and its own fields contradict each other (chartPreviousClose is range-dependent and disagrees with "
    "regularMarketChangePercent for the same security). Treat JSE/EGX day changes as provider-reported. NGX is "
    "the one exchange where the change is verified against the exchange's own published price list.", BODY))

# ─────────────────────────────────────────────── order
A(Paragraph("Suggested order", H2))
A(table([
    [Paragraph("<b>#</b>", CELLB), Paragraph("<b>Action</b>", CELLB), Paragraph("<b>Effort</b>", CELLB)],
    [Paragraph("1", CELL), Paragraph("Stop the second agent, or split the files it and this session touch", CELL), Paragraph("minutes", CELL)],
    [Paragraph("2", CELL), Paragraph("Wire sign-up to Supabase and confirm a real account is created", CELL), Paragraph("1–2 hours", CELL)],
    [Paragraph("3", CELL), Paragraph("Re-apply the four reverted features once the deploy race is settled", CELL), Paragraph("30 minutes", CELL)],
    [Paragraph("4", CELL), Paragraph("Fix CORP indices and GLCO gold; hide NEWS until it has content", CELL), Paragraph("1 hour", CELL)],
    [Paragraph("5", CELL), Paragraph("Launch read-only with the waitlist working", CELL), Paragraph("—", CELL)],
    [Paragraph("6", CELL), Paragraph("Add Stripe once people are asking to pay", CELL), Paragraph("later", CELL)],
], [10 * mm, 130 * mm, 30 * mm]))

A(Spacer(1, 10))
rule(space_before=0, space_after=4)
A(Paragraph(
    "All figures measured against the live site on 30 August 2026. Coverage counts come from a full sweep of "
    "static_data; price checks compare against the NGX's published price list and Yahoo Finance.", SMALL))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE); canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7.5); canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 9.5 * mm, "MUTXRI TERMINAL — Launch Readiness & Solutions")
    canvas.drawRightString(190 * mm, 9.5 * mm, "Page %d" % doc.page)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4,
                        leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=18 * mm, bottomMargin=20 * mm,
                        title="MUTXRI TERMINAL - Launch Readiness & Solutions",
                        author="MUTXRI TERMINAL")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
