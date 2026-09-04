#!/usr/bin/env python3
"""bot/social.py - drafting posts, and publishing only what a human approved.

The bot writes posts. It does not decide to publish them.

Everything drafted here lands in a review queue on disk with status "pending".
Publishing is a separate, explicit act: a person names a draft id and confirms it.
There is no scheduled path from "the bot noticed something" to "it went out under
MUTXRI's name", and `refresh_all.py` never calls the publisher. That is a
deliberate constraint, not an oversight - a market account that posts unattended
can be wrong in public, at speed, about real companies, and a retraction never
travels as far as the original.

Three gates every post passes:

  1. GROUNDING  A draft is built from a signal or a computed analysis, and carries
                the source URL and the figures it came from. Nothing is drafted
                from thin air.
  2. SCREEN     Compliance screen: no buy/sell/target-price language, no promises
                about future prices, length limits per platform. A draft that
                fails is queued as "blocked" with the reason, and cannot publish.
  3. APPROVAL   A human approves a specific draft id. The approval, the approver
                and the published id are appended to an audit log.

Credentials: posting to X needs user-context OAuth 1.0a (X_API_KEY, X_API_SECRET,
X_ACCESS_TOKEN, X_ACCESS_SECRET) - the read-only bearer token used elsewhere in
this package cannot post. LinkedIn needs LINKEDIN_ACCESS_TOKEN and LINKEDIN_URN.
"""
import base64, datetime as dt, hashlib, hmac, json, os, re, textwrap, time
import urllib.parse, urllib.request, uuid

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(BASE, "static_data")
QUEUE_FILE = os.path.join(SD, "social_queue.json")
AUDIT_FILE = os.path.join(SD, "social_audit.log")

LIMITS = {"x": 280, "linkedin": 3000}

# Language that must never go out under a market-data brand. These are not style
# preferences: a post telling the public to buy or sell a named security, or
# promising a price, is advice, and MUTXRI publishes data.
BLOCKED_PATTERNS = [
    (r"\b(buy|sell|short|long)\s+(this|the\s+stock|now|today|\$?[A-Z]{2,10}\b)",
     "reads as a trade instruction"),
    (r"\b(price\s+target|target\s+price|pt\s*[:=]\s*\d)", "sets a price target"),
    (r"\b(guaranteed|risk[- ]free|can'?t lose|sure thing|will (?:double|triple|moon|soar))",
     "promises a return"),
    (r"\b(strong buy|table pounding|load up|all[- ]in|ape in)", "is a recommendation"),
    (r"\b(we (?:recommend|advise)|you should (?:buy|sell|invest))",
     "gives investment advice"),
    (r"\b(insider|guaranteed profit|pump)", "suggests improper conduct"),
]


# ------------------------------------------------------------------- storage
def _load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        return json.load(open(QUEUE_FILE, encoding="utf-8"))
    except Exception:
        return []


def _save_queue(q):
    os.makedirs(SD, exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=1)


