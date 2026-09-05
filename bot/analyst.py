#!/usr/bin/env python3
"""bot/analyst.py - the language layer: reading documents and explaining numbers.

The division of labour in this package is deliberate and load-bearing:

    bot/statements.py   computes every number (margins, growth, leverage, flags)
    bot/analyst.py      reads documents and explains what the numbers mean

A language model is excellent at reading a badly-formatted annual report and at
saying why a set of ratios is worrying. It is the wrong tool for arithmetic on a
balance sheet. So nothing here calculates a metric: extraction results are handed
straight back to bot/statements.py, which recomputes everything and runs the
accounting-identity audit (assets = liabilities + equity, and so on). If the model
misread a digit, that audit fails and the caller is told - rather than a confident
wrong ratio reaching a user.

Every explanation is grounded in figures supplied in the prompt. The model is told
to work only from those numbers, to say when something is missing, and never to
give personalised investment advice - MUTXRI is a data terminal, not an adviser.

Requires an API credential (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an
`ant auth login` profile) and the `anthropic` package.
"""
import base64, json, os, textwrap

MODEL = "claude-opus-5"

SYSTEM = """You are the MUTXRI TERMINAL analyst. MUTXRI covers four African \
exchanges: the Nairobi Securities Exchange (NSE, Kenya), the Nigerian Exchange \
(NGX), the Johannesburg Stock Exchange (JSE, South Africa) and the Egyptian \
Exchange (EGX).

How you work:

- Work only from the figures given to you in the prompt. They were computed \
deterministically from filed statements; treat them as the facts of the matter.
- Never calculate, re-derive or estimate a financial metric yourself. If a number \
you want is not supplied, say it is not available rather than inferring it.
- When data is missing, partial, or the periods have gaps, say so plainly. An \
honest "the cash flow statement was not available" beats a confident guess. This \
is a house rule at MUTXRI: an empty field is always better than a fabricated one.
- Distinguish what the numbers show from what might explain them. Label inference \
as inference.
- Be concrete and quantitative. Cite the actual figures and periods you are \
reasoning from.
- Write plainly, in the register of a professional analyst briefing a colleague. \
No hype, no filler, no bullet-point padding.
- You do not give personalised investment advice and you never tell anyone to buy \
or sell a security. You describe financial condition and what would need to be \
true for it to improve or deteriorate. If asked for a recommendation, explain \
what the figures show and leave the decision to the reader.

What the supplied metrics mean. Every one is computed in Python from filed \
figures and checked against worked examples; you interpret them, you never \
recompute them.

- net margin = net profit / revenue. gross and EBIT margins likewise.
- ROE = net profit / shareholders' equity. Withheld when equity is negative, \
because the ratio then inverts and reads as a strong return on a wrecked \
balance sheet.
- DuPont: ROE = net margin x asset turnover x equity multiplier. Use it to say \
where a return comes from. A bank and a retailer can print the same ROE from \
opposite sources: thin margin and heavy leverage, or fat margin and low gearing.
- ROCE = EBIT / capital employed, and ROIC = after-tax EBIT / capital employed. \
These are the return on the money in the business, and unlike ROE they are not \
flattered by borrowing. Check capital_employed_basis before comparing two \
companies: "assets less current liabilities" and "equity plus debt" are \
different bases.
- P/E = market capitalisation / net profit, cross-checked against price / EPS. \
When peCrossCheck does not say "agree", treat the multiple as unreliable and say \
so. P/E is withheld for a loss-making company, where it is not a valuation.
- Valuation ratios pair a current market capitalisation with the latest \
reported period, and only that period. Never describe a P/E as belonging to an \
earlier year.
- CAGR is compounded over the contiguous years named in the growth block. It is \
withheld when either endpoint is negative, because there is no compound rate \
from a loss to a profit, only a change of sign.
- interest cover = EBIT / net finance costs. Below about 2 the company is \
working for its lenders.
- ocf_to_net_profit is cash conversion. Persistently under 1 means profit is not \
arriving as cash, and that is a question about receivables and revenue \
recognition, not a verdict.
- ebit_derived = true means EBIT was not reported and was rebuilt as PBT plus \
net finance costs. Say so if you lean on it.

Two habits that matter. A ratio without a comparison is close to meaningless, so \
reach for the peer median or the company's own history rather than calling a \
number good or bad on its own. And a flag is a prompt for scrutiny, not a \
verdict: one year of weak cash conversion can be working-capital timing."""


