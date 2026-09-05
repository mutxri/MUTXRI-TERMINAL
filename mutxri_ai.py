#!/usr/bin/env python3
"""mutxri_ai.py - the MUTXRI analyst: read statements, explain them, draft posts.

Companion to market_bot.py (which scans markets and news). This is the layer that
reads financial statements - listed or private - and puts language around numbers.

    # Deterministic: ratios, trends, earnings-quality flags, consistency audit
    python mutxri_ai.py analyse ABG.JO
    python mutxri_ai.py analyse SCOM --explain          # + Claude's analyst note

    # Private companies: ingest management accounts or an audited PDF
    python mutxri_ai.py ingest accounts.xlsx --name "Savanna Logistics" --save
    python mutxri_ai.py ingest scan.pdf --name "Acme Ltd" --read-with-claude

    # Language layer over the market scan
    python mutxri_ai.py brief
    python mutxri_ai.py ask "which NGX banks show weak cash conversion?"

    # Social: draft -> review -> approve -> publish. Never automatic.
    python mutxri_ai.py social draft --from-signals 5
    python mutxri_ai.py social list
    python mutxri_ai.py social approve <id> --by jimmy
    python mutxri_ai.py social publish <id> --by jimmy

Nothing here posts anything without a person naming a draft and confirming it,
and no scheduled job calls the publisher.

Credentials: the language features need ANTHROPIC_API_KEY (or `ant auth login`).
Publishing needs the platform keys listed in .env.example. Everything
deterministic - the statement analysis, the ratios, the flags, the drafting
templates - runs with no credentials at all.
"""
import argparse, json, os, re, sys, textwrap

from bot import analyst, cards, ingest, social, statements as S

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")

RESET, DIM, BOLD = "\033[0m", "\033[2m", "\033[1m"
GREEN, RED, YELLOW, CYAN = "\033[32m", "\033[31m", "\033[33m", "\033[36m"
_COLOUR = sys.stdout.isatty()


def c(s, col):
    return (col + str(s) + RESET) if _COLOUR else str(s)


def _n(v, fmt="%.0f"):
    return fmt % v if isinstance(v, (int, float)) else "-"