def _audit(event, **fields):
    """Append-only record of everything that was approved, published or rejected."""
    os.makedirs(SD, exist_ok=True)
    rec = dict(fields)
    rec["event"] = event
    rec["at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# -------------------------------------------------------------------- screen
URL_RE = re.compile(r"https?://\S+")
# X wraps every link in t.co, so a link costs a flat 23 characters however long
# it is. This matters here: the Google News URLs the news scan collects run to
# 300+ raw characters, and counting those literally would reject posts that X
# accepts comfortably.
X_URL_WEIGHT = 23


def post_length(text, platform="x"):
    """Length as the platform counts it, not as Python does."""
    if platform != "x":
        return len(text)
    return len(URL_RE.sub("u" * X_URL_WEIGHT, text))


def screen(text, platform="x"):
    """Compliance and length screen. Returns (ok, [reasons])."""
    problems = []
    for pat, why in BLOCKED_PATTERNS:
        if re.search(pat, text, re.I):
            problems.append("%s (matched %r)" % (why, pat))
    limit = LIMITS.get(platform, 280)
    n = post_length(text, platform)
    if n > limit:
        problems.append("too long for %s: %d counted chars, limit %d"
                        % (platform, n, limit))
    if not text.strip():
        problems.append("empty draft")
    return (not problems), problems


# -------------------------------------------------------------------- drafts
def _fmt_pct(v):
    return "%+.2f%%" % v if isinstance(v, (int, float)) else "n/a"


def draft_from_signal(signal, platform="x"):
    """Template draft from a scored news signal. Deterministic - no model needed.

    Reports the story and the linked securities; it does not editorialise about
    what anyone should do.
    """
    tickers = []
    for s in signal.get("securities", [])[:3]:
        t = s.get("ticker")
        if t:
            tickers.append(t.split(".")[0])
    tick = " ".join("$" + t for t in dict.fromkeys(tickers))
    themes = ", ".join(dict.fromkeys(t["label"] for t in signal.get("themes", [])))

    head = signal["title"].strip().rstrip(".")
    bits = ["%s: %s" % (signal["exchange"], head)]
    if tick:
        bits.append(tick)
    elif themes:
        bits.append(themes)
    body = " — ".join(bits)
    url = signal.get("url") or ""
    limit = LIMITS.get(platform, 280)
    # Reserve the link's counted cost, not its raw length.
    cost = (X_URL_WEIGHT + 1) if (url and platform == "x") else (len(url) + 1 if url else 0)
    room = limit - cost
    if len(body) > room:
        body = body[: max(0, room - 1)].rstrip() + "…"
    text = (body + (" " + url if url else "")).strip()

    return _make_draft(
        text, platform,
        kind="signal",
        grounding={"signalId": signal.get("id"), "exchange": signal["exchange"],
                   "impact": signal.get("impact"), "bias": signal.get("bias"),
                   "publisher": signal.get("publisher"), "url": url,
                   "securities": tickers, "themes": themes.split(", ") if themes else []})


def draft_market_summary(digest, platform="x"):
    """Template draft summarising where the four boards closed."""
    parts = []
    for ex, d in (digest or {}).items():
        parts.append("%s %s" % (ex, _fmt_pct(d.get("tradedChgPct"))))
    text = "African markets today — " + ", ".join(parts) + " (traded average). mutxriterminal.com"
    return _make_draft(text, platform, kind="market_summary",
                       grounding={"digest": digest})


def draft_with_analyst(subject_text, facts, platform="x", effort="high"):
    """Have Claude write the draft, grounded in supplied facts.

    The model is given the same house rules as the rest of the package, plus the
    publishing constraints - so the compliance screen afterwards is a backstop,
    not the only line of defence.
    """
    from . import analyst
    limit = LIMITS.get(platform, 280)
    system = analyst.SYSTEM + textwrap.dedent("""

    You are drafting a social media post for the MUTXRI TERMINAL account.

    - Stay strictly within the facts given. Never state a figure that is not supplied.
    - Report what happened. Do not tell anyone to buy, sell or hold anything, do
      not set price targets, and do not predict prices.
    - No hype, no emoji strings, no hashtag spam (at most one hashtag).
    - Hard limit %d characters, including any link.
    - Output only the post text. No preamble, no quotes around it.""" % limit)
    prompt = "FACTS:\n%s\n\nTASK: %s" % (
        json.dumps(facts, ensure_ascii=False, indent=1)[:40000], subject_text)
    text = analyst.ask(prompt, system=system, effort=effort,
                       max_tokens=2000, stream=False).strip().strip('"')
    return _make_draft(text, platform, kind="analyst", grounding=facts)


def _make_draft(text, platform, kind, grounding):
    ok, problems = screen(text, platform)
    return {
        "id": uuid.uuid4().hex[:12],
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "platform": platform,
        "kind": kind,
        "text": text,
        "chars": len(text),
        "status": "pending" if ok else "blocked",
        "screen": {"ok": ok, "problems": problems},
        "grounding": grounding,
        "approvedBy": None, "approvedAt": None,
        "publishedAt": None, "publishedId": None, "error": None,
    }


def enqueue(drafts):
    """Add drafts to the review queue, skipping ones already queued verbatim."""
    q = _load_queue()
    seen = {d["text"] for d in q if d.get("status") in ("pending", "published")}
    added = []
    for d in drafts:
        if d["text"] in seen:
            continue
        q.append(d)
        added.append(d)
        seen.add(d["text"])
    _save_queue(q)
    return added


def queue(status=None):
    q = _load_queue()
    return [d for d in q if not status or d.get("status") == status]


def get(draft_id):
    return next((d for d in _load_queue() if d["id"] == draft_id), None)


def set_status(draft_id, **fields):
    q = _load_queue()
    for d in q:
        if d["id"] == draft_id:
            d.update(fields)
            _save_queue(q)
            return d
    return None


def approve(draft_id, approver):
    """Mark a draft approved. Publishing is still a separate, explicit step."""
    d = get(draft_id)
    if not d:
        raise KeyError("no draft %s" % draft_id)
    if d["status"] == "blocked":
        raise ValueError("draft %s failed the compliance screen: %s"
                         % (draft_id, "; ".join(d["screen"]["problems"])))
    if d["status"] == "published":
        raise ValueError("draft %s is already published" % draft_id)
    d = set_status(draft_id, status="approved", approvedBy=approver,
                   approvedAt=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    _audit("approved", draftId=draft_id, approver=approver, platform=d["platform"],
           text=d["text"])
    return d


def reject(draft_id, approver, reason=""):
    d = set_status(draft_id, status="rejected", approvedBy=approver)
    if d:
        _audit("rejected", draftId=draft_id, approver=approver, reason=reason)
    return d


# ----------------------------------------------------------------- publishing
def _oauth1_header(method, url, params, ck, cs, at, ats):
    """OAuth 1.0a signature for X. Posting needs user context - a bearer token
    is read-only, so the app-only token used for the news scan cannot post."""
    oauth = {
        "oauth_consumer_key": ck,
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": at,
        "oauth_version": "1.0",
    }
    allp = dict(params or {})
    allp.update(oauth)
    enc = urllib.parse.quote
    norm = "&".join("%s=%s" % (enc(k, ""), enc(str(allp[k]), ""))
                    for k in sorted(allp))
    base = "&".join([method.upper(), enc(url, ""), enc(norm, "")])
    key = "%s&%s" % (enc(cs, ""), enc(ats, ""))
    sig = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    oauth["oauth_signature"] = base64.b64encode(sig).decode()
    return "OAuth " + ", ".join('%s="%s"' % (enc(k, ""), enc(v, ""))
                                for k, v in sorted(oauth.items()))


def _publish_x(text):
    ck = os.environ.get("X_API_KEY", "").strip()
    cs = os.environ.get("X_API_SECRET", "").strip()
    at = os.environ.get("X_ACCESS_TOKEN", "").strip()
    ats = os.environ.get("X_ACCESS_SECRET", "").strip()
    if not all([ck, cs, at, ats]):
        raise RuntimeError(
            "X posting needs user-context OAuth 1.0a: set X_API_KEY, X_API_SECRET, "
            "X_ACCESS_TOKEN and X_ACCESS_SECRET (the read-only X_BEARER_TOKEN "
            "cannot post)")
    url = "https://api.twitter.com/2/tweets"
    body = json.dumps({"text": text}).encode()
    # JSON bodies are not part of the OAuth 1.0a signature base string.
    auth = _oauth1_header("POST", url, {}, ck, cs, at, ats)
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read().decode("utf-8", "replace"))
    return (out.get("data") or {}).get("id")


def _publish_linkedin(text):
    tok = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    urn = os.environ.get("LINKEDIN_URN", "").strip()
    if not tok or not urn:
        raise RuntimeError("LinkedIn posting needs LINKEDIN_ACCESS_TOKEN and "
                           "LINKEDIN_URN (e.g. urn:li:organization:12345)")
    payload = {
        "author": urn, "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": {
            "shareCommentary": {"text": text},
            "shareMediaCategory": "NONE"}},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    req = urllib.request.Request(
        "https://api.linkedin.com/v2/ugcPosts",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok,
                 "Content-Type": "application/json",
                 "X-Restli-Protocol-Version": "2.0.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace")).get("id")


