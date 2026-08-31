#!/usr/bin/env python3
"""auth_api.py - email accounts for the terminal.
Signup/login/logout with pbkdf2-hashed passwords (stdlib only) and
token sessions. Users stored in MongoDB 'users' collection when available,
else a local users.json file. NEVER stores plaintext passwords."""
import hashlib, hmac, json, os, re, secrets, time

_DB = None          # set by afri_server (Mongo db) if available
_USE_MONGO = False
_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SESSIONS = {}  # token -> {email, exp}

def _init(db, mongo_ok):
    global _DB, _USE_MONGO
    _DB = db
    _USE_MONGO = bool(mongo_ok and db is not None)

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
        u = _DB["users"].find_one({"email": email})
        return dict(u) if u else None
    return _load_json().get(email)

def _save_user(record):
    if _USE_MONGO:
        _DB["users"].replace_one({"email": record["email"]}, record, upsert=True)
    else:
        data = _load_json()
        data[record["email"]] = record
        _save_json(data)

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

def _send_confirmation_email(email, name):
    """Send a confirmation email on signup via SES SMTP (env-configured).
    Non-blocking: failures are logged, never fail the signup."""
    try:
        import smtplib, ssl, os, html as _html
        from email.mime.text import MIMEText
        server = os.environ.get("SES_SERVER", "")
        user = os.environ.get("SES_USER", "")
        pwd = os.environ.get("SES_PASS", "")
        sender = os.environ.get("BRIEF_FROM", "jimmy@mutxri.com")
        if not server or not user or not pwd:
            return  # email not configured - skip silently
        first = (name or email).split()[0] if (name or "").strip() else email
        first = _html.escape(first)  # never let a user-supplied name inject HTML into the email
        html = f"""<div style="background:#000;color:#f0f0f0;font-family:monospace;padding:32px">
  <h2 style="color:#33e29a">MUTXRI TERMINAL</h2>
  <p>Hi {first},</p>
  <p>Your MUTXRI TERMINAL account has been created. Welcome to African markets intelligence.</p>
  <p style="color:#9a9a9a">You can now log in at <a href="https://mutxriterminal.com" style="color:#33e29a">mutxriterminal.com</a> and start exploring 1,021 securities across the JSE, NGX, NSE and EGX.</p>
  <p style="color:#6a6a6a;font-size:12px">This is a confirmation email for your account — no action needed. If you did not create this account, reply and we will remove it.</p>
</div>"""
        msg = MIMEText(html, "html")
        msg["Subject"] = "Welcome to MUTXRI TERMINAL — account confirmed"
        msg["From"] = sender
        msg["To"] = email
        ctx = ssl.create_default_context()
        with smtplib.SMTP(server, int(os.environ.get("SES_PORT", "587")), timeout=30) as s:
            s.starttls(context=ctx)
            s.login(user, pwd)
            s.sendmail(sender, [email], msg.as_string())
    except Exception as e:
        print(f"[auth] confirmation email failed for {email}: {str(e)[:80]}", flush=True)


def signup(email, password, name=""):
    email = (email or "").lower().strip()
    if not _EMAIL_RE.match(email):
        return {"ok": False, "error": "valid email required"}
    if not password or len(password) < 8:
        return {"ok": False, "error": "password must be at least 8 characters"}
    if _find_user(email):
        return {"ok": False, "error": "an account with this email already exists"}
    record = {
        "email": email,
        "name": (name or "").strip()[:80],
        "pw": _hash_password(password),
        "created": time.time(),
    }
    _save_user(record)
    # fire the confirmation email in a background thread (never blocks signup)
    try:
        import threading
        threading.Thread(target=_send_confirmation_email, args=(email, record["name"]), daemon=True).start()
    except Exception:
        pass
    token = secrets.token_hex(32)
    _SESSIONS[token] = {"email": email, "exp": time.time() + 30 * 86400}
    return {"ok": True, "token": token, "email": email, "name": record["name"]}

def login(email, password):
    email = (email or "").lower().strip()
    u = _find_user(email)
    if not u or not _check_password(password, u.get("pw", "")):
        return {"ok": False, "error": "invalid email or password"}
    token = secrets.token_hex(32)
    _SESSIONS[token] = {"email": email, "exp": time.time() + 30 * 86400}
    return {"ok": True, "token": token, "email": email, "name": u.get("name", "")}

def logout(token):
    if token:
        _SESSIONS.pop(token, None)
    return {"ok": True}

def me(token):
    if not token:
        return {"ok": False, "error": "not logged in"}
    s = _SESSIONS.get(token)
    if not s or s["exp"] < time.time():
        _SESSIONS.pop(token, None)
        return {"ok": False, "error": "session expired"}
    u = _find_user(s["email"])
    return {"ok": True, "email": s["email"], "name": (u or {}).get("name", "")}

def handle_auth(path, q):
    """Router for /api/auth/*  (signup | login | logout | me)."""
    action = path.split("/")[-1]
    if action == "signup":
        return signup((q.get("email") or [""])[0], (q.get("password") or [""])[0], (q.get("name") or [""])[0])
    if action == "login":
        return login((q.get("email") or [""])[0], (q.get("password") or [""])[0])
    if action == "logout":
        return logout((q.get("token") or [""])[0])
    if action == "me":
        return me((q.get("token") or [""])[0])
    return {"ok": False, "error": "unknown auth action"}
