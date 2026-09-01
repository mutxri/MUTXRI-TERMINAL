#!/usr/bin/env python3
"""_build_fix_pdf.py - render the "how to fix" runbook."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)

OUT = "MUTXRI_Fix_Runbook.pdf"

INK = colors.HexColor("#14181d"); MUTED = colors.HexColor("#5b6672")
RULE = colors.HexColor("#d7dde3"); BAND = colors.HexColor("#f2f5f8")
GOOD = colors.HexColor("#1a7f4f"); WARN = colors.HexColor("#b06a12")
BAD = colors.HexColor("#b3261e");  ACC = colors.HexColor("#0f766e")
CODEBG = colors.HexColor("#f6f8fa")


def S(n, **kw):
    b = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK, alignment=TA_LEFT)
    b.update(kw); return ParagraphStyle(n, **b)


BODY = S("b", spaceAfter=5)
SMALL = S("s", fontSize=8.3, leading=11.5, textColor=MUTED)
CELL = S("c", fontSize=8.3, leading=11.3)
CELLB = S("cb", fontSize=8.3, leading=11.3, fontName="Helvetica-Bold")
CODE = S("code", fontName="Courier", fontSize=8.0, leading=11.0)
H1 = S("h1", fontSize=19, leading=23, fontName="Helvetica-Bold", spaceAfter=3)
H2 = S("h2", fontSize=12.5, leading=16, fontName="Helvetica-Bold", spaceBefore=15,
       spaceAfter=6, textColor=ACC)
H3 = S("h3", fontSize=10, leading=13.5, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=3)
LEAD = S("l", fontSize=10, leading=15, textColor=MUTED, spaceAfter=2)

story = []; A = story.append


def rule(a=3, b=7):
    t = Table([[""]], colWidths=[170 * mm], rowHeights=[0.6])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
    A(Spacer(1, a)); A(t); A(Spacer(1, b))


def table(rows, widths, header=True):
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
          ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
          ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), BAND), ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE)]
    for i in range(2 if header else 1, len(rows), 2):
        st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fafbfc")))
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle(st)); return t


def code(lines):
    t = Table([[Paragraph(l.replace("&", "&amp;").replace("<", "&lt;"), CODE)] for l in lines],
              colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODEBG),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOX", (0, 0), (-1, -1), 0.4, RULE)]))
    return t


def tag(t, c):
    return Paragraph(f'<font color="{c.hexval()}"><b>{t}</b></font>', CELL)


# ── cover ──────────────────────────────────────────────────────────────────
A(Paragraph("MUTXRI TERMINAL", S("br", fontSize=8.5, leading=11, textColor=ACC,
                                 fontName="Helvetica-Bold")))
A(Spacer(1, 3))
A(Paragraph("Fix Runbook", H1))
A(Paragraph("Measured against the live site and the live backend on 1 September 2026. "
            "Five issues, each with the fix and how to confirm it worked.", LEAD))
rule()

A(Paragraph("Status right now", H2))
A(table([
    [Paragraph("<b>Item</b>", CELLB), Paragraph("<b>State</b>", CELLB), Paragraph("<b>Evidence</b>", CELLB)],
    [Paragraph("Backend service", CELL), tag("UP", GOOD),
     Paragraph("mutxri-terminal.onrender.com/api/health -> 200 (43s cold start)", CELL)],
    [Paragraph("Email sign-up / login", CELL), tag("WORKS", GOOD),
     Paragraph("Created an account and logged back in; both returned a token", CELL)],
    [Paragraph("Account persistence", CELL), tag("BROKEN", BAD),
     Paragraph("health reports db: json - accounts live on Render's ephemeral disk", CELL)],
    [Paragraph("Google sign-in", CELL), tag("BROKEN", BAD),
     Paragraph("“Google sign-in is not configured yet.” - env vars absent", CELL)],
    [Paragraph("GitHub sign-in", CELL), tag("BROKEN", BAD),
     Paragraph("“GitHub sign-in is not configured yet.” - env vars absent", CELL)],
    [Paragraph("Price freshness", CELL), tag("STALE", BAD),
     Paragraph("Snapshot is 30 Aug; 8/8 JSE prices wrong, MTN off by 4.23%", CELL)],
    [Paragraph("Screener", CELL), tag("BROKEN", BAD),
     Paragraph("25 JSE securities at +9900% and above; heatmap is clean", CELL)],
    [Paragraph("Heatmap / watchlist", CELL), tag("PASS", GOOD),
     Paragraph("821 cells, 0 disagreements, 0 impossible moves", CELL)],
    [Paragraph("Financial statements", CELL), tag("PASS", GOOD),
     Paragraph("540 index entries, 0 orphaned, 0 artefact values", CELL)],
    [Paragraph("Charts", CELL), tag("PASS", GOOD),
     Paragraph("682 chartable, 339 honest cards, 0 corrupt files", CELL)],
    [Paragraph("Logos", CELL), tag("PARTIAL", WARN),
     Paragraph("920/1,021 have a domain; roughly 1 in 6 render a generic globe", CELL)],
], [34 * mm, 20 * mm, 116 * mm]))

A(Spacer(1, 5))
A(Paragraph("Correction to my earlier reports: I tested mutxri-<b>backend</b>.onrender.com, a dead "
            "legacy hostname still referenced 9 times in the repo, and reported three times that no "
            "backend was deployed. The live host is mutxri-<b>terminal</b>.onrender.com and it is up. "
            "Email auth works; only persistence and OAuth are broken.", SMALL))

# ── fix 1 ──────────────────────────────────────────────────────────────────
A(Paragraph("Fix 1 - Accounts are wiped on every deploy", H2))
A(Paragraph("<font face='Courier' size='8'>/api/health</font> returns "
            "<font face='Courier' size='8'>\"db\": \"json\"</font>. That means "
            "<font face='Courier' size='8'>auth_api.py</font> fell back to writing "
            "<font face='Courier' size='8'>users.json</font> on the container's local disk, which "
            "Render replaces on every deploy and every restart or spin-down. Accounts do not survive.", BODY))

A(Paragraph("Find the real cause before changing anything", H3))
A(Paragraph("Every failure collapses into the same <font face='Courier' size='8'>db: json</font>. "
            "The server prints the actual reason once at startup:", BODY))
A(code(['except Exception as _e:',
        '    print("MongoDB unavailable:", str(_e)[:80])']))
A(Spacer(1, 4))
A(Paragraph("Open the Render service logs and find that line. It tells you which of these it is:", BODY))
A(table([
    [Paragraph("<b>Log text contains</b>", CELLB), Paragraph("<b>Cause</b>", CELLB), Paragraph("<b>Fix</b>", CELLB)],
    [Paragraph("bad auth / authentication failed", CELL), Paragraph("Wrong password", CELL),
     Paragraph("Reset the DB user password in Atlas and paste it URL-encoded into MONGODB_URI", CELL)],
    [Paragraph("timeout / no reachable servers", CELL), Paragraph("IP allowlist", CELL),
     Paragraph("Atlas > Network Access > add 0.0.0.0/0. Render's egress IPs are not static, so an allowlist of specific IPs will keep failing", CELL)],
    [Paragraph("no such host / getaddrinfo", CELL), Paragraph("Wrong cluster host", CELL),
     Paragraph("Re-copy the SRV string from Atlas > Connect", CELL)],
    [Paragraph("“MongoDB disabled (no MONGODB_URI)”", CELL), Paragraph("Variable not set", CELL),
     Paragraph("It is declared sync: false, so Render never reads it from the repo - it must be typed into the dashboard", CELL)],
], [42 * mm, 30 * mm, 98 * mm]))
A(Spacer(1, 4))
A(Paragraph("<b>The allowlist is at least as likely as the password.</b> If the password were the only "
            "problem you would see an auth error; a timeout means the connection never got far enough "
            "to be rejected. Read the log line rather than guessing again.", BODY))
A(Spacer(1, 3))
A(Paragraph("A password containing @ : / ? # [ ] must be percent-encoded inside the URI or it will "
            "break parsing and look like a wrong password.", SMALL))

A(Paragraph("Confirm it worked", H3))
A(code(['curl https://mutxri-terminal.onrender.com/api/health',
        '',
        '{"ok": true, "time": ..., "db": "mongo"}     <- fixed',
        '{"ok": true, "time": ..., "db": "json"}      <- still broken']))

# ── fix 2 ──────────────────────────────────────────────────────────────────
A(Paragraph("Fix 2 - Google and GitHub sign-in", H2))
A(Paragraph("The OAuth code is complete and correct on the <font face='Courier' size='8'>backend</font> "
            "branch - <font face='Courier' size='8'>oauth_start</font>, both providers, the callback "
            "exchange, all present. It returns the “not configured yet” message purely because "
            "the client id is an empty string.", BODY))

A(Paragraph("Step 1 - register the two OAuth apps", H3))
A(Paragraph("The callback URLs must match byte-for-byte. <font face='Courier' size='8'>auth_api.py</font> "
            "builds them from the request Host header, so on Render they resolve to:", BODY))
A(code(['https://mutxri-terminal.onrender.com/api/auth/oauth/google/callback',
        'https://mutxri-terminal.onrender.com/api/auth/oauth/github/callback']))
A(Spacer(1, 4))
A(table([
    [Paragraph("<b>Provider</b>", CELLB), Paragraph("<b>Where</b>", CELLB), Paragraph("<b>Notes</b>", CELLB)],
    [Paragraph("GitHub", CELL), Paragraph("Settings > Developer settings > OAuth Apps > New", CELL),
     Paragraph("Homepage https://mutxriterminal.com; paste the callback above as the Authorization callback URL", CELL)],
    [Paragraph("Google", CELL), Paragraph("Cloud Console > APIs &amp; Services > Credentials > OAuth client ID > Web application", CELL),
     Paragraph("Add the callback above as an Authorized redirect URI, and configure the consent screen", CELL)],
], [22 * mm, 66 * mm, 82 * mm]))
A(Spacer(1, 4))
A(Paragraph("<b>If these were registered against mutxri-terminal.onrender.com they must be re-pointed</b> - "
            "a mismatched redirect URI fails even with correct credentials.", BODY))

A(Paragraph("Step 2 - add four variables in the Render dashboard", H3))
A(Paragraph("All four are declared <font face='Courier' size='8'>sync: false</font> in render.yaml, "
            "which means Render will never populate them from the repository:", BODY))
A(code(['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
        'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET']))

A(Paragraph("Confirm it worked", H3))
A(code(['curl https://mutxri-terminal.onrender.com/api/auth/oauth/google/start',
        '',
        '{"ok": true, "url": "https://accounts.google.com/o/oauth2/..."}   <- fixed',
        '{"ok": false, "error": "Google sign-in is not configured yet."}   <- vars still missing']))

A(Spacer(1, 5))
A(Paragraph("<b>Google starts in Testing mode</b>, where only email addresses you list explicitly can "
            "sign in - everyone else sees “access blocked”. Publish the consent screen before "
            "real users arrive. The current scope (openid email profile) is basic, so publishing should "
            "not require review.", BODY))

# ── fix 3 ──────────────────────────────────────────────────────────────────
A(Paragraph("Fix 3 - Prices are two sessions stale", H2))
A(Paragraph("Today is 1 September. The snapshot is from 30 August and its newest bar is the 28 August "
            "close, so Monday and today are both missing. Every JSE price on the site is wrong.", BODY))
A(Spacer(1, 4))
A(table([
    [Paragraph("<b>Security</b>", CELLB), Paragraph("<b>Site shows</b>", CELLB),
     Paragraph("<b>Actual</b>", CELLB), Paragraph("<b>Error</b>", CELLB)],
    [Paragraph("MTN", CELL), Paragraph("19,000", CELL), Paragraph("19,840", CELL), tag("-4.23%", BAD)],
    [Paragraph("AGL", CELL), Paragraph("93,150", CELL), Paragraph("89,823", CELL), tag("+3.70%", BAD)],
    [Paragraph("NPN", CELL), Paragraph("78,939", CELL), Paragraph("76,822", CELL), tag("+2.76%", BAD)],
    [Paragraph("ABG", CELL), Paragraph("23,147", CELL), Paragraph("22,700", CELL), tag("+1.97%", BAD)],
    [Paragraph("SHP", CELL), Paragraph("30,700", CELL), Paragraph("31,314", CELL), tag("-1.96%", BAD)],
], [30 * mm, 40 * mm, 40 * mm, 30 * mm]))
A(Spacer(1, 5))
A(Paragraph("In fairness the badge reads “EOD SNAPSHOT - 2026-08-30”, so the page is honest "
            "about being a snapshot. But a visitor on Tuesday reading Friday's prices as current is a "
            "worse failure than an empty panel.", BODY))
A(Paragraph("The refresh chain", H3))
A(code(['python refresh_history.py JSE,EGX --workers 8 --topup',
        'python build_market_snapshots.py',
        'python rebuild_heatmaps.py',
        'python assemble_deploy.py',
        '# then deploy gh_pages_deploy/']))
A(Spacer(1, 4))
A(Paragraph("Takes a few minutes. <b>This needs to run on a schedule</b>, not by hand - it is the "
            "difference between a terminal and a screenshot. A daily cron after each market closes is "
            "enough while the data is end-of-day.", BODY))

# ── fix 4 ──────────────────────────────────────────────────────────────────
A(Paragraph("Fix 4 - The screener shows +9900% moves", H2))
A(Paragraph("The cents-versus-rand bug was fixed in the heatmap and the watchlist, which are both clean. "
            "The screener reads its own file, <font face='Courier' size='8'>screener_JSE.json</font>, "
            "which never received the sanity cap:", BODY))
A(Spacer(1, 3))
A(code(['CAC.JO    +13177.31%        EXP.JO     +9955.56%',
        'MHB.JO    +10401.19%        ANI.JO     +9900.00%',
        'NPKP.JO   +10347.76%        ... 21 more at exactly +9900%']))
A(Spacer(1, 4))
A(Paragraph("25 securities on JSE, 1 on EGX. It is the most visible surface you have: a screener sorted "
            "by change puts the broken rows at the top by design.", BODY))
A(Paragraph("The fix", H3))
A(Paragraph("Build the screener from <font face='Courier' size='8'>market_&lt;EX&gt;.json</font> the way "
            "<font face='Courier' size='8'>rebuild_heatmaps.py</font> already does, so there is one "
            "source of price truth rather than three. Failing that, apply the same per-exchange cap "
            "(JSE 50%, EGX 25%, NGX/NSE 15%) when the screener file is written - each cap sits above "
            "that exchange's own daily price band, so nothing real is ever suppressed.", BODY))

# ── fix 5 ──────────────────────────────────────────────────────────────────
A(Paragraph("Fix 5 - Smaller things", H2))
A(table([
    [Paragraph("<b>Issue</b>", CELLB), Paragraph("<b>Fix</b>", CELLB)],
    [Paragraph("43-second cold start", CELLB),
     Paragraph("Render's free tier sleeps after 15 minutes idle. The first person to click Get Access "
               "after a quiet spell waits 43 seconds and will assume it is broken. The $7/month Starter "
               "plan removes it - this is the one cost worth paying before launch.", CELL)],
    [Paragraph("Sessions lost on restart", CELLB),
     Paragraph("_SESSIONS, _OAUTH_STATE and _OAUTH_CODES are plain in-process dicts. Every restart logs "
               "everyone out, and an OAuth round trip that spans a sleep fails with an invalid-state "
               "error. Move all three to the database - same fix for all three.", CELL)],
    [Paragraph("Four reverted features", CELLB),
     Paragraph("Statements in the Market rail, the rail chart, the FINANCIALS panel following the "
               "watchlist, and the (derived) share label are all still absent from production after a "
               "concurrent deploy of index.html. Recoverable from git history once the deploy race is "
               "settled.", CELL)],
    [Paragraph("Generic globe logos", CELLB),
     Paragraph("920/1,021 securities have a domain, but for roughly one in six Google has no icon and "
               "returns its own globe with HTTP 200 - which never fires onerror, so the monogram "
               "fallback does not run. Detect the placeholder by its dimensions in onload and fall back "
               "to the letter. A letter is more useful than a globe.", CELL)],
    [Paragraph("Stale hostname", CELLB),
     Paragraph("mutxri-terminal.onrender.com is referenced 9 times in the repository and is dead. It cost "
               "me three wrong diagnoses. Delete the references so nobody else tests the wrong host.", CELL)],
], [34 * mm, 136 * mm]))

# ── order ──────────────────────────────────────────────────────────────────
A(Paragraph("Order to do them in", H2))
A(table([
    [Paragraph("<b>#</b>", CELLB), Paragraph("<b>Action</b>", CELLB), Paragraph("<b>Why first</b>", CELLB)],
    [Paragraph("1", CELL), Paragraph("Read the Render log line for the Mongo failure", CELL),
     Paragraph("Everything about persistence depends on knowing which cause it is", CELL)],
    [Paragraph("2", CELL), Paragraph("Fix MONGODB_URI or the Atlas allowlist", CELL),
     Paragraph("Until db reads mongo, every account you create is temporary", CELL)],
    [Paragraph("3", CELL), Paragraph("Refresh prices and deploy", CELL),
     Paragraph("The site is currently wrong, not merely incomplete", CELL)],
    [Paragraph("4", CELL), Paragraph("Add the four OAuth variables", CELL),
     Paragraph("Two of three sign-in buttons do nothing", CELL)],
    [Paragraph("5", CELL), Paragraph("Cap the screener", CELL),
     Paragraph("Most visible remaining data error", CELL)],
    [Paragraph("6", CELL), Paragraph("Upgrade off the free tier", CELL),
     Paragraph("43 seconds is longer than anyone will wait to sign up", CELL)],
], [10 * mm, 74 * mm, 86 * mm]))

A(Spacer(1, 10))
rule(0, 4)
A(Paragraph("Backend checked at mutxri-terminal.onrender.com; prices compared against Yahoo Finance "
            "live quotes and the NGX's published price list; coverage counts from a full sweep of "
            "static_data. 1 September 2026.", SMALL))


def footer(c, d):
    c.saveState(); c.setStrokeColor(RULE); c.setLineWidth(0.5)
    c.line(20 * mm, 14 * mm, 190 * mm, 14 * mm)
    c.setFont("Helvetica", 7.5); c.setFillColor(MUTED)
    c.drawString(20 * mm, 9.5 * mm, "MUTXRI TERMINAL - Fix Runbook")
    c.drawRightString(190 * mm, 9.5 * mm, "Page %d" % d.page)
    c.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=18 * mm, bottomMargin=20 * mm,
                        title="MUTXRI TERMINAL - Fix Runbook", author="MUTXRI TERMINAL")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