def print_analysis(a, show_all=False):
    e = a["entity"]
    print()
    print(c("%s - %s" % (e.get("ticker") or e.get("id"), e.get("name")), BOLD)
          + c("  [%s%s]" % (e.get("kind", "public"),
                            ", " + e["currency"] if e.get("currency") else ""), DIM))
    src = a.get("source") or {}
    if src:
        print(c("source: %s %s" % (src.get("kind", "?"), src.get("detail") or ""), DIM))

    print(c("\n%-8s %14s %13s %8s %8s %8s %8s %9s" %
            ("PERIOD", "REVENUE", "NET PROFIT", "MARGIN", "ROE", "D/E", "OCF/NP", "REV G"), DIM))
    for r in a["metrics"]:
        g = r.get("revenue_growth")
        gcol = GREEN if isinstance(g, (int, float)) and g > 0 else RED
        print("%-8s %14s %13s %8s %8s %8s %8s %9s" % (
            r["period"], _n(r["revenue"]), _n(r["net_profit"]),
            _n(r["net_margin"], "%.1f%%"), _n(r["roe"], "%.1f%%"),
            _n(r["debt_to_equity"], "%.2f"), _n(r["ocf_to_net_profit"], "%.2f"),
            c(_n(g, "%+.1f%%"), gcol) if isinstance(g, (int, float)) else "-"))
        if r.get("yearsSincePrior") not in (None, 1):
            print(c("         (prior period is %s years back - growth not computed)"
                    % r["yearsSincePrior"], DIM))

    if a["flags"]:
        print(c("\nFLAGS", BOLD))
        for f in a["flags"]:
            col = RED if f["severity"] == "high" else (YELLOW if f["severity"] == "medium" else DIM)
            print("  %s %s" % (c("[%s]" % f["severity"].upper(), col), f["label"]))
            print(c("      %s" % f["detail"], DIM))
    else:
        print(c("\nno flags raised", DIM))

    m = a["metrics"][0] if a.get("metrics") else {}
    ratios = [
        ("ROCE", m.get("roce"), "%"), ("ROIC", m.get("roic"), "%"),
        ("asset turnover", m.get("asset_turnover"), "x"),
        ("equity multiplier", m.get("equity_multiplier"), "x"),
        ("quick ratio", m.get("quick_ratio"), ""),
        ("current ratio", m.get("current_ratio"), ""),
        ("inventory days", m.get("inventory_days"), "d"),
        ("receivable days", m.get("receivable_days"), "d"),
        ("effective tax", m.get("effective_tax_rate"), "%"),
    ]
    shown = [(k, val, u) for k, val, u in ratios if val is not None]
    if shown:
        print(c("\nRETURNS AND EFFICIENCY", BOLD))
        for i in range(0, len(shown), 3):
            print("  " + "".join("%-16s %10s   " % (k, ("%.2f%s" % (val, u)))
                                 for k, val, u in shown[i:i+3]))
        if m.get("capital_employed_basis"):
            print(c("  capital employed: %s" % m["capital_employed_basis"], DIM))
        if m.get("ebit_derived"):
            print(c("  EBIT was not reported; rebuilt as PBT + net finance costs", DIM))
        if m.get("roe") is not None and m.get("asset_turnover") and m.get("equity_multiplier"):
            print(c("  DuPont: ROE %.2f%% = margin %.2f%% x turnover %.2fx x leverage %.2fx"
                    % (m["roe"], m["net_margin"], m["asset_turnover"],
                       m["equity_multiplier"]), DIM))

    val = a.get("valuation") or {}
    if val.get("marketCap"):
        print(c("\nVALUATION", BOLD) + c("  (current market cap vs %s)"
                                         % val.get("asOfPeriod"), DIM))
        pairs = [("P/E", val.get("pe")), ("P/B", val.get("pb")), ("P/S", val.get("ps")),
                 ("earnings yield", val.get("earnings_yield")),
                 ("EV/EBIT", val.get("ev_ebit"))]
        print("  " + "".join("%-16s %8s   " % (k, ("%.2f" % v) if v is not None else "-")
                             for k, v in pairs))
        if val.get("peCrossCheck"):
            col = GREEN if val["peCrossCheck"] == "agree" else YELLOW
            print(c("  P/E cross-check: market cap route %.2f vs price/EPS route %.2f - %s"
                    % (val["pe"], val["pe_from_eps"], val["peCrossCheck"]), col))
        if val.get("note"):
            print(c("  %s" % val["note"], DIM))
    elif val.get("unavailable"):
        print(c("\nvaluation: %s" % val["unavailable"], DIM))

    g = a.get("growth") or {}
    cagrs = [(k.replace("_cagr", ""), g[k]) for k in
             ("revenue_cagr", "net_profit_cagr", "ebit_cagr", "ocf_cagr")
             if g.get(k) is not None]
    if cagrs:
        print(c("\nCOMPOUND GROWTH", BOLD) + c("  (%s to %s)" % (g.get("from"), g.get("to")), DIM))
        print("  " + "".join("%-14s %+8.2f%%   " % (k, v) for k, v in cagrs))

    v = a.get("verification") or {}
    if v.get("total"):
        ok = not v["failed"]
        print(c("\nconsistency audit: %d/%d accounting identities hold"
                % (v["passed"], v["total"]), GREEN if ok else RED))
        for ck in v["failed"]:
            print(c("  FAILED %s: %s (%.0f vs %.0f)"
                    % (ck["period"], ck["check"], ck["lhs"], ck["rhs"]), RED))
        for ck in v.get("noted", []):
            print(c("  note %s: %s (%.0f vs %.0f) - %s"
                    % (ck["period"], ck["check"], ck["lhs"], ck["rhs"],
                       ck.get("note") or ""), DIM))
    cov = a.get("coverage") or {}
    if cov.get("missingSections"):
        print(c("missing statements: %s" % ", ".join(cov["missingSections"]), YELLOW))
    if show_all:
        print(c("available lines: %s" % json.dumps(cov.get("sections", {})), DIM))


# ------------------------------------------------------------------ commands
def cmd_analyse(args):
    doc = ingest.load_any(args.entity)
    if not doc:
        pub = S.available_public()
        priv = ingest.available_private()
        print("no statements for %r" % args.entity)
        print("public with statements (%d), e.g.: %s" % (len(pub), ", ".join(pub[:10])))
        if priv:
            print("private on file: %s" % ", ".join(priv))
        return 1
    a = S.analyse(doc)
    print_analysis(a, show_all=args.verbose)
    if args.explain:
        if not analyst.available():
            print(c("\n[explain unavailable] set ANTHROPIC_API_KEY to enable the "
                    "language layer; the analysis above needs no credentials.", YELLOW))
            return 0
        print(c("\nANALYST NOTE", BOLD))
        try:
            print(textwrap.fill(analyst.explain(a, question=args.question,
                                                effort=args.effort), 88))
        except analyst.AnalystUnavailable as e:
            print(c("  unavailable: %s" % e, YELLOW))
    return 0


