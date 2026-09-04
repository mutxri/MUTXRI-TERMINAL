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

from bot import analyst, cards, images, ingest, social, statements as S

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
            print(c("  %s" % (u.get("label") or u), DIM))
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
