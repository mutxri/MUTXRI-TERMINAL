#!/usr/bin/env python3
"""chat_room.py - the terminal's shared chat room.

One public room every signed-in user reads and writes, so people on the desk can
see what everyone else makes of the market. Messages live in the MongoDB
`chat_messages` collection when Mongo is configured, sharing the connection
auth_api already holds, and fall back to a capped JSON file otherwise so local
development and a mis-configured deploy still work.

What it stores
    id, ts, room, name (display handle), text, ctx (what the sender was looking
    at, e.g. "NSE SCOM"), and the author's email
What it never returns to the room
    the author's email address - everyone sees a display handle, never each
    other's address. A room that leaks every subscriber's email is a mailing
    list you did not agree to join.

Messages older than CHAT_TTL_DAYS (default 30) are removed automatically by a
Mongo TTL index; the JSON fallback is capped at _JSON_MAX rows.
"""
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

_DB = None
_USE_MONGO = False
_INDEXED = False
_LOCK = threading.Lock()

COLLECTION = "chat_messages"
_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_messages.json")
_JSON_MAX = 1000           # keep the fallback file bounded
TTL_DAYS = int(os.environ.get("CHAT_TTL_DAYS", "30"))

MAX_TEXT = 500             # one message
MAX_FETCH = 200            # one poll
ROOM_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
CTX_RE = re.compile(r"[^A-Za-z0-9 .:_-]")
DEFAULT_ROOM = "global"


def init(db, mongo_ok):
    """Called once at startup with the same handle auth_api receives."""
    global _DB, _USE_MONGO, _INDEXED
    _DB = db
    _USE_MONGO = bool(mongo_ok and db is not None)
    _INDEXED = False
    if _USE_MONGO:
        _ensure_indexes()
    print("[chat_room] store: %s" % ("mongo" if _USE_MONGO else "json"), flush=True)


def _ensure_indexes():
    """One index for 'the newest messages in this room', one TTL index so old
    chatter expires on its own."""
    global _INDEXED
    if _INDEXED or not _USE_MONGO:
        return
    try:
        coll = _DB[COLLECTION]
        coll.create_index([("room", 1), ("ts", -1)], name="room_ts")
        coll.create_index("at", name="ttl_at", expireAfterSeconds=TTL_DAYS * 86400)
        _INDEXED = True
    except Exception as exc:
        print("[chat_room] index setup failed: %s" % str(exc)[:80], flush=True)


def store_mode():
    return "mongo" if _USE_MONGO else "json"


# ---------------- helpers ----------------

def _clean_room(room):
    room = (room or DEFAULT_ROOM).strip()
    return room if ROOM_RE.match(room) else DEFAULT_ROOM


def _clean_text(text):
    """Collapse control characters and trim. Markup is NOT stripped here - the
    client escapes on render - but newlines survive so a quote reads as one."""
    t = str(text or "")
    t = "".join(ch for ch in t if ch == "\n" or ord(ch) >= 32)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:MAX_TEXT]


def _clean_ctx(ctx):
    return CTX_RE.sub("", str(ctx or ""))[:24].strip()


def _handle(email, name):
    """The public display name: the account's own name when it set one, else the
    local part of the address. Never the full address."""
    n = (name or "").strip()
    if n:
        return n[:32]
    local = str(email or "").split("@")[0]
    return (local or "trader")[:32]


def _public(doc):
    """The shape the room sees - author email deliberately absent."""
    return {
        "id": doc.get("id"),
        "ts": doc.get("ts"),
        "room": doc.get("room"),
        "name": doc.get("name"),
        "text": doc.get("text"),
        "ctx": doc.get("ctx") or "",
    }


# ---------------- JSON fallback ----------------

def _json_load():
    try:
        with open(_JSON_PATH, encoding="utf-8") as f:
            rows = json.load(f)
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _json_save(rows):
    tmp = _JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows[-_JSON_MAX:], f, ensure_ascii=False)
    os.replace(tmp, _JSON_PATH)