def cmd_ingest(args):
    if args.read_with_claude:
        if not analyst.available():
            print(c("--read-with-claude needs ANTHROPIC_API_KEY", YELLOW))
            return 1
        print("reading %s with Claude..." % os.path.basename(args.path))
        doc, report = analyst.extract_document(args.path, name=args.name,
                                               effort=args.effort)
        print(c("transcribed %d lines (%d mapped, %d unrecognised)"
                % (report["linesTranscribed"], report["linesMapped"],
                   report["linesUnmapped"]), DIM))
        if report.get("units"):
            print(c("figures stated in: %s" % report["units"], DIM))
        if report.get("modelNotes"):
            print(c("notes: %s" % report["modelNotes"], DIM))
    else:
        try:
            doc = ingest.ingest(args.path, name=args.name, currency=args.currency,
                                sector=args.sector, country=args.country)
        except (ValueError, RuntimeError) as e:
            print(c("could not parse %s: %s" % (os.path.basename(args.path), e), RED))
            if args.path.lower().endswith(".pdf"):
                print("try --read-with-claude for a scanned or awkwardly laid-out PDF")
            return 1

    a = S.analyse(doc)
    print_analysis(a, show_all=args.verbose)
    if doc.get("unmapped"):
        print(c("\n%d line(s) kept but not mapped to a standard item:"
                % len(doc["unmapped"]), DIM))
        for u in doc["unmapped"][:6]:
            print(c("  %s" % (u.get("label") if isinstance(u, dict) else u), DIM))
    dropped = doc.get("droppedOutOfScale") or []
    if dropped:
        print(c("\n%d line(s) dropped as out of scale for this statement "
                "(most likely note references, not money):" % len(dropped), YELLOW))
        for d in dropped:
            print(c("  %s.%s = %s (document median figure %s)"
                    % (d["section"], d["item"], d["values"], int(d["medianFigure"])), DIM))
    if args.explain and analyst.available():
        print(c("\nANALYST NOTE", BOLD))
        print(textwrap.fill(analyst.explain(a, effort=args.effort), 88))
    if args.save:
        print("\nsaved:", ingest.save(doc))
    return 0


def _load_signals():
    p = os.path.join(SD, "bot_signals.json")
    if not os.path.exists(p):
        print("no bot_signals.json - run: python market_bot.py")
        return None
    return json.load(open(p, encoding="utf-8"))


def cmd_brief(args):
    d = _load_signals()
    if not d:
        return 1
    if not analyst.available():
        print(c("the brief needs ANTHROPIC_API_KEY (or `ant auth login`). "
                "market_bot.py's own brief needs no credentials.", YELLOW))
        return 1
    statep = os.path.join(SD, "bot_market_state.json")
    state = json.load(open(statep, encoding="utf-8")) if os.path.exists(statep) else None
    print(c("\nMUTXRI MARKET BRIEF", BOLD))
    try:
        print(textwrap.fill(analyst.market_brief(d["signals"], d.get("digest"), state,
                                                 top=args.top, effort=args.effort), 88))
    except analyst.AnalystUnavailable as e:
        print(c("unavailable: %s" % e, YELLOW))
        return 1
    return 0


def cmd_ask(args):
    if not analyst.available():
        print(c("ask needs ANTHROPIC_API_KEY (or `ant auth login`)", YELLOW))
        return 1
    ctx = {}
    d = _load_signals()
    if d:
        ctx["digest"] = d.get("digest")
        ctx["signals"] = d["signals"][:40]
    statep = os.path.join(SD, "bot_market_state.json")
    if os.path.exists(statep):
        ctx["marketState"] = json.load(open(statep, encoding="utf-8"))
    for ent in args.entity or []:
        doc = ingest.load_any(ent)
        if doc:
            ctx.setdefault("companies", []).append(S.analyse(doc))
    try:
        print(textwrap.fill(analyst.answer(args.question, ctx, effort=args.effort), 88))
    except analyst.AnalystUnavailable as e:
        print(c("unavailable: %s" % e, YELLOW))
        return 1
    return 0


def _print_draft(d):
    col = {"pending": YELLOW, "approved": CYAN, "published": GREEN,
           "blocked": RED, "rejected": DIM}.get(d["status"], DIM)
    print("%s %s %s" % (c(d["id"], BOLD), c("[%s]" % d["status"], col),
                        c("%s %d/%d chars" % (d["platform"],
                                              social.post_length(d["text"], d["platform"]),
                                              social.LIMITS.get(d["platform"], 280)), DIM)))
    print("  " + d["text"].replace("\n", "\n  "))
    for p in d["screen"]["problems"]:
        print(c("  ! %s" % p, RED))
    m = d.get("media")
    if m:
        mono = ((m.get("provenance") or {}).get("notes") or [])
        print(c("  card: %s" % m["path"], CYAN))
        for cr in (m.get("credits") or []):
            print(c("        image: %s" % cr, DIM))
        for note in mono:
            print(c("        %s" % note, DIM))
        for r in ((m.get("provenance") or {}).get("refused") or []):
            print(c("        REFUSED %s of %s (%s)" % (r["what"], r["subject"], r["why"]), RED))
    if d.get("publishedId"):
        print(c("  published as %s at %s" % (d["publishedId"], d["publishedAt"]), DIM))
    if d.get("error"):
        print(c("  last error: %s" % d["error"], RED))



