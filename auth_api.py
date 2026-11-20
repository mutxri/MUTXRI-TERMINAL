#!/usr/bin/env python3
"""auth_api.py - email accounts for the terminal.
Signup/login/logout with pbkdf2-hashed passwords (stdlib only) and
token sessions. Users stored in MongoDB 'users' collection when available,
else a local users.json file. NEVER stores plaintext passwords."""
import hashlib, hmac, json, os, re, secrets, time, urllib.parse, urllib.request

_DB = None          # set by afri_server (Mongo db) if available
_USE_MONGO = False
_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---- WHO IS ALLOWED TO CREATE AN ACCOUNT -------------------------------------
# A signup form is the cheapest place to manufacture addresses: a script can post
# test@example.com or a dotted variant of a real Gmail address and the database
# fills with accounts nobody can sign into. The classifier lives in
# cleanup_fakes.py so the same definition is used to purge the old rows and to
# refuse new ones - one rule, not two that drift.
try:
    from cleanup_fakes import classify as _classify_fake, gmail_key as _gmail_key
except Exception:                                     # pragma: no cover
    def _classify_fake(email, name=""):
        return False, ""
    def _gmail_key(local, dom):
        return None


def _mailbox_key(email):
    """The identity Google itself uses: dots and +tags are not a new person."""
    addr = (email or "").lower().strip()
    if "@" not in addr:
        return addr
    local, _, dom = addr.rpartition("@")
    if dom in ("gmail.com", "googlemail.com"):
        return "gmail:" + local.split("+", 1)[0].replace(".", "")
    return dom + ":" + local


def _mail_configured():
    return bool(os.environ.get("MAIL_PASS", "").strip())


def _new_code():
    import random
    return "%06d" % random.randint(0, 999999)


_SESSIONS = {}  # in-process cache only: token -> {email, exp}
_SESSIONS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.json")