PUBLISHERS = {"x": _publish_x, "linkedin": _publish_linkedin}


def publish(draft_id, approver, confirmed=False):
    """Publish an approved draft. Requires `confirmed=True` from the caller.

    The caller is responsible for having actually asked a person. The CLI prompts
    interactively; nothing in the scheduled pipeline calls this.
    """
    d = get(draft_id)
    if not d:
        raise KeyError("no draft %s" % draft_id)
    if d["status"] == "published":
        raise ValueError("draft %s is already published (%s)"
                         % (draft_id, d.get("publishedId")))
    if d["status"] != "approved":
        raise ValueError("draft %s is %s - approve it first" % (draft_id, d["status"]))
    if not confirmed:
        raise ValueError("publish requires explicit confirmation")

    # Re-screen at the moment of publishing: the text may have been edited in the
    # queue file after it was approved.
    ok, problems = screen(d["text"], d["platform"])
    if not ok:
        set_status(draft_id, status="blocked",
                   screen={"ok": False, "problems": problems})
        _audit("blocked_at_publish", draftId=draft_id, problems=problems)
        raise ValueError("draft %s no longer passes the screen: %s"
                         % (draft_id, "; ".join(problems)))

    pub = PUBLISHERS.get(d["platform"])
    if not pub:
        raise ValueError("no publisher for platform %r" % d["platform"])
    try:
        posted_id = pub(d["text"])
    except Exception as e:
        detail = "%s: %s" % (type(e).__name__, e)
        if hasattr(e, "read"):
            try:
                detail += " | " + e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
        set_status(draft_id, error=detail)
        _audit("publish_failed", draftId=draft_id, error=detail)
        raise RuntimeError(detail)

    d = set_status(draft_id, status="published", publishedId=posted_id, error=None,
                   publishedAt=dt.datetime.now(dt.timezone.utc)
                   .isoformat(timespec="seconds"))
    _audit("published", draftId=draft_id, approver=approver,
           platform=d["platform"], postId=posted_id, text=d["text"])
    return d


def credentials_status():
    """What the publisher could actually post to right now."""
    x_ok = all(os.environ.get(k) for k in
               ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))
    li_ok = all(os.environ.get(k) for k in ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_URN"))
    return {"x": "ready" if x_ok else "not configured (needs OAuth 1.0a user context)",
            "linkedin": "ready" if li_ok else "not configured"}