class AnalystUnavailable(RuntimeError):
    """Raised when the LLM layer cannot run (missing package or credentials)."""


def _client():
    try:
        import anthropic
    except ImportError:
        raise AnalystUnavailable(
            "the 'anthropic' package is not installed - pip install anthropic")
    try:
        return anthropic.Anthropic()
    except Exception as e:
        raise AnalystUnavailable(
            "could not create an Anthropic client (%s). Set ANTHROPIC_API_KEY, or "
            "run `ant auth login`." % type(e).__name__)


def available():
    """True when the language layer can actually run.

    The SDK client constructs fine with no credentials and only fails at request
    time, so checking that the constructor succeeded is not enough - it would
    report the feature as available and then fail confusingly mid-command.
    A resolved api_key or auth_token is the real test.
    """
    try:
        c = _client()
    except AnalystUnavailable:
        return False
    return bool(getattr(c, "api_key", None) or getattr(c, "auth_token", None))


def _describe_error(e):
    """Turn an SDK exception into something a terminal user can act on."""
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "authentication failed - check ANTHROPIC_API_KEY"
    if isinstance(e, anthropic.PermissionDeniedError):
        return "the API key lacks permission for this request"
    if isinstance(e, anthropic.NotFoundError):
        return "model or endpoint not found (%s)" % MODEL
    if isinstance(e, anthropic.RateLimitError):
        retry = e.response.headers.get("retry-after", "60") if e.response else "60"
        return "rate limited - retry after %ss" % retry
    if isinstance(e, anthropic.APIStatusError):
        return "API error %s: %s" % (e.status_code, e.message)
    if isinstance(e, anthropic.APIConnectionError):
        return "could not reach the API - check the network"
    return "%s: %s" % (type(e).__name__, e)


def _text(msg):
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def ask(prompt, *, effort="high", max_tokens=16000, stream=True,
        system=SYSTEM, content=None):
    """One grounded request to Claude.

    The system prompt is cached: it is identical on every call, so after the first
    request it is served from cache rather than re-billed as fresh input.
    Streaming is the default because analysis responses can be long, and a long
    non-streaming request risks an HTTP timeout.
    """
    import anthropic
    client = _client()
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": content or prompt}],
    )
    try:
        if stream:
            with client.messages.stream(**kwargs) as s:
                msg = s.get_final_message()
        else:
            msg = client.messages.create(**kwargs)
    except Exception as e:
        raise AnalystUnavailable(_describe_error(e))
    if msg.stop_reason == "refusal":
        detail = getattr(msg, "stop_details", None)
        raise AnalystUnavailable(
            "the model declined this request%s"
            % (" (%s)" % detail.category if detail and detail.category else ""))
    return _text(msg)