# Sessions have to outlive the process. They used to live only in the dict
# above, so every Render restart or idle spin-down silently invalidated every
# token: people came back with a valid mt_token in localStorage, /api/auth/me
# answered "session expired", and they were bounced to the login form.
def _sessions_load():
    try:
        with open(_SESSIONS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _sessions_save(d):
    try:
        with open(_SESSIONS_JSON, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def _session_put(token, rec):
    _SESSIONS[token] = rec
    try:
        if _USE_MONGO:
            _DB["sessions"].replace_one(
                {"_id": token}, {"_id": token, "email": rec["email"], "exp": rec["exp"],
                                 "seen": rec.get("seen", 0)},
                upsert=True)
        else:
            d = _sessions_load(); d[token] = rec; _sessions_save(d)
    except Exception:
        pass   # the in-process cache still serves this instance


def _session_get(token):
    if not token:
        return None
    s = _SESSIONS.get(token)
    if s:
        return s
    try:
        if _USE_MONGO:
            r = _DB["sessions"].find_one({"_id": token})
            if r:
                rec = {"email": r.get("email"), "exp": r.get("exp", 0), "seen": r.get("seen", 0)}
                _SESSIONS[token] = rec
                return rec
        else:
            r = _sessions_load().get(token)
            if r:
                _SESSIONS[token] = r
                return r
    except Exception:
        pass
    return None


def _session_del(token):
    _SESSIONS.pop(token or "", None)
    try:
        if _USE_MONGO:
            _DB["sessions"].delete_one({"_id": token})
        else:
            d = _sessions_load(); d.pop(token, None); _sessions_save(d)
    except Exception:
        pass
# owner account: full lifetime access (token never expires)
_OWNER = (os.environ.get("OWNER_EMAIL", "") or "jimmymuturi99@gmail.com").lower().strip()

def _is_owner(email):
    return bool(_OWNER) and (email or "").lower().strip() == _OWNER

# Everyone but the owner is signed out once they leave the site. Every open page
# checks in (POST /api/auth/me) about once a minute; a session that has gone
# SESSION_IDLE_SECONDS without a check-in is over, so the next visit asks them to
# log in again. Reloads, moving between pages and a tab left in the background
# all sit inside the window. The owner keeps a lifetime session, never idled out.
IDLE_SECONDS = int(os.environ.get("SESSION_IDLE_SECONDS", "600") or 600)
_TOUCH_EVERY = 60   # write a check-in to the store at most once a minute


def _issue_token(email):
    token = secrets.token_hex(32)
    now = time.time()
    exp = now + (3650 * 86400 if _is_owner(email) else 30 * 86400)  # owner: ~10y
    _session_put(token, {"email": email, "exp": exp, "seen": now})
    return token


def _live(token):
    """The session behind token while it is still valid, recording the check-in.

    Returns None, and deletes the session, once it has expired or - for anyone
    but the owner - once it has gone IDLE_SECONDS without a check-in. Sessions
    issued before idle expiry existed carry no 'seen', so deploying this does not
    sign everyone out at once: their next check-in starts the window."""
    s = _session_get(token)
    now = time.time()
    if not s or s.get("exp", 0) < now:
        _session_del(token)
        return None
    if not _is_owner(s.get("email")):
        seen = s.get("seen") or 0
        if seen and now - seen > IDLE_SECONDS:
            _session_del(token)
            return None
        if now - seen >= _TOUCH_EVERY:
            s["seen"] = now
            _session_put(token, s)
    return s



_USERS_INDEX_READY = False


def _ensure_users_index():
    """One account document per email, when Mongo is the store.

    Nothing enforced that. Two documents could share an email (a record carried
    over from the old users.json file sitting beside one created straight in
    Mongo, or two racing signups), and find_one then returns whichever the
    server reaches first - so a username written to one document reads back as
    the original from the other. A unique index makes the account the address
    names single and every read deterministic. Best effort: a pre-existing
    duplicate must not stop the service from starting, so a failure is logged,
    never raised, and a record is never deleted to force the index.
    """
    global _USERS_INDEX_READY
    if _USERS_INDEX_READY or not _USE_MONGO:
        return
    try:
        _DB["users"].create_index("email", unique=True, name="uniq_email")
        _USERS_INDEX_READY = True
    except Exception as e:
        print("[auth] users.email unique index NOT created (duplicate rows?): "
              "%s" % str(e)[:140], flush=True)


def _migrate_json_into_mongo():
    """Carry any users.json accounts into Mongo once, without clobbering.

    A record already in Mongo wins; a JSON-only account (one created while the
    store was the local file) is inserted so it is not orphaned when the file
    is discarded. Nothing is ever overwritten or deleted, so a username already
    stored cannot be lost to a stale file.
    """
    if not _USE_MONGO:
        return
    try:
        data = _load_json()
    except Exception:
        return
    if not isinstance(data, dict) or not data:
        return
    moved = 0
    for email, rec in data.items():
        if not isinstance(rec, dict):
            continue
        try:
            rec = dict(rec)
            rec.pop("_id", None)
            rec["email"] = (rec.get("email") or email or "").lower().strip()
            if not rec["email"]:
                continue
            if _DB["users"].find_one({"email": rec["email"]}, {"_id": 1}) is None:
                _DB["users"].insert_one(rec)
                moved += 1
        except Exception:
            continue
    if moved:
        print("[auth] carried %d user record(s) from users.json into Mongo"
              % moved, flush=True)


def _init(db, mongo_ok):
    global _DB, _USE_MONGO
    _DB = db
    _USE_MONGO = bool(mongo_ok and db is not None)
    if _USE_MONGO:
        _ensure_users_index()
        _migrate_json_into_mongo()

def _load_json():
    try:
        with open(_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_json(data):
    with open(_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

def _find_user(email):
    email = email.lower().strip()
    if _USE_MONGO:
        # Newest document wins, deterministically. With a unique index there is
        # exactly one; before it exists this stops a stale duplicate from being
        # served one request and the live record the next.
        u = _DB["users"].find_one({"email": email}, sort=[("created", -1), ("_id", -1)])
        return dict(u) if u else None
    return _load_json().get(email)

def _all_users():
    """Every account, whichever store is live. Used by the duplicate-mailbox check
    and by the fake purge, so neither can quietly see an empty list."""
    try:
        if _USE_MONGO:
            return [dict(u) for u in _DB["users"].find({})]
        return [dict(v) for v in (_load_json() or {}).values() if isinstance(v, dict)]
    except Exception:
        return []


def _update_user(email, patch):
    """Apply a partial change to one account, on either store."""
    email = (email or "").lower().strip()
    if _USE_MONGO:
        _DB["users"].update_one({"email": email}, {"$set": dict(patch)})
        return True
    data = _load_json()
    rec = data.get(email)
    if not rec:
        return False
    rec.update(patch)
    data[email] = rec
    _save_json(data)
    return True


def _save_user(record):
    if _USE_MONGO:
        rec = dict(record)
        rec.pop("_id", None)   # Mongo keeps the existing _id; a stray one is a mismatch
        # Same sort as _find_user, so the write lands on the exact document the
        # read returns even in the pre-index window.
        _DB["users"].find_one_and_replace(
            {"email": rec["email"]}, rec, sort=[("created", -1), ("_id", -1)], upsert=True)
    else:
        data = _load_json()
        data[record["email"]] = record
        _save_json(data)


# ---------------------------------------------------------------------------
# Sign-in record.
# The account list only proves an account EXISTS. The owner asked for the email
# of everyone who actually signs in, so every signup, password sign-in and
# Google sign-in writes one row to the `signins` collection (a local file when
# Mongo is not connected, same fallback the users table uses). Recording never
# blocks a sign-in: any failure here is swallowed.
# ---------------------------------------------------------------------------
_SIGNINS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signins.json")
SIGNIN_KEEP = 5000


def _record_signin(email, name="", provider="password", kind="signin", ip="", user_agent=""):
    email = (email or "").lower().strip()
    if not email:
        return
    row = {
        "email": email,
        "name": (name or "")[:80],
        "provider": (provider or "password")[:20],
        "kind": (kind or "signin")[:12],     # signup | signin | oauth
        "ts": time.time(),
        "ip": (ip or "")[:64],
        "ua": (user_agent or "")[:180],
    }
    try:
        if _USE_MONGO:
            _DB["signins"].insert_one(dict(row))
            _DB["users"].update_one({"email": email},
                                    {"$set": {"last_signin": row["ts"],
                                              "last_provider": row["provider"],
                                              "signins": (_find_user(email) or {}).get("signins", 0) + 1}})
        else:
            data = []
            if os.path.exists(_SIGNINS_PATH):
                with open(_SIGNINS_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            data.append(row)
            with open(_SIGNINS_PATH, "w", encoding="utf-8") as f:
                json.dump(data[-SIGNIN_KEEP:], f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def recent_signins(limit=300):
    """Every recorded sign-in, newest first. Never raises."""
    try:
        limit = max(1, min(int(limit or 300), 2000))
    except Exception:
        limit = 300
    try:
        if _USE_MONGO:
            rows = list(_DB["signins"].find({}, {"_id": 0}).sort("ts", -1).limit(limit))
            return rows
        with open(_SIGNINS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return list(reversed(data[-limit:]))
    except Exception:
        return []


def _hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000)
    return salt + ":" + dk.hex()

def _check_password(password, stored):
    try:
        salt, hexdigest = stored.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000)
        return hmac.compare_digest(dk.hex(), hexdigest)
    except Exception:
        return False

def _cb_url(host, provider):
    base = os.environ.get("OAUTH_BASE", "").strip().rstrip("/")
    if base:
        # fixed callback domain (e.g. https://mutxriterminal.com) so Google's
        # registered redirect can live on the authorized domain regardless of
        # which host the browser hit (Render proxy keeps its own Host).
        return "%s/api/auth/oauth/%s/callback" % (base, provider)
    host = (host or "").strip()
    return "https://%s/api/auth/oauth/%s/callback" % (host, provider)

_OAUTH_STATE = {}   # state -> {provider, exp}
_OAUTH_CODES = {}   # one-time code -> {email, name, exp}


def oauth_start(provider, host):
    """Return the provider authorize URL (or an error string if unconfigured)."""
    provider = (provider or "").lower()
    state = secrets.token_hex(16)
    _OAUTH_STATE[state] = {"provider": provider, "exp": time.time() + 600}
    cb = _cb_url(host, provider)
    if provider == "google":
        cid = os.environ.get("GOOGLE_CLIENT_ID", "")
        if not cid:
            return {"ok": False, "error": "Google sign-in is not configured yet."}
        return {"ok": True, "url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=%s&redirect_uri=%s&response_type=code&scope=openid%%20email%%20profile&state=%s" % (
            urllib.parse.quote(cid, safe=""), urllib.parse.quote(cb, safe=""), state)}
    return {"ok": False, "error": "Unknown provider."}

def _gg_access_token(code, cb):
    cid = os.environ.get("GOOGLE_CLIENT_ID", ""); csec = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    req = urllib.request.Request("https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode({"client_id": cid, "client_secret": csec, "code": code, "redirect_uri": cb, "grant_type": "authorization_code"}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    return d.get("access_token", "")

def _gg_profile(token):
    req = urllib.request.Request("https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": "Bearer " + token})
    u = json.loads(urllib.request.urlopen(req, timeout=25).read().decode())
    return (u.get("email") or ""), (u.get("name") or "")

def oauth_callback(provider, code, state, host, user_agent="", ip=""):
    """Exchange the provider code, find/create the account, return a one-time
    frontend code (redirect target) — never put the session token in a URL."""
    fail = "https://mutxriterminal.com/terminal/?oauth=error"
    st = _OAUTH_STATE.pop(state or "", None)
    if not st or st.get("provider") != provider or st.get("exp", 0) < time.time() or not code:
        return fail
    cb = _cb_url(host, provider)
    try:
        if provider == "google":
            tok = _gg_access_token(code, cb); email, name = _gg_profile(tok)
        else:
            return fail
    except Exception:
        return fail
    email = (email or "").lower().strip()
    if not email:
        return fail
    u = _find_user(email)
    is_new = not u
    if is_new:
        u = {"email": email, "name": (name or "")[:80], "pw": _hash_password(secrets.token_hex(16)),
             "created": time.time(), "oauth": provider, "devices": []}
        _save_user(u)
    _record_signin(email, u.get("name", ""), provider,
                   "signup" if is_new else "signin", ip, user_agent)

    otc = secrets.token_hex(32)
    _OAUTH_CODES[otc] = {"email": email, "name": u.get("name", ""), "exp": time.time() + 120}
    return "https://mutxriterminal.com/terminal/?oauth=%s&code=%s" % (provider, otc)

def oauth_exchange(one_time_code):
    """Frontend trades the one-time code for a real session token (single use)."""
    rec = _OAUTH_CODES.pop(one_time_code or "", None)
    if not rec or rec.get("exp", 0) < time.time():
        return {"ok": False, "error": "Sign-in link expired. Please try again."}
    token = _issue_token(rec["email"])
    u = _find_user(rec["email"])
    return {"ok": True, "token": token, "email": rec["email"], "name": rec.get("name", ""),
            "username": (u or {}).get("username", ""), "owner": _is_owner(rec["email"])}

# MAILER (2026-09-29): the deployed backend had NO sending code at all. afri_server.py
# does `import auth_api`, which resolves to THIS file, so signups on the live site sent
# nothing while the root copy held the only mailer. Ported verbatim from the root file.
# Needs MAIL_PASS in the environment (Render dashboard); without it the function
# returns quietly and signup still succeeds.
def send_mention_email(to_email, to_name, from_handle, room, text):
    """Tell a signed-in user they were mentioned in the room.

    Sent to the address they signed in with, which is the only address the
    account has. Non-blocking: a mail failure is logged and never fails the
    message, exactly like the confirmation email, because the message is already
    in the room by the time this runs.
    """
    try:
        import smtplib, os, html as _html
        from email.mime.text import MIMEText
        from email.utils import formataddr
        server = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
        user = os.environ.get("MAIL_USER", "mutxriterminal@gmail.com")
        pwd = os.environ.get("MAIL_PASS", "")
        sender = os.environ.get("MAIL_FROM", user or "mutxriterminal@gmail.com")
        if not server or not user or not pwd:
            print("[chat] MAIL_USER/MAIL_PASS not set - mention email NOT sent to %s" % to_email,
                  flush=True)
            return False
        first = _html.escape((to_name or to_email).split()[0])
        who = _html.escape(str(from_handle or "someone"))
        room_l = _html.escape(str(room or "main"))
        body = _html.escape(str(text or ""))[:1500]
        html = f"""<div style="background:#000;color:#f0f0f0;font-family:monospace;padding:32px">
  <h2 style="color:#33e29a">MUTXRI TERMINAL</h2>
  <p>Hi {first},</p>
  <p><b style="color:#e0a340">{who}</b> mentioned you in the {room_l} room.</p>
  <p style="border-left:3px solid #33e29a;padding-left:12px;color:#d2d2d2">{body}</p>
  <p><a href="https://mutxriterminal.com/terminal/" style="color:#33e29a">Open the room</a></p>
  <p style="color:#6a6a6a;font-size:12px">You are getting this because your account signed in with
  this address. Mentions arrive one email per message, never a digest.</p>
</div>"""
        msg = MIMEText(html, "html")
        msg["Subject"] = "%s mentioned you in the %s room" % (str(from_handle or "Someone"), str(room or "main"))
        msg["From"] = formataddr(("MUTXRI TERMINAL", sender))
        msg["To"] = to_email
        with smtplib.SMTP(server, int(os.environ.get("MAIL_PORT", "587")), timeout=30) as sm:
            sm.starttls()
            sm.login(user, pwd)
            sm.sendmail(sender, [to_email], msg.as_string())
        return True
    except Exception as e:
        print("[chat] mention email failed for %s: %s" % (to_email, str(e)[:140]), flush=True)
        return False


def _send_confirmation_email(email, name, code=None):
    """Send a confirmation email on signup via Zoho SMTP (env-configured).

    Zoho, not SES: the SES account is sandboxed, so it silently rejects any
    recipient that is not a verified identity - which is every real signup.
    Zoho sends to arbitrary recipients and its DKIM (selector 'zmail') aligns
    with mutxri.com, so these messages pass DMARC.

    Non-blocking: failures are logged, never fail the signup."""
    try:
        import smtplib, ssl, os, html as _html
        from email.mime.text import MIMEText
        # smtppro.zoho.com is the host for custom-domain (paid) Zoho accounts;
        # free/personal accounts use smtp.zoho.com. Override via MAIL_SERVER.
        # MAILBOX 2026-09-28: the sending account is mutxriterminal@gmail.com and it
        # sends through Gmail SMTP. These defaults were previously a Zoho account for
        # mutxri.com that no longer serves this domain, so every sign-in and
        # confirmation email failed silently while the form looked broken.
        server = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
        user = os.environ.get("MAIL_USER", "mutxriterminal@gmail.com")
        pwd = os.environ.get("MAIL_PASS", "")
        sender = os.environ.get("MAIL_FROM", user or "mutxriterminal@gmail.com")
        if not server or not user or not pwd:
            print("[auth] MAIL_USER/MAIL_PASS not set - confirmation email "
                  f"NOT sent to {email}", flush=True)
            return
        first = (name or email).split()[0] if (name or "").strip() else email
        first = _html.escape(first)  # never let a user-supplied name inject HTML into the email
        code_block = ("<p style=\"color:#33e29a;font-size:22px;letter-spacing:6px\">"
                      + _html.escape(str(code)) + "</p>"
                      + "<p style=\"color:#9a9a9a\">Enter this code in the terminal to confirm the "
                        "address belongs to you. It is the only way an account on a made-up address "
                        "can be stopped, so it is required.</p>") if code else ""
        html = f"""<div style="background:#000;color:#f0f0f0;font-family:monospace;padding:32px">
  <h2 style="color:#33e29a">MUTXRI TERMINAL</h2>
  <p>Hi {first},</p>
  <p>Your MUTXRI TERMINAL account has been created. Welcome.</p>
  {code_block}
  <p style="color:#9a9a9a">You can now log in at <a href="https://mutxriterminal.com" style="color:#33e29a">mutxriterminal.com</a> and start exploring 938 securities across the NSE, NGX, JSE and EGX.</p>
  <p style="color:#6a6a6a;font-size:12px">This is a confirmation email for your account. No action needed. If you did not create this account, reply and we will remove it.</p>
</div>"""
        msg = MIMEText(html, "html")
        msg["Subject"] = ("MUTXRI TERMINAL - your code is " + str(code)) if code else "Welcome to MUTXRI TERMINAL - account confirmed"
        msg["From"] = sender
        msg["To"] = email
        ctx = ssl.create_default_context()
        with smtplib.SMTP(server, int(os.environ.get("MAIL_PORT", "587")), timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(sender, [email], msg.as_string())
        print(f"[auth] confirmation email sent to {email}", flush=True)
    except Exception as e:
        print(f"[auth] CONFIRMATION EMAIL FAILED for {email}: "
              f"{type(e).__name__}: {str(e)[:200]}", flush=True)


def signup(email, password, name="", username="", ip="", user_agent=""):
    email = (email or "").lower().strip()
    if not _EMAIL_RE.match(email):
        return {"ok": False, "error": "A valid email is required"}
    if not password or len(password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters"}
    # REFUSE AN ADDRESS NOBODY CAN RECEIVE MAIL AT. Test/disposable domains and
    # fixture local parts are rejected outright, with the reason, instead of being
    # written to the user table and cleaned up later.
    _fake, _why = _classify_fake(email, (name or ""))
    if _fake:
        return {"ok": False, "error": "Use an email address you can receive mail at (%s)" % _why}
    # A dotted or +tagged Gmail address is the SAME mailbox, so it cannot become a
    # second account: every existing user is compared on the mailbox key, not the
    # literal string.
    _my_key = _mailbox_key(email)
    for _u in _all_users():
        if _mailbox_key(_u.get("email")) == _my_key:
            return {"ok": False,
                    "error": "An account with this email already exists (dots and +tags in a Gmail "
                             "address are the same mailbox)"}
    _existing = _find_user(email)
    if _existing:
        # Point Google users at the door that actually opens. Deliberately NOT
        # setting a password here: that would let anyone who knows the address
        # take over an OAuth account. They sign in with Google first.
        if _existing.get("oauth") and not _existing.get("pw_set"):
            return {"ok": False, "oauth": _existing.get("oauth"),
                    "error": "This email already signs in with %s. Use \"Continue with %s\"."
                             % (_existing.get("oauth").title(), _existing.get("oauth").title())}
        return {"ok": False, "error": "An account with this email already exists"}
    record = {
        "email": email,
        "name": (name or "").strip()[:80],
        "username": (username or "").strip()[:30],
        # A handle typed on the signup form is a deliberate choice, exactly like
        # one set later in the Username field, so it is recorded and protected
        # from set_name. Left blank it stays unset and stays adoptable.
        "username_explicit": bool((username or "").strip()),
        "username_history": [],
        "pw": _hash_password(password),
        "created": time.time(),
    }
    # PROOF OF OWNERSHIP. A code is generated at signup and mailed to the address;
    # until it comes back the account exists but is marked unverified. A made-up
    # Gmail address never receives the code, so it can never be used. When no mail
    # credentials are configured the check cannot run, and the account is marked
    # verified so a signup still works instead of dead-ending.
    if _mail_configured():
        record["verified"] = False
        record["verify_code"] = _new_code()
        record["verify_sent"] = time.time()
    else:
        record["verified"] = True
    _save_user(record)
    # send the welcome email without letting a mail failure break signup
    try:
        _send_confirmation_email(email, record["name"], code=record.get("verify_code"))
    except Exception:
        pass
    _record_signin(email, record["name"], "password", "signup", ip, user_agent)
    token = _issue_token(email)
    return {"ok": True, "token": token, "email": email, "name": record["name"],
            "username": record["username"], "owner": _is_owner(email),
            "verified": bool(record.get("verified")),
            "verify_required": bool(record.get("verify_code"))}

def verify_signup(email, code):
    """Confirm the address by the code mailed at signup.

    A made-up Gmail address passes every format test; the only thing it cannot do is
    receive the code. So the account is created at signup but stays unverified, and
    this is the call that flips it.
    """
    email = (email or "").lower().strip()
    code = (code or "").strip().replace(" ", "")
    u = _find_user(email)
    if not u:
        return {"ok": False, "error": "No account for that address"}
    if u.get("verified"):
        return {"ok": True, "verified": True, "already": True, "email": email}
    want = str(u.get("verify_code") or "")
    if not want:
        return {"ok": False, "error": "No code is outstanding for this account"}
    if code != want:
        return {"ok": False, "error": "That code is not right"}
    _update_user(email, {"verified": True, "verified_at": time.time(), "verify_code": None})
    return {"ok": True, "verified": True, "email": email, "token": _issue_token(email)}


def login(email, password, ip="", user_agent=""):
    email = (email or "").lower().strip()
    u = _find_user(email)
    # Accounts created through Google get a random unguessable password, so a
    # password login against one can never succeed. Saying "invalid email or
    # password" sent people round in circles (their password manager had
    # credentials, they looked right, they always failed). Say what is actually
    # wrong instead.
    if u and u.get("oauth") and not u.get("pw_set"):
        return {"ok": False, "oauth": u.get("oauth"),
                "error": "This account was created with %s. Use \"Continue with %s\" to sign in."
                         % (u.get("oauth").title(), u.get("oauth").title())}
    # AN UNVERIFIED ACCOUNT CANNOT SIGN IN while mail is configured: the address has
    # not proved it exists. The message names the next step rather than saying the
    # password is wrong.
    if u and u.get("verify_code") and not u.get("verified") and _mail_configured():
        return {"ok": False, "verify_required": True, "email": u.get("email"),
                "error": "Confirm your email first. Enter the 6-digit code we sent to %s."
                         % u.get("email")}
    if not u or not _check_password(password, u.get("pw", "")):
        # A missing account skipped the KDF entirely (Python short-circuits the
        # `or`), so a wrong password for a real user took measurably longer than
        # an address with no account. Burn the same PBKDF2 work on the missing
        # path so both answers cost the same, then say what the owner asked for.
        if not u:
            _check_password(password, "0" * 32 + ":" + "0" * 64)
        return {"ok": False, "error": "User not found"}
    _record_signin(email, u.get("name", ""), "password", "signin", ip, user_agent)
    token = _issue_token(email)
    return {"ok": True, "token": token, "email": email, "name": u.get("name", ""),
            "username": u.get("username", ""), "owner": _is_owner(email)}

def set_password(token, password):
    """Give a signed-in account a password it can actually log in with.

    This is how a Google user stops being locked out of the email/password
    form: they are already authenticated by the session token, so no email
    round-trip is needed. It also lets a password user rotate their password.
    """
    if not password or len(password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters"}
    s = _live(token)
    if not s:
        return {"ok": False, "error": "Session expired", "code": "session_expired"}
    u = _find_user(s["email"])
    if not u:
        return {"ok": False, "error": "Account not found"}
    u["pw"] = _hash_password(password)
    u["pw_set"] = True            # from here on, password login is allowed
    _save_user(u)
    return {"ok": True, "email": s["email"]}


def set_username(token, username):
    """Set the chat display handle (username) for the signed-in account.

    This is what shows in the shared chat room instead of the account's real
    name. Falls back to name (or the email prefix) until one is set.

    A successful save also RECORDS that the handle was chosen here
    (username_explicit = True). That record - not a guess about the handle's
    characters - is what tells set_name the handle is deliberate, so a handle
    like '@jimmy' is never mistaken for an un-chosen email leftover.
    """
    s = _live(token)
    if not s:
        return {"ok": False, "error": "Session expired", "code": "session_expired"}
    username = (username or "").strip()
    if not username:
        return {"ok": False, "error": "Username required"}
    if len(username) > 30:
        return {"ok": False, "error": "Username too long (30 max)"}
    if any(ord(c) < 32 for c in username):
        return {"ok": False, "error": "Invalid username"}
    u = _find_user(s["email"])
    if not u:
        return {"ok": False, "error": "Account not found"}
    old = u.get("username", "")
    if old != username:
        hist = u.get("username_history") or []
        hist.append({"username": username, "previous": old, "ts": time.time()})
        u["username_history"] = hist[-50:]   # keep every change, capped at 50
    u["username"] = username
    # Record the FACT of the choice, not a guess about its characters. set_name
    # reads this to know the handle was picked here on purpose, so a handle such
    # as '@jimmy' - which merely contains '@' - is never overwritten.
    u["username_explicit"] = True
    _save_user(u)
    return {"ok": True, "username": username, "email": s["email"]}


def set_name(token, name):
    """Set the account's real name, and keep the public chat handle honest.

    The account panel labels this field "how you appear in chat", so someone who
    types a handle here expects the room to show it - but the room only ever
    reads `username`, so the save looked like it never stuck. A save therefore
    also sets the chat handle only when the stored handle was NEVER deliberately
    chosen: it is empty, or it is nothing but this account's own email address
    (which published the address to the whole room).

    Whether a handle was deliberate is read from the recorded choice
    (`username_explicit`, written by set_username and by a signup that carried a
    handle), never inferred from the handle's characters. So a handle the user
    chose in the Username field - including one containing '@', such as
    '@jimmy' - is left exactly as it is, as this docstring has always promised.
    An account that only ever had its handle adopted records
    `username_explicit` False, so it stays adoptable: a later Name save keeps
    the adopted handle in step with the name. An account carried over from
    before this change has no recorded choice at all, so it adopts only from an
    empty handle or its own raw email - the conservative rule that cannot
    destroy any pre-existing handle.
    """
    s = _live(token)
    if not s:
        return {"ok": False, "error": "Session expired", "code": "session_expired"}
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "Name required"}
    if len(name) > 80:
        return {"ok": False, "error": "Name too long (80 max)"}
    if any(ord(c) < 32 for c in name):
        return {"ok": False, "error": "Invalid name"}
    u = _find_user(s["email"])
    if not u:
        return {"ok": False, "error": "Account not found"}
    u["name"] = name[:80]
    cur = (u.get("username") or "").strip()
    explicit = u.get("username_explicit")          # True | False | None (absent)
    chosen = (explicit is True)                    # picked in the Username field / signup
    adopted_before = (explicit is False)           # a past Name save adopted it (recorded)
    owns_email = cur.lower() == (u.get("email") or "").lower().strip()
    # Adopt the real name as the chat handle ONLY for a handle that was never
    # deliberately chosen. The RECORD decides, never the handle's characters:
    #   * empty                         -> never chosen, adopt.
    #   * the account's own email       -> the raw-address leftover the rule
    #                                      exists to remove, and not chosen, adopt.
    #   * recorded adopted (flag False) -> still following the name, adopt the new.
    #   * anything else (flag True or absent: a plain handle, or '@jimmy') -> keep.
    # A MIGRATED account carries NO username_explicit key, so it adopts only from
    # empty or the raw account email. That rule cannot destroy a pre-existing
    # handle: it never overwrites a non-empty handle that is not the account's own
    # email - which protects a deliberate '@jimmy' and equally a pre-existing
    # handle that merely happens to equal the old name.
    adoptable = (not chosen) and (adopted_before or owns_email)
    if (not cur) or adoptable:
        new_handle = name[:30]
        if new_handle and new_handle != cur:
            hist = u.get("username_history") or []
            hist.append({"username": new_handle, "previous": cur, "ts": time.time()})
            u["username_history"] = hist[-50:]
        u["username"] = new_handle
        # Adopted, not chosen: record that, so the account STAYS adoptable and a
        # later Name save keeps the handle in step. It is never set explicit.
        u["username_explicit"] = False
    _save_user(u)
    return {"ok": True, "name": name, "username": u.get("username", ""),
            "email": s["email"]}


def logout(token):
    if token:
        _session_del(token)
    return {"ok": True}

def me(token):
    if not token:
        return {"ok": False, "error": "Not logged in"}
    s = _live(token)
    if not s:
        return {"ok": False, "error": "Session expired"}
    u = _find_user(s["email"])
    owner = _is_owner(s["email"])
    # 'provider' lets the client confirm WHICH door the session came through. Sign-in
    # is Google-only, so a session minted by email + password has to be visible as such
    # rather than looking identical to a Google one.
    prov = ((u or {}).get("oauth") or "email")
    return {"ok": True, "email": s["email"], "name": (u or {}).get("name", ""),
            "username": (u or {}).get("username", ""), "owner": owner,
            "provider": str(prov).lower(),
            "access": "lifetime" if owner else "standard",
            "idle_seconds": None if owner else IDLE_SECONDS}


def store_mode():
    """'mongo' when connected to MongoDB, 'json' when falling back to users.json."""
    return "mongo" if _USE_MONGO else "json"

def _admin_key_ok(key):
    """The ADMIN_KEY from the environment, compared in constant time."""
    expected = os.environ.get("ADMIN_KEY", "")
    return bool(expected) and bool(key) and hmac.compare_digest(key, expected)


def _owner_token_ok(token):
    """True when the caller holds a live session for the OWNER account.

    The owner already signs into the terminal with their own account, so they
    should not have to go digging the ADMIN_KEY out of the Render dashboard
    just to see who is using it. Reading is owner-only; nothing here exposes a
    password hash.
    """
    s = _session_get(token or "")
    return bool(s) and s.get("exp", 0) > time.time() and _is_owner(s.get("email"))


def _admin_ok(key, token):
    return _admin_key_ok(key) or _owner_token_ok(token)


def admin_purge_fakes(key="", token="", dry=False):
    """Admin: delete bot and test signups, keep the real accounts.

    Uses the same classifier as cleanup_fakes.py, so the rule that refuses a fake at
    signup is the rule that removes an old one. Reports what it removed, address by
    address, because deleting accounts is not something to do silently.
    """
    if not _admin_ok(key, token):
        return {"ok": False, "error": "Unauthorized"}
    try:
        import cleanup_fakes as CF
    except Exception as e:
        return {"ok": False, "error": "cleanup module unavailable: %s" % e}
    out = {"ok": True, "dry": bool(dry), "users": [], "signins": 0, "events": 0, "mongo": 0}
    # users
    try:
        rows = _all_users() if "_all_users" in globals() else []
    except Exception:
        rows = []
    seen = {}
    for u in rows:
        email = (u.get("email") or "")
        fake, why = CF.classify(email, u.get("name"))
        key_g = CF.gmail_key(*((email.lower().rpartition("@")[0], email.lower().rpartition("@")[2])
                               if "@" in email else ("", "")))
        if not fake and key_g:
            if key_g in seen:
                fake, why = True, "duplicate gmail mailbox of " + seen[key_g]
            else:
                seen[key_g] = email
        if fake:
            out["users"].append({"email": email, "why": why})
            if not dry:
                try:
                    if _USE_MONGO:
                        _DB["users"].delete_one({"email": email.lower()})
                    else:
                        data = _load_json()
                        if email.lower() in data:
                            data.pop(email.lower(), None)
                            _write_json(data)
                except Exception as e:
                    out.setdefault("errors", []).append("%s: %s" % (email, str(e)[:60]))
    # sign-in rows and login events
    for path, label, attr in ((_SIGNINS_PATH, "signins.json", "signins"),
                              (os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_events.json"),
                               "login_events.json", "events")):
        try:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            rows2 = d.get("items") if isinstance(d, dict) else d
            keep = []
            for r in (rows2 or []):
                em = (r.get("email") if isinstance(r, dict) else "") or ""
                fake, _ = CF.classify(em, r.get("name") if isinstance(r, dict) else "")
                if fake:
                    out[attr] += 1
                else:
                    keep.append(r)
            if not dry and out[attr]:
                if isinstance(d, dict):
                    d["items"] = keep
                else:
                    d = keep
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(d, fh, ensure_ascii=False, indent=1)
                os.replace(tmp, path)
        except Exception as e:
            out.setdefault("errors", []).append("%s: %s" % (label, str(e)[:60]))
    # the same rule applied to the event log in Mongo
    if _USE_MONGO and not dry:
        try:
            for coll in ("login_events", "signins"):
                c = _DB[coll]
                ids = []
                for r in c.find({}, {"email": 1, "name": 1}):
                    fake, _ = CF.classify(r.get("email"), r.get("name"))
                    if fake:
                        ids.append(r["_id"])
                if ids:
                    c.delete_many({"_id": {"$in": ids}})
                    out["mongo"] += len(ids)
        except Exception as e:
            out.setdefault("errors", []).append("mongo: %s" % str(e)[:60])
    out["removed_total"] = len(out["users"]) + out["signins"] + out["events"] + out["mongo"]
    return out


def admin_list(key, delete_email=None, token=""):
    """Admin: list signed-up users (or delete one with delete_email).
    Authorised by the ADMIN_KEY env var OR a live owner session token.
    Never exposes password hashes."""
    if not _admin_ok(key, token):
        return {"ok": False, "error": "Unauthorized"}
    if delete_email:
        delete_email = delete_email.lower().strip()
        try:
            if _USE_MONGO:
                r = _DB["users"].delete_one({"email": delete_email})
                return {"ok": True, "deleted": r.deleted_count > 0}
            data = _load_json()
            gone = data.pop(delete_email, None)
            if gone:
                _save_json(data)
            return {"ok": True, "deleted": gone is not None}
        except Exception as e:
            return {"ok": False, "error": "DB error: %s" % str(e)[:80]}
    users = []
    try:
        if _USE_MONGO:
            for u in _DB["users"].find({}, {"_id": 0, "email": 1, "name": 1, "username": 1, "created": 1, "oauth": 1}):
                users.append(u)
        else:
            data = _load_json()
            for email, rec in data.items():
                users.append({"email": email, "name": rec.get("name", ""),
                              "username": rec.get("username", ""),
                              "created": rec.get("created"), "oauth": rec.get("oauth", "")})
    except Exception as e:
        return {"ok": False, "error": "DB error: %s" % str(e)[:80]}
    users.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return {"ok": True, "count": len(users), "users": users}

def admin_overview(key="", token=""):
    """The owner's at-a-glance view: every account, how it was created, when
    the newest one arrived, and which store answered."""
    if not _admin_ok(key, token):
        return {"ok": False, "error": "Unauthorized"}
    base = admin_list(key, token=token)
    if not base.get("ok"):
        return base
    users = base.get("users", [])
    by_provider = {}
    for u in users:
        p = (u.get("oauth") or "email").lower() or "email"
        by_provider[p] = by_provider.get(p, 0) + 1
    newest = max([u.get("created") or 0 for u in users] or [0])
    signins = recent_signins(400)
    last_seen = {}
    for r in signins:
        e = (r.get("email") or "").lower()
        if e and e not in last_seen:
            last_seen[e] = r.get("ts")
    for u in users:
        e = (u.get("email") or "").lower()
        u["last_signin"] = last_seen.get(e) or u.get("last_signin")
    users.sort(key=lambda r: (r.get("last_signin") or r.get("created") or 0), reverse=True)
    return {"ok": True, "count": len(users), "by_provider": by_provider,
            "newest_created": newest, "store": store_mode(), "users": users,
            "signin_count": len(signins), "signins": signins}

def handle_auth(path, q):
    """Router for /api/auth/*  (signup | login | logout | me | oauth exchange)."""
    action = path.split("/")[-1]
    if "oauth" in path and action == "exchange":
        return oauth_exchange((q.get("code") or [""])[0])
    ip = (q.get("_ip") or [""])[0]
    ua = (q.get("_ua") or [""])[0]
    if action == "signup":
        return signup((q.get("email") or [""])[0], (q.get("password") or [""])[0],
                      (q.get("name") or [""])[0], (q.get("username") or [""])[0],
                      ip=ip, user_agent=ua)
    if action == "login":
        return login((q.get("email") or [""])[0], (q.get("password") or [""])[0],
                     ip=ip, user_agent=ua)
    if action == "set_password":
        return set_password((q.get("token") or [""])[0], (q.get("password") or [""])[0])
    if action == "logout":
        return logout((q.get("token") or [""])[0])
    if action == "username":
        return set_username((q.get("token") or [""])[0], (q.get("username") or [""])[0])
    if action == "name":
        return set_name((q.get("token") or [""])[0], (q.get("name") or [""])[0])
    if action == "verify":
        return verify_signup((q.get("email") or [""])[0], (q.get("code") or [""])[0])
    if action == "purge_fakes":
        return admin_purge_fakes((q.get("key") or [""])[0], (q.get("token") or [""])[0],
                                 dry=(q.get("dry") or [""])[0].lower() in ("1", "true", "yes"))
    if action == "me":
        return me((q.get("token") or [""])[0])
    # SIGN-IN COUNTS. Every signup/login/oauth exchange has been recorded for a while,
    # but no route read it back, so "how many people are signing in" had no answer.
    # admin_overview() and the sign-in rows both already existed - they were simply
    # never reachable. Both require ADMIN_KEY or a live owner session: the counts
    # cover distinct email addresses, which is not public data.
    if action in ("admin", "overview"):
        return admin_overview((q.get("key") or [""])[0], (q.get("token") or [""])[0])
    if action == "stats":
        # HOW MANY PEOPLE ARE SIGNING IN. Every signup, password login and oauth
        # exchange already writes a row through _record_signin, but no route ever read
        # those rows back, so the question had no answer. Counts come from the same
        # recent_signins() feed admin_overview uses, the sanctioned reader.
        if not _admin_ok((q.get("key") or [""])[0], (q.get("token") or [""])[0]):
            return {"ok": False, "error": "Unauthorized"}
        rows = recent_signins(1000)
        by_day = {}
        by_provider = {}
        accounts = set()
        for r in rows:
            ts = r.get("ts") or 0
            try:
                d = time.strftime("%Y-%m-%d", time.gmtime(int(ts)))
            except Exception:
                d = "unknown"
            by_day[d] = by_day.get(d, 0) + 1
            pv = (r.get("provider") or "email")
            by_provider[pv] = by_provider.get(pv, 0) + 1
            e = (r.get("email") or "").lower()
            if e:
                accounts.add(e)
        return {"ok": True, "total": len(rows), "accounts": len(accounts),
                "by_day": dict(sorted(by_day.items())), "by_provider": by_provider,
                "recent": rows[:25]}
    return {"ok": False, "error": "Unknown auth action"}
