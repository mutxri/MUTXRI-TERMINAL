"""pro_plans.py - Pro plans and the Pro data store for the terminal backend.

PLANS
  An account is "free" unless it holds a pro_until in the future; the owner is
  always Pro. pro_until is written only by admin_set_plan (manual M-Pesa payments
  for now, a payment webhook later). The client can never set it.

DATA
  The valuations (build_valuation.py) and guidance (build_guidance.py) are paid
  data, so they never go into the public repo. They live in the backend's own
  MongoDB collection "pro_data", one document per file ({_id: "valuation/NSE_SCOM.json",
  body: {...}}), loaded through POST /api/pro/ingest. That route needs a key whose
  SHA-256 is below; the key itself is held only in the operator's
  secrets_local.json. Without Mongo (local runs) the files are read from PRO_DIR.
"""
import hashlib, hmac, json, os, time, threading

import auth_api

INGEST_KEY_SHA256 = "e2f16b8dfeb9c1073dc273554f00cbcb7369ce37fe202e5d87aff2a64a78d63d"
PRO_DIR = os.environ.get("PRO_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "pro_data")
CACHE_TTL = 300

_db = None
_cache = {}
_lock = threading.Lock()


def init(db, ok):
    global _db
    _db = db if (ok and db is not None) else None


# ---------------------------------------------------------------- plans
def plan_of(email, u=None):
    if auth_api._is_owner(email):
        return "pro", None
    u = u if u is not None else (auth_api._find_user(email) or {})
    try:
        until = float((u or {}).get("pro_until") or 0)
    except Exception:
        until = 0.0
    return ("pro" if until > time.time() else "free"), (until or None)


def pro_session(token):
    """{'email', 'plan', 'pro_until'} for a live session, else None."""
    s = auth_api._live(token) if token else None
    if not s:
        return None
    plan, until = plan_of(s["email"])
    return {"email": s["email"], "plan": plan, "pro_until": until}


def admin_set_plan(key, token, email, days):
    """Owner or ADMIN_KEY only: Pro for N days from now (or from the end of the
    current Pro period); days=0 removes it. Every change is kept in plan_history."""
    if not auth_api._admin_ok(key, token):
        return {"ok": False, "error": "Unauthorized"}
    email = (email or "").lower().strip()
    u = auth_api._find_user(email)
    if not u:
        return {"ok": False, "error": "No account for that address"}
    try:
        days = float(days)
    except Exception:
        return {"ok": False, "error": "days must be a number"}
    now = time.time()
    until = 0 if days <= 0 else max(now, float(u.get("pro_until") or 0)) + days * 86400
    hist = list(u.get("plan_history") or [])
    hist.append({"at": now, "days": days, "until": until})
    auth_api._update_user(email, {"pro_until": until, "plan_history": hist[-50:]})
    plan, until = plan_of(email)
    return {"ok": True, "email": email, "plan": plan, "pro_until": until}


# ---------------------------------------------------------------- data
def _safe(path):
    return bool(path) and ".." not in path and not path.startswith("/") and path.endswith(".json") \
        and all(c.isalnum() or c in "._-/" for c in path)


def get(path):
    """One Pro data file by its relative path ("valuation/NSE_SCOM.json"), or None."""
    if not _safe(path):
        return None
    now = time.time()
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] > now:
            return hit[1]
    body = None
    if _db is not None:
        try:
            doc = _db["pro_data"].find_one({"_id": path})
            body = doc.get("body") if doc else None
        except Exception:
            body = None
    else:
        p = os.path.realpath(os.path.join(PRO_DIR, path))
        if p.startswith(os.path.realpath(PRO_DIR) + os.sep):
            try:
                with open(p, encoding="utf-8") as f:
                    body = json.load(f)
            except Exception:
                body = None
    with _lock:
        _cache[path] = (now + CACHE_TTL, body)
    return body


def ingest(key, files):
    """Store {path: body} in Mongo. Needs the ingest key."""
    if not key or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), INGEST_KEY_SHA256):
        return {"ok": False, "error": "Unauthorized"}
    if _db is None:
        return {"ok": False, "error": "no database on this server"}
    if not isinstance(files, dict) or not files:
        return {"ok": False, "error": "files must be a non-empty object"}
    from pymongo import ReplaceOne
    ops, bad = [], []
    for path, body in files.items():
        if not _safe(path) or not isinstance(body, (dict, list)):
            bad.append(path)
            continue
        ops.append(ReplaceOne({"_id": path}, {"_id": path, "body": body, "at": time.time()}, upsert=True))
    if ops:
        _db["pro_data"].bulk_write(ops, ordered=False)
    with _lock:
        _cache.clear()
    return {"ok": True, "stored": len(ops), "rejected": bad}


def stats():
    if _db is None:
        return {"store": "files"}
    try:
        return {"store": "mongo", "documents": _db["pro_data"].estimated_document_count()}
    except Exception as e:
        return {"store": "mongo", "error": str(e)[:80]}