# ---------------- API ----------------

def post(email, name, text, room=DEFAULT_ROOM, ctx=""):
    """Append one message. The caller has already checked the session token."""
    text = _clean_text(text)
    if not text:
        return {"ok": False, "error": "empty message"}
    doc = {
        "id": "%d-%s" % (int(time.time() * 1000), secrets.token_hex(3)),
        "ts": time.time(),
        "at": datetime.now(timezone.utc),
        "room": _clean_room(room),
        "email": str(email or "").lower(),
        "name": _handle(email, name),
        "text": text,
        "ctx": _clean_ctx(ctx),
    }
    try:
        if _USE_MONGO:
            _ensure_indexes()
            _DB[COLLECTION].insert_one(dict(doc))
        else:
            with _LOCK:
                rows = _json_load()
                rows.append({k: v for k, v in doc.items() if k != "at"})
                _json_save(rows)
    except Exception as exc:
        print("[chat_room] post failed: %s" % str(exc)[:80], flush=True)
        return {"ok": False, "error": "could not save message"}
    return {"ok": True, "message": _public(doc)}


def history(room=DEFAULT_ROOM, after=0.0, limit=60):
    """Messages newer than `after` (a unix timestamp), oldest first.

    `after` of 0 means 'the tail of the room' - what a newcomer should see on
    opening it - so the client never has to ask for the whole history.
    """
    room = _clean_room(room)
    try:
        after = float(after or 0)
    except (TypeError, ValueError):
        after = 0.0
    try:
        limit = max(1, min(MAX_FETCH, int(limit or 60)))
    except (TypeError, ValueError):
        limit = 60
    rows = []
    try:
        if _USE_MONGO:
            _ensure_indexes()
            q = {"room": room}
            if after > 0:
                q["ts"] = {"$gt": after}
            cur = _DB[COLLECTION].find(q).sort("ts", -1).limit(limit)
            rows = list(cur)[::-1]
        else:
            with _LOCK:
                rows = [r for r in _json_load() if r.get("room") == room]
            if after > 0:
                rows = [r for r in rows if float(r.get("ts") or 0) > after]
            rows = rows[-limit:]
    except Exception as exc:
        print("[chat_room] history failed: %s" % str(exc)[:80], flush=True)
        return {"ok": False, "error": "chat unavailable", "messages": [], "now": time.time()}
    return {"ok": True, "room": room, "messages": [_public(r) for r in rows], "now": time.time()}


def delete(msg_id, requester_email, is_owner=False):
    """Remove one message. Its author can always delete it; the owner can delete
    anyone's - a public room with no way to take something down is a liability."""
    msg_id = str(msg_id or "")[:64]
    who = str(requester_email or "").lower()
    if not msg_id or not who:
        return {"ok": False, "error": "not allowed"}
    try:
        if _USE_MONGO:
            doc = _DB[COLLECTION].find_one({"id": msg_id})
            if not doc:
                return {"ok": False, "error": "no such message"}
            if not is_owner and str(doc.get("email") or "").lower() != who:
                return {"ok": False, "error": "not your message"}
            _DB[COLLECTION].delete_one({"id": msg_id})
        else:
            with _LOCK:
                rows = _json_load()
                keep, found, allowed = [], False, False
                for r in rows:
                    if r.get("id") == msg_id:
                        found = True
                        if is_owner or str(r.get("email") or "").lower() == who:
                            allowed = True
                            continue
                    keep.append(r)
                if not found:
                    return {"ok": False, "error": "no such message"}
                if not allowed:
                    return {"ok": False, "error": "not your message"}
                _json_save(keep)
    except Exception as exc:
        print("[chat_room] delete failed: %s" % str(exc)[:80], flush=True)
        return {"ok": False, "error": "could not delete message"}
    return {"ok": True, "id": msg_id}