# ------------------------------------------------------- explaining a company
def _facts_block(analysis, max_periods=5):
    """Render computed metrics as the factual ground for the model."""
    e = analysis["entity"]
    lines = ["ENTITY: %s (%s)" % (e.get("name"), e.get("kind", "public"))]
    for k in ("ticker", "exchange", "currency", "sector", "country"):
        if e.get(k):
            lines.append("%s: %s" % (k.upper(), e[k]))
    src = analysis.get("source") or {}
    if src:
        lines.append("SOURCE: %s %s" % (src.get("kind", "?"), src.get("detail") or ""))

    lines.append("\nPER-PERIOD FIGURES (newest first; null = not available):")
    fields = ["period", "revenue", "net_profit", "ebit", "total_assets",
              "total_equity", "borrowings", "ocf", "capex", "fcf",
              "gross_margin", "ebit_margin", "net_margin", "roe", "roa",
              "debt_to_equity", "net_debt_to_equity", "current_ratio",
              "interest_cover", "ocf_to_net_profit",
              "revenue_growth", "net_profit_growth", "ocf_growth",
              "yearsSincePrior"]
    for r in analysis["metrics"][:max_periods]:
        lines.append("  " + json.dumps({k: r.get(k) for k in fields}))

    cov = analysis.get("coverage") or {}
    if cov.get("missingSections"):
        lines.append("\nMISSING STATEMENTS: " + ", ".join(cov["missingSections"]))
    if cov.get("nonContiguousAfter"):
        lines.append("PERIOD GAPS AFTER: " + ", ".join(cov["nonContiguousAfter"])
                     + "  (growth vs a non-adjacent year is not computed)")

    if analysis.get("flags"):
        lines.append("\nCOMPUTED WARNINGS:")
        for f in analysis["flags"]:
            lines.append("  [%s] %s - %s" % (f["severity"], f["label"], f["detail"]))

    v = analysis.get("verification") or {}
    if v.get("total"):
        lines.append("\nCONSISTENCY AUDIT: %d/%d accounting identities hold."
                     % (v["passed"], v["total"]))
        for c in v.get("failed", []):
            lines.append("  FAILED %s: %s (%.0f vs %.0f) - the underlying figures "
                         "disagree; treat ratios built on them with caution."
                         % (c["period"], c["check"], c["lhs"], c["rhs"]))
        for c in v.get("noted", []):
            lines.append("  NOTE %s: %s (%.0f vs %.0f) - %s. Not necessarily an "
                         "error." % (c["period"], c["check"], c["lhs"], c["rhs"],
                                     c.get("note") or "difference unexplained"))
    return "\n".join(lines)


def explain(analysis, question=None, effort="high"):
    """Narrative read of one company's financial condition."""
    task = question or (
        "Write a short analyst note on this company's financial condition. Cover: "
        "how the business performed across the periods shown, what is driving the "
        "direction of travel, the quality of earnings (how profit compares with "
        "operating cash), the balance sheet and any funding pressure, and what "
        "would have to change for the picture to improve. Note explicitly where "
        "data is missing. Around 250-350 words, no headings.")
    prompt = ("%s\n\nFACTS (computed from filed statements - do not recalculate):\n"
              "%s\n\nTASK: %s" % (
                  "Analyse the company below.", _facts_block(analysis), task))
    return ask(prompt, effort=effort)


