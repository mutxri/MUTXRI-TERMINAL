#!/usr/bin/env python3
"""login_log.py - durable record of every sign-in attempt.

Writes one document per authentication event to the MongoDB `login_events`
collection, sharing the connection auth_api already holds rather than opening a
second one. With Mongo unavailable it falls back to a capped JSON file so local
development and a mis-configured deploy still record something.

What it stores
    email, provider, event, ok, ts, ip, device, user_agent, new_device
What it never stores
    passwords, password hashes, session tokens, OAuth tokens

Failed attempts are recorded as well as successful ones - a login log that only
contains successes cannot show you a credential-stuffing run against an account,
which is most of the reason to keep one.

Events older than LOGIN_LOG_TTL_DAYS (default 180) are removed automatically by
a Mongo TTL index. Keeping sign-in history forever is a liability, not an asset.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

_DB = None
_USE_MONGO = False
_INDEXED = False
_LOCK = threading.Lock()

COLLECTION = "login_events"
_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_events.json")
_JSON_MAX = 2000          # keep the fallback file bounded
TTL_DAYS = int(os.environ.get("LOGIN_LOG_TTL_DAYS", "180"))


def init(db, mongo_ok):
    """Called once at startup with the same handle auth_api receives."""
    global _DB, _USE_MONGO, _INDEXED
    _DB = db
    _USE_MONGO = bool(mongo_ok and db is not None)
    _INDEXED = False
    if _USE_MONGO:
        _ensure_indexes()
    print("[login_log] store: %s" % ("mongo" if _USE_MONGO else "json"), flush=True)


def _ensure_indexes():
    """One compound index for 'show me this account's history', one TTL index so
    old rows expire on their own."""
    global _INDEXED
    if _INDEXED or not _USE_MONGO:
        return
    try:
        coll = _DB[COLLECTION]
        coll.create_index([("email", 1), ("ts", -1)], name="email_ts")
        coll.create_index("at", name="ttl_at", expireAfterSeconds=TTL_DAYS * 86400)
        _INDEXED = True
    except Exception as exc:
        print("[login_log] index setup skipped: %s" % str(exc)[:90], flush=True)


def _append_json(doc):
    with _LOCK:
        try:
            with open(_JSON_PATH, encoding="utf-8") as fh:
                rows = json.load(fh)
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
        rows.append(doc)
        rows = rows[-_JSON_MAX:]
        tmp = _JSON_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
        os.replace(tmp, _JSON_PATH)   # atomic; a crash mid-write cannot truncate the log


def record(email, provider="password", event="login", ok=True,
           ip="", user_agent="", device="", new_device=False, detail=""):
    """Write one event. Never raises - logging must not be able to fail a
    sign-in, and must not fail a rejected sign-in either."""
    email = (email or "").lower().strip()
    now = time.time()
    doc = {
        "email": email,
        "provider": provider,
        "event": event,                  # signup | login | oauth
        "ok": bool(ok),
        "ts": now,
        "at": datetime.fromtimestamp(now, timezone.utc),   # real date, for the TTL index
        "ip": (ip or "").strip()[:45],
        "device": (device or "")[:60],
        "user_agent": (user_agent or "")[:300],
        "new_device": bool(new_device),
    }
    if detail:
        doc["detail"] = str(detail)[:120]

    try:
        if _USE_MONGO:
            _ensure_indexes()
            _DB[COLLECTION].insert_one(dict(doc))
        else:
            doc["at"] = doc["at"].isoformat()             # JSON has no datetime
            _append_json(doc)
    except Exception as exc:
        print("[login_log] write failed for %s: %s" % (email, str(exc)[:90]), flush=True)
    return doc


def history(email, limit=20):
    """Recent events for one account, newest first."""
    email = (email or "").lower().strip()
    if not email:
        return []
    try:
        if _USE_MONGO:
            cur = _DB[COLLECTION].find({"email": email}, {"_id": 0}).sort("ts", -1).limit(int(limit))
            return list(cur)
        with open(_JSON_PATH, encoding="utf-8") as fh:
            rows = [r for r in json.load(fh) if r.get("email") == email]
        return sorted(rows, key=lambda r: r.get("ts", 0), reverse=True)[:int(limit)]
    except Exception as exc:
        print("[login_log] history failed: %s" % str(exc)[:90], flush=True)
        return []


def recent_failures(email, within_seconds=900):
    """Failed attempts in the last window - the number a lockout rule wants."""
    email = (email or "").lower().strip()
    cutoff = time.time() - within_seconds
    try:
        if _USE_MONGO:
            return _DB[COLLECTION].count_documents(
                {"email": email, "ok": False, "ts": {"$gte": cutoff}})
        with open(_JSON_PATH, encoding="utf-8") as fh:
            rows = json.load(fh)
        return sum(1 for r in rows
                   if r.get("email") == email and not r.get("ok") and r.get("ts", 0) >= cutoff)
    except Exception:
        return 0


def summary(limit=200):
    """Counts for an admin view: who signed in, how, and how often it failed."""
    out = {"store": "mongo" if _USE_MONGO else "json", "total": 0,
           "ok": 0, "failed": 0, "by_provider": {}, "accounts": 0}
    try:
        if _USE_MONGO:
            coll = _DB[COLLECTION]
            out["total"] = coll.count_documents({})
            out["ok"] = coll.count_documents({"ok": True})
            out["failed"] = coll.count_documents({"ok": False})
            out["accounts"] = len(coll.distinct("email"))
            for prov in coll.distinct("provider"):
                out["by_provider"][prov] = coll.count_documents({"provider": prov})
        else:
            with open(_JSON_PATH, encoding="utf-8") as fh:
                rows = json.load(fh)[-int(limit):]
            out["total"] = len(rows)
            out["ok"] = sum(1 for r in rows if r.get("ok"))
            out["failed"] = out["total"] - out["ok"]
            out["accounts"] = len({r.get("email") for r in rows})
            for r in rows:
                p = r.get("provider", "?")
                out["by_provider"][p] = out["by_provider"].get(p, 0) + 1
    except Exception as exc:
        out["error"] = str(exc)[:90]
    return out