CARD_DIR = os.path.join(SD, "cards")


def _person_args(specs):
    """--person \"Name:Role\" pairs into the shape cards.build_for_story wants."""
    out = []
    for spec in specs or []:
        name, _, role = spec.partition(":")
        if name.strip():
            out.append({"name": name.strip(), "role": role.strip() or None})
    return out


def _print_provenance(prov):
    lg = prov.get("logo")
    if lg:
        print(c("  logo    %-28s %s" % ((lg.get("subject") or "")[:28],
                                        lg.get("licence") or "licence not stated"),
                DIM if lg.get("reuse") in ("permitted", "attribution") else YELLOW))
    for p in prov.get("people", []):
        if p.get("found"):
            warn = " (VERIFY: may not be a portrait)" if p.get("needsVisualCheck") else ""
            print(c("  photo   %-28s %s conf %.2f%s"
                    % (p["name"][:28], p.get("licence"), p.get("confidence") or 0, warn),
                    YELLOW if p.get("needsVisualCheck") else GREEN))
            if p.get("source"):
                print(c("          %s" % p["source"], DIM))
        else:
            print(c("  no photo %-27s %s -> shown as initials"
                    % (p["name"][:27], p.get("reason")), DIM))
    for r in prov.get("refused", []):
        print(c("  REFUSED %s of %s: %s (%s)"
                % (r["what"], r["subject"], r["why"], r.get("licence") or "no licence"),
                RED))
    for n in prov.get("notes", []):
        print(c("  note: %s" % n, DIM))


def _build_card(plan, out_path, allow_unlicensed=False):
    res, prov = cards.build_for_story(
        plan["headline"], out_path,
        company=plan.get("company"), ticker=plan.get("ticker"),
        exchange=plan.get("exchange"), people=plan.get("people"),
        eyebrow=plan.get("eyebrow"), source=plan.get("source"),
        date=plan.get("date"), allow_unlicensed=allow_unlicensed)
    return res, prov


def cmd_card(args):
    os.makedirs(CARD_DIR, exist_ok=True)
    if args.signal is not None:
        d = _load_signals()
        if not d:
            return 1
        sigs = d["signals"]
        if args.signal >= len(sigs):
            print("only %d signals available" % len(sigs))
            return 1
        sig = sigs[args.signal]
        plan = cards.plan_from_signal(sig, use_model=not args.no_model)
        plan["date"] = None
        print(c("story read by %s (confidence %s)" % (plan["readBy"], plan["confidence"]), DIM))
        if plan.get("modelError"):
            print(c("  model unavailable: %s" % plan["modelError"], DIM))
    else:
        if not args.headline:
            print("give --headline (and optionally --company/--person), or --signal N")
            return 1
        plan = {"headline": args.headline, "company": args.company,
                "ticker": args.ticker, "exchange": args.exchange,
                "people": _person_args(args.person), "eyebrow": args.eyebrow,
                "source": args.source, "date": args.date,
                "readBy": "manual", "confidence": "high"}

    print(c("\nheadline: %s" % plan["headline"], BOLD))
    print("company: %s   people: %s"
          % (plan.get("company") or "-",
             ", ".join(p["name"] for p in plan.get("people") or []) or "none"))
    out = args.out or os.path.join(CARD_DIR, "card_%s.png" % (
        re.sub(r"[^A-Za-z0-9]+", "_", (plan.get("company") or plan["headline"])[:40]).strip("_").lower()))
    print(c("\nresolving images...", DIM))
    res, prov = _build_card(plan, out, allow_unlicensed=args.allow_unlicensed)
    _print_provenance(prov)
    print(c("\ncard: %s (%d bytes)" % (res["path"], res["bytes"]), GREEN))

    if args.draft:
        text = plan["headline"]
        if plan.get("exchange"):
            text = "%s: %s" % (plan["exchange"], text)
        draft = social.draft_from_signal(
            {"title": plan["headline"], "exchange": plan.get("exchange") or "",
             "securities": [{"ticker": plan.get("ticker")}] if plan.get("ticker") else [],
             "themes": [], "url": args.link or "", "publisher": plan.get("source")},
            platform=args.platform) if plan.get("exchange") else social._make_draft(
            text, args.platform, kind="card", grounding=plan)
        alt = social.card_alt_text(plan["headline"], plan.get("company"),
                                   plan.get("people"), res["monograms"])
        social.attach_card(draft, res["path"], credits=res["credits"],
                           alt_text=alt, provenance=prov)
        added = social.enqueue([draft])
        if added:
            print(c("\nqueued draft %s with the card attached" % added[0]["id"], GREEN))
            _print_draft(added[0])
        else:
            print(c("an identical draft is already queued", DIM))
    return 0