# ------------------------------------------- model-assisted PDF extraction
_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_name": {"type": "string"},
        "currency": {"type": "string"},
        "units": {
            "type": "string",
            "description": "Scale the figures are stated in, exactly as the "
                           "document says: 'units', 'thousands', 'millions'.",
        },
        "periods": {
            "type": "array",
            "description": "Fiscal period labels, NEWEST FIRST, e.g. ['FY2026','FY2025'].",
            "items": {"type": "string"},
        },
        "lines": {
            "type": "array",
            "description": "One entry per statement line found.",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string",
                                "enum": ["income", "balance", "cashflow"]},
                    "label": {"type": "string",
                              "description": "The label exactly as printed."},
                    "values": {
                        "type": "array",
                        "description": "Values aligned to `periods`, same order and "
                                       "length. Use null where the document has no "
                                       "figure. Negatives (including figures shown "
                                       "in brackets) must be negative numbers.",
                        "items": {"type": ["number", "null"]},
                    },
                },
                "required": ["section", "label", "values"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string",
                  "description": "Anything ambiguous or unreadable in the document."},
    },
    "required": ["entity_name", "currency", "units", "periods", "lines", "notes"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """You transcribe financial statements from documents into \
structured data for the MUTXRI TERMINAL.

You are transcribing, not analysing. Rules:

- Copy figures exactly as printed. Do not compute, derive, total or reconcile \
anything - if a subtotal is not printed in the document, leave it out.
- A figure in brackets, or with a minus sign, is negative.
- Keep the label exactly as the document prints it.
- Align every `values` array to `periods`, in the same order and the same length. \
Use null where a line has no figure for a period.
- Report the scale as printed ("KES '000" means thousands). Do NOT rescale the \
numbers - transcribe the digits as shown and report the scale separately.
- If a page is unreadable or a figure is ambiguous, leave it null and say so in \
`notes`. Never guess a digit."""


def extract_document(path, name=None, max_pages=40, effort="high"):
    """Read a statement document with Claude, then verify it deterministically.

    Used when the deterministic readers in bot/ingest.py cannot parse a PDF -
    scanned pages, multi-column layouts, statements split across pages. The model
    transcribes; bot/statements.py recomputes every metric and runs the accounting
    -identity audit. Returns (doc, report) where report carries the audit result
    and the model's own notes, so a failed identity is visible to the caller.
    """
    from . import statements as S

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        content = [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": data}},
            {"type": "text", "text":
                "Transcribe every income statement, balance sheet and cash flow "
                "line in this document into the required structure."},
        ]
    else:
        from . import ingest as I
        raw = I.pdf_text(path, max_pages) if ext == ".pdf" else open(
            path, encoding="utf-8", errors="replace").read()
        content = [{"type": "text", "text":
                    "Transcribe the statements in this document.\n\n" + raw[:200000]}]

    import anthropic
    client = _client()
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=[{"type": "text", "text": EXTRACT_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema",
                                      "schema": _EXTRACT_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        ) as s:
            msg = s.get_final_message()
    except Exception as e:
        raise AnalystUnavailable(_describe_error(e))
    if msg.stop_reason == "refusal":
        raise AnalystUnavailable("the model declined to transcribe this document")

    payload = json.loads(_text(msg))

    # Regroup the transcribed lines into the canonical document shape. The
    # mapping to canonical keys is done here, in code, from the printed labels.
    sections, unmapped = {}, []
    for line in payload.get("lines", []):
        sec = line.get("section")
        if sec not in S.SECTION_MAPS:
            continue
        key = S._canon(line.get("label"), S.SECTION_MAPS[sec])
        vals = [S._num(v) for v in (line.get("values") or [])]
        if key is None:
            unmapped.append({"section": sec, "label": line.get("label"),
                             "values": vals})
            continue
        sections.setdefault(sec, {}).setdefault(key, vals)

    doc = {
        "entity": {
            "id": (name or payload.get("entity_name") or "entity").upper()
                  .replace(" ", "-"),
            "name": name or payload.get("entity_name"),
            "kind": "private",
            "currency": payload.get("currency"),
        },
        "periods": payload.get("periods") or [],
        "sections": sections,
        "unmapped": unmapped,
        "source": {"kind": "model-transcribed", "detail": os.path.basename(path),
                   "units": payload.get("units"), "model": MODEL,
                   "notes": payload.get("notes")},
    }
    report = {
        "units": payload.get("units"),
        "modelNotes": payload.get("notes"),
        "linesTranscribed": len(payload.get("lines", [])),
        "linesMapped": sum(len(v) for v in sections.values()),
        "linesUnmapped": len(unmapped),
        "verification": S.verify(doc),
    }
    return doc, report


# ------------------------------------------------- reading a story's entities
_STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": ["string", "null"],
                    "description": "The listed company the story is about, as "
                                   "normally written. Null if the story is macro."},
        "event_type": {
            "type": "string",
            "enum": ["appointment", "results", "dividend", "deal", "regulatory",
                     "listing", "macro", "other"],
        },
        "people": {
            "type": "array",
            "description": "People the story names, at most three, most central "
                           "first. Only people actually named in the text.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Full name exactly as written."},
                    "role": {"type": "string",
                             "description": "Their role per the story, e.g. "
                                            "'Incoming board member'. Short."},
                    "is_new_appointee": {"type": "boolean"},
                },
                "required": ["name", "role", "is_new_appointee"],
                "additionalProperties": False,
            },
        },
        "headline": {
            "type": "string",
            "description": "A factual headline for a card, at most 70 characters. "
                           "State what happened. No hype, no speculation, no "
                           "prediction, and nothing not present in the source.",
        },
        "confidence": {
            "type": "string", "enum": ["high", "medium", "low"],
            "description": "How certain you are that company and people are "
                           "correctly identified from the text alone.",
        },
    },
    "required": ["company", "event_type", "people", "headline", "confidence"],
    "additionalProperties": False,
}

STORY_SYSTEM = """You read financial news headlines for the MUTXRI TERMINAL and \
identify what the story is about, so the terminal can find the right pictures.

Rules:

- Name only people who actually appear in the text you are given. Never add a \
CEO, chairman or director from your own knowledge - the terminal will attach a \
photograph to whoever you name, and naming the wrong person puts a real face \
against a story they have nothing to do with.
- If the story names nobody, return an empty people list. That is a normal and \
correct answer.
- Give roles exactly as the story frames them.
- The headline must be supported by the source text alone. Do not add figures, \
outcomes or implications that are not there.
- Set confidence to low when the text is thin, ambiguous, or you are inferring \
the company rather than reading it."""


def read_story(title, summary="", effort="medium"):
    """Identify company, people and a factual headline from a news story.

    This is what lets a card be built automatically: the model reads who the story
    names, and bot/images.py then binds each name to a licensed photograph - or
    reports that none exists. The model is explicitly barred from supplying names
    from memory, because an invented name becomes a real face on a published card.
    """
    client = _client()
    text = (title or "").strip()
    if summary:
        text += "\n\n" + summary.strip()
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=4000,
            system=[{"type": "text", "text": STORY_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema",
                                      "schema": _STORY_SCHEMA}},
            messages=[{"role": "user", "content": "STORY:\n" + text[:8000]}],
        ) as s:
            msg = s.get_final_message()
    except Exception as e:
        raise AnalystUnavailable(_describe_error(e))
    if msg.stop_reason == "refusal":
        raise AnalystUnavailable("the model declined to read this story")
    return json.loads(_text(msg))


# ------------------------------------------------------------- market brief
def market_brief(signals, digest, state=None, top=12, effort="high"):
    """Narrative brief over the news signals and exchange state."""
    rows = []
    for s in signals[:top]:
        rows.append({
            "exchange": s["exchange"], "impact": s["impact"], "bias": s["bias"],
            "title": s["title"], "publisher": s["publisher"],
            "securities": [x.get("ticker") or x.get("name")
                           for x in s.get("securities", [])][:4],
            "themes": [t["label"] for t in s.get("themes", [])],
        })
    facts = ["EXCHANGE STATE (computed from the boards):"]
    for ex, d in (digest or {}).items():
        facts.append("  " + json.dumps(d))
    if state and state.get("crossAsset", {}).get("commodities"):
        facts.append("\nCOMMODITIES:")
        for c in state["crossAsset"]["commodities"][:8]:
            facts.append("  " + json.dumps({k: c.get(k) for k in
                                            ("name", "price", "chgPct", "africa")}))
    facts.append("\nTOP NEWS SIGNALS (impact = relevance x confidence, computed):")
    for r in rows:
        facts.append("  " + json.dumps(r))

    prompt = (
        "Write the MUTXRI morning market brief for the four exchanges.\n\n"
        + "\n".join(facts) +
        "\n\nTASK: A tight brief a trader reads before the open. Lead with what "
        "actually matters across the four markets, then a short paragraph per "
        "exchange that has something worth saying - tie the board's direction to "
        "the specific stories and securities above where there is a real link, and "
        "say so when there is not. Do not invent any figure that is not above. "
        "Around 300-400 words. No headings, no bullet lists.")
    return ask(prompt, effort=effort)


def answer(question, context, effort="high"):
    """Answer a question grounded in supplied terminal data."""
    prompt = ("Answer the question using only the MUTXRI data below.\n\n"
              "DATA:\n%s\n\nQUESTION: %s" % (
                  json.dumps(context, ensure_ascii=False, indent=1)[:120000],
                  question))
    return ask(prompt, effort=effort)


if __name__ == "__main__":
    import sys
    from . import statements as S
    if not available():
        print("LLM layer unavailable - set ANTHROPIC_API_KEY (or run `ant auth login`)")
        raise SystemExit(1)
    tick = sys.argv[1] if len(sys.argv) > 1 else "ABG.JO"
    doc = S.load_public(tick)
    if not doc:
        print("no statements for", tick)
        raise SystemExit(1)
    print(textwrap.fill(explain(S.analyse(doc)), 88))