def _fmt(v, suffix=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        return ("%.2f%s" % (v, suffix)) if abs(v) < 1000 else ("%,.0f" % v).replace(",", ",")
    return "%s%s" % (v, suffix)


def cmd_screen(args):
    from bot import screen as SC
    conds = []
    for expr in args.where or []:
        try:
            conds.append(SC.parse_condition(expr))
        except ValueError as e:
            print(c(str(e), RED))
            return 1
    companies = SC.load(rebuild=args.rebuild, verbose=not args.quiet)

    if args.list_flags:
        print(c("flags present across %d companies:" % len(companies), BOLD))
        for f in SC.flag_counts(companies):
            print("  %-26s %-8s %4d   %s" % (f["id"], f["severity"], f["count"],
                                             f["label"]))
        return 0

    hits = SC.screen(companies, exchange=args.exchange, sector=args.sector,
                     flags=args.flag or (), severity=args.severity,
                     conditions=conds, require_all_flags=args.all_flags)
    cols = args.show or ["net_margin", "roe", "revenue_growth", "ocf_to_net_profit"]
    hits.sort(key=lambda x: (x["latest"].get(cols[0]) is None,
                             -(x["latest"].get(cols[0]) or 0)))
    print(c("\n%d of %d companies match" % (len(hits), len(companies)), BOLD))
    head = "%-12s %-30s %-4s " % ("TICKER", "NAME", "EX") + \
           " ".join("%14s" % col[:14] for col in cols) + "  FLAGS"
    print(c(head, DIM))
    for h in hits[:args.limit]:
        vals = " ".join("%14s" % _fmt(h["latest"].get(col)) for col in cols)
        fl = ",".join(f["id"] for f in h["flags"] if f["severity"] == "high")
        print("%-12s %-30s %-4s %s  %s"
              % (h["ticker"][:12], (h["name"] or "")[:30], h.get("exchange") or "-",
                 vals, c(fl[:40], RED) if fl else ""))
    if len(hits) > args.limit:
        print(c("  ... %d more (use --limit)" % (len(hits) - args.limit), DIM))
    return 0


def cmd_peers(args):
    from bot import screen as SC
    companies = SC.load(verbose=not args.quiet)
    p = SC.peers(companies, args.ticker, by=args.by)
    if not p:
        print(c("no statements for %s" % args.ticker, RED))
        return 1
    print(c("\n%s - %s" % (p["ticker"], p["name"]), BOLD))
    print(c("compared against %s (%d peers), latest period %s"
            % (p["group"], p["groupSize"], p["latestPeriod"] or "?"), DIM))
    if p.get("widened"):
        print(c("too few %s peers on this exchange - widened to all sectors"
                % (p.get("sector") or "sector"), YELLOW))
    print(c("\n%-20s %12s %12s %10s" % ("METRIC", "COMPANY", "PEER MEDIAN",
                                        "PERCENTILE"), DIM))
    for r in p["metrics"]:
        pct = "-"
        if r["percentile"] is not None:
            pct = "%.0f" % r["percentile"]
            if not r["reliable"]:
                pct += "*"
        col = GREEN if (r["percentile"] or 0) >= 60 else (
            RED if r["percentile"] is not None and r["percentile"] <= 25 else "")
        line = "%-20s %12s %12s %10s" % (r["metric"], _fmt(r["value"]),
                                         _fmt(r["peerMedian"]), pct)
        print(c(line, col) if col else line)
    if any(not r["reliable"] for r in p["metrics"] if r["percentile"] is not None):
        print(c("\n* fewer than %d peers - an ordering, not a measurement"
                % SC.MIN_PEERS, DIM))
    if p["flags"]:
        print(c("\nflags: %s" % ", ".join(f["id"] for f in p["flags"]), YELLOW))
    return 0


def cmd_watch(args):
    from bot import watch as W
    if args.watch_cmd == "add":
        wl = W.add(tickers=args.ticker or (), exchanges=args.exchange or (),
                   min_impact=args.min_impact)
        print("watching %d ticker(s), %d exchange(s), impact >= %.0f"
              % (len(wl["tickers"]), len(wl["exchanges"]), wl["minImpact"]))
        return 0
    if args.watch_cmd == "remove":
        wl = W.remove(tickers=args.ticker or (), exchanges=args.exchange or ())
        print("watching %d ticker(s), %d exchange(s)"
              % (len(wl["tickers"]), len(wl["exchanges"])))
        return 0
    if args.watch_cmd == "list":
        wl = W.watchlist()
        print("tickers  :", ", ".join(wl["tickers"]) or "(none)")
        print("exchanges:", ", ".join(wl["exchanges"]) or "(none)")
        print("min impact:", wl["minImpact"], "| flag severities:",
              ", ".join(wl["flagSeverities"]))
        return 0
    if args.watch_cmd == "reset":
        W.reset()
        print("seen-state cleared - the next check reports everything again")
        return 0

    res = W.check(record=not args.dry_run)
    if res.get("error"):
        print(c(res["error"], RED))
        print("e.g. python mutxri_ai.py watch add --ticker SCOM --ticker ABG.JO")
        return 1
    news, stmts = res["news"], res["statements"]
    if not news and not stmts:
        print(c("nothing new since the last check", DIM))
        if args.dry_run:
            print(c("(dry run - nothing was marked as reported)", DIM))
        return 0
    if news:
        print(c("\n%d NEW SIGNAL(S)" % len(news), BOLD))
        for n in news:
            print("  %s %-4s %-8s %s"
                  % (c("%5.1f" % n["impact"], CYAN), n["exchange"],
                     c(n["bias"], GREEN if n["bias"] == "bullish"
                       else (RED if n["bias"] == "bearish" else YELLOW)),
                     n["title"][:62]))
            print(c("        %s | %s | %s" % (n["why"], n["publisher"] or "",
                                              ", ".join(x for x in n["securities"] if x)),
                    DIM))
    if stmts:
        print(c("\n%d STATEMENT FLAG CHANGE(S)" % len(stmts), BOLD))
        for s in stmts:
            col = RED if s["change"] == "appeared" else GREEN
            print("  %s %-10s %-28s %s"
                  % (c(s["change"].upper()[:8].ljust(8), col), s["ticker"],
                     (s["name"] or "")[:28], s["label"]))
    if args.dry_run:
        print(c("\n(dry run - nothing was marked as reported)", DIM))
    return 0


def cmd_doctor(args):
    from bot import health as H
    r = H.report()
    icon = {"ok": GREEN, "ageing": YELLOW, "stale": RED, "missing": RED,
            "thin": YELLOW, "poor": RED, "degraded": YELLOW, "down": RED,
            "unreadable": RED}
    print(c("\nDATA HEALTH - %s" % r["overall"].upper(),
            GREEN if r["overall"] == "ok" else YELLOW))

    print(c("\nFILES", BOLD))
    for f in r["files"]:
        age = "%.1fd" % f["ageDays"] if f["ageDays"] is not None else "missing"
        line = "  %-26s %-9s %-9s %s" % (f["file"], f["status"], age, f["what"])
        print(c(line, icon.get(f["status"], "")))

    print(c("\nEXCHANGE COVERAGE", BOLD))
    for e in r["coverage"]:
        if e.get("securities"):
            line = ("  %-5s %3d securities, %3d priced (%.0f%%), %d suspect row(s)"
                    % (e["exchange"], e["securities"], e["priced"], e["pricedPct"],
                       e["suspectRows"]))
        else:
            line = "  %-5s no data" % e["exchange"]
        print(c(line, icon.get(e["status"], "")))

    st, sr = r["statements"], r["sources"]
    print(c("\nSTATEMENTS", BOLD))
    print("  %d tickers with parsed statements (%d in the index)"
          % (st["tickersWithStatements"], st["indexEntries"]))

    print(c("\nNEWS SOURCES", BOLD))
    if sr.get("sourcesOk") is not None:
        print(c("  %d ok, %d failed | %s signals | scanned %s"
                % (sr["sourcesOk"], sr["sourcesFailed"], sr.get("signals"),
                   sr.get("generated")), icon.get(sr["status"], "")))
        for f in sr.get("failures", [])[:6]:
            print(c("    down: %s (%s)" % (f["source"], f["error"]), DIM))
        if sr.get("social") and sr["social"] != "ok":
            print(c("    social tier: %s" % sr["social"], DIM))
    else:
        print(c("  %s" % sr.get("detail", sr.get("status")), RED))

    print(c("\nCAPABILITIES", BOLD))
    for cap in r["credentials"]:
        mark = "on " if cap["enabled"] else "off"
        print(c("  %-3s %-48s %s" % (mark, cap["capability"], cap["env"]),
                GREEN if cap["enabled"] else DIM))
    return 0 if r["overall"] == "ok" else 0


def cmd_selftest(args):
    from bot import selftest
    rep = selftest.run()
    groups = {}
    for r in rep["results"]:
        groups.setdefault(r["group"], []).append(r)
    for g, rows in groups.items():
        ok = sum(1 for r in rows if r["ok"])
        print(c("\n%s  %d/%d" % (g.upper(), ok, len(rows)),
                BOLD if ok == len(rows) else RED))
        for r in rows:
            if r["ok"] and not args.verbose:
                continue
            mark = c("PASS", GREEN) if r["ok"] else c("FAIL", RED)
            print("  %s %-44s got=%-14s want=%s" % (mark, r["name"], r["got"], r["expected"]))
            if not r["ok"]:
                print(c("       %s" % r["how"], DIM))
    col = GREEN if rep["ok"] else RED
    print(c("\n%d/%d checks passed" % (rep["passed"], rep["total"]), col))
    if not args.verbose and rep["ok"]:
        print(c("(--verbose to list every check)", DIM))
    return 0 if rep["ok"] else 1


def cmd_social(args):
    if args.action == "status":
        print("publishing credentials:")
        for k, v in social.credentials_status().items():
            print("  %-9s %s" % (k, c(v, GREEN if v == "ready" else YELLOW)))
        q = social.queue()
        counts = {}
        for d in q:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        print("queue: %s" % (", ".join("%s %d" % kv for kv in counts.items()) or "empty"))
        print(c("nothing publishes without an explicit approve + publish.", DIM))
        return 0

    if args.action == "draft":
        drafts = []
        if args.summary or not args.from_signals:
            d = _load_signals()
            if d:
                drafts.append(social.draft_market_summary(d.get("digest"),
                                                          platform=args.platform))
        if args.from_signals:
            d = _load_signals()
            if not d:
                return 1
            for s in d["signals"][:args.from_signals]:
                if args.analyst and analyst.available():
                    facts = {k: s.get(k) for k in
                             ("exchange", "title", "url", "publisher", "bias",
                              "impact", "securities", "themes")}
                    drafts.append(social.draft_with_analyst(
                        "Write a post reporting this market story.", facts,
                        platform=args.platform, effort=args.effort))
                else:
                    drafts.append(social.draft_from_signal(s, platform=args.platform))
        added = social.enqueue(drafts)
        print("queued %d draft(s) (%d already present)"
              % (len(added), len(drafts) - len(added)))
        for d in added:
            _print_draft(d)
        if added:
            print(c("\nreview, then: python mutxri_ai.py social approve <id> --by <you>",
                    DIM))
        return 0

    if args.action == "list":
        q = social.queue(args.status)
        if not q:
            print("queue empty" + (" for status %r" % args.status if args.status else ""))
            return 0
        for d in q:
            _print_draft(d)
            print()
        return 0

    if args.action in ("approve", "reject"):
        if not args.by:
            print("--by <name> is required: approvals are recorded against a person")
            return 1
        try:
            if args.action == "approve":
                d = social.approve(args.id, args.by)
                print(c("approved %s by %s" % (d["id"], args.by), GREEN))
                print(c("not yet posted - publish with: "
                        "python mutxri_ai.py social publish %s --by %s"
                        % (d["id"], args.by), DIM))
            else:
                d = social.reject(args.id, args.by, args.reason or "")
                print(c("rejected %s" % args.id, DIM))
        except (KeyError, ValueError) as e:
            print(c(str(e), RED))
            return 1
        return 0

    if args.action == "publish":
        if not args.by:
            print("--by <name> is required: publications are recorded against a person")
            return 1
        d = social.get(args.id)
        if not d:
            print(c("no draft %s" % args.id, RED))
            return 1
        print(c("\nAbout to post publicly as MUTXRI on %s:" % d["platform"], BOLD))
        _print_draft(d)
        # Explicit human confirmation at the moment of publishing. --yes exists
        # for a person running this non-interactively; there is deliberately no
        # scheduled caller of this command.
        if args.yes:
            confirmed = True
            print(c("confirmed via --yes by %s" % args.by, DIM))
        else:
            try:
                confirmed = input("\ntype PUBLISH to post this: ").strip() == "PUBLISH"
            except EOFError:
                confirmed = False
        if not confirmed:
            print("cancelled - nothing was posted")
            return 1
        try:
            d = social.publish(args.id, args.by, confirmed=True)
        except (KeyError, ValueError, RuntimeError) as e:
            print(c("not published: %s" % e, RED))
            return 1
        print(c("published as %s" % d["publishedId"], GREEN))
        return 0
    return 1


def main():
    ap = argparse.ArgumentParser(
        description="MUTXRI analyst - statements, explanation, drafting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--effort", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"],
                    help="how hard the model works (default high)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyse", help="analyse a company's statements")
    p.add_argument("entity", help="ticker (ABG.JO, SCOM) or a saved private entity id")
    p.add_argument("--explain", action="store_true", help="add Claude's analyst note")
    p.add_argument("--question", help="ask something specific about this company")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_analyse)

    p = sub.add_parser("ingest", help="read a private company's statements")
    p.add_argument("path", help="CSV, XLSX, JSON or PDF")
    p.add_argument("--name", help="company name")
    p.add_argument("--currency")
    p.add_argument("--sector")
    p.add_argument("--country")
    p.add_argument("--save", action="store_true", help="keep for later runs")
    p.add_argument("--explain", action="store_true")
    p.add_argument("--read-with-claude", action="store_true",
                   help="use the model to transcribe an awkward or scanned document")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("brief", help="narrative market brief over the latest scan")
    p.add_argument("--top", type=int, default=12)
    p.set_defaults(fn=cmd_brief)

    p = sub.add_parser("ask", help="ask a question grounded in terminal data")
    p.add_argument("question")
    p.add_argument("--entity", action="append", help="include a company's analysis")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("screen", help="screen every parsed statement at once")
    p.add_argument("--exchange")
    p.add_argument("--sector", help="substring match, e.g. bank")
    p.add_argument("--flag", action="append",
                   help="repeatable; matches any unless --all-flags")
    p.add_argument("--all-flags", action="store_true",
                   help="require every --flag rather than any")
    p.add_argument("--severity", choices=["high", "medium", "low"])
    p.add_argument("--where", action="append", metavar="EXPR",
                   help='repeatable metric test, e.g. --where "roe>15"')
    p.add_argument("--show", action="append", metavar="METRIC",
                   help="columns to display (repeatable)")
    p.add_argument("--list-flags", action="store_true",
                   help="show every flag and how many companies carry it")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--rebuild", action="store_true", help="force a corpus rebuild")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_screen)

    p = sub.add_parser("peers", help="rank a company against its sector")
    p.add_argument("ticker")
    p.add_argument("--by", choices=["sector", "exchange"], default="sector")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_peers)

    p = sub.add_parser("watch", help="alert on what is new for your holdings")
    w = p.add_subparsers(dest="watch_cmd")
    wa = w.add_parser("add", help="add tickers or exchanges to the watchlist")
    wa.add_argument("--ticker", action="append")
    wa.add_argument("--exchange", action="append")
    wa.add_argument("--min-impact", type=float)
    wr = w.add_parser("remove", help="stop watching")
    wr.add_argument("--ticker", action="append")
    wr.add_argument("--exchange", action="append")
    w.add_parser("list", help="show the watchlist")
    w.add_parser("reset", help="forget what has already been reported")
    wc = w.add_parser("check", help="report what is new since the last check")
    wc.add_argument("--dry-run", action="store_true",
                    help="preview without marking anything as reported")
    p.set_defaults(fn=cmd_watch, watch_cmd="check", dry_run=False,
                   ticker=None, exchange=None, min_impact=None)

    p = sub.add_parser("doctor", help="data freshness, coverage and capabilities")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("selftest", help="verify every financial formula against worked examples")
    p.add_argument("--verbose", action="store_true", help="list every check, not just failures")
    p.set_defaults(fn=cmd_selftest)

    p = sub.add_parser("card", help="build a social card from real, licensed images")
    p.add_argument("--signal", type=int, help="build from signal N of the last scan")
    p.add_argument("--headline")
    p.add_argument("--company")
    p.add_argument("--ticker")
    p.add_argument("--exchange")
    p.add_argument("--person", action="append", metavar="NAME:ROLE",
                   help='repeatable, e.g. --person "Jane Mwangi:Incoming director"')
    p.add_argument("--eyebrow", help="small label above the headline")
    p.add_argument("--source", help="publication the story came from")
    p.add_argument("--date")
    p.add_argument("--link", help="URL to include in the drafted post")
    p.add_argument("--out", help="output PNG path")
    p.add_argument("--draft", action="store_true", help="queue a post with this card")
    p.add_argument("--platform", default="x", choices=sorted(social.LIMITS))
    p.add_argument("--no-model", action="store_true",
                   help="use the heuristic story reader even if a key is set")
    p.add_argument("--allow-unlicensed", action="store_true",
                   help="permit images whose licence could not be established "
                        "(you take responsibility for clearing them)")
    p.set_defaults(fn=cmd_card)

    p = sub.add_parser("social", help="draft, review and publish posts")
    p.add_argument("action",
                   choices=["draft", "list", "approve", "reject", "publish", "status"])
    p.add_argument("id", nargs="?", help="draft id, for approve/reject/publish")
    p.add_argument("--from-signals", type=int, default=0,
                   help="draft from the top N news signals")
    p.add_argument("--summary", action="store_true", help="draft the market summary")
    p.add_argument("--analyst", action="store_true",
                   help="have Claude write the drafts instead of the template")
    p.add_argument("--platform", default="x", choices=sorted(social.LIMITS))
    p.add_argument("--status", help="filter list by status")
    p.add_argument("--by", help="who is approving or publishing (recorded)")
    p.add_argument("--reason", help="why a draft was rejected")
    p.add_argument("--yes", action="store_true",
                   help="skip the interactive confirmation (still records --by)")
    p.set_defaults(fn=cmd_social)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
