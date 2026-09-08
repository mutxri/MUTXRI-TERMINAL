#!/usr/bin/env python3
"""chat_room.py - shared chat room for signed-in terminal users.

MongoDB 'chat_messages' collection when available, else a local
chat_messages.json file (a capped list, newest last). Messages are only
readable/writable by authenticated sessions; ownership is by email, the
owner account can delete anything.
"""
import json, os, secrets, time, threading

_DB = None          # set by afri_server (Mongo db) if available
_USE_MONGO = False
_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_messages.json")

DEFAULT_ROOM = "main"
_MAX_TEXT = 500          # frontend maxlength is 500
_MAX_KEEP = 500          # cap stored messages per room to bound the JSON file
_LOCK = threading.Lock()


def init(db, mongo_ok):
    global _DB, _USE_MONGO
    _DB = db
    _USE_MONGO = bool(mongo_ok and db is not None)


def store_mode():
    """'mongo' when connected to MongoDB, 'json' when falling back to a file."""
    return "mongo" if _USE_MONGO else "json"


def _handle(email, name):
    """Display handle: the name when present, else the email prefix."""
    if name:
        return str(name)[:80]
    if email:
        return str(email).split("@")[0]
    return "trader"


def _load_json():
    try:
        with open(_JSON_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def _save_json(msgs):
    try:
        with open(_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False)
    except Exception:
        pass


def _all():
    """All messages (newest first), both stores."""
    if _USE_MONGO:
        try:
            # exclude _id: an ObjectId is not JSON-serialisable, and the server's
            # json() would raise on it a second time inside its own fallback,
            # turning every read of the room into a 500
            return [dict(m) for m in _DB["chat_messages"]
                    .find({}, {"_id": 0}).sort("ts", -1)]
        except Exception:
            return []
    return _load_json()


def post(email, name, text, room, ctx):
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "message is empty"}
    if len(text) > _MAX_TEXT:
        return {"ok": False, "error": "message too long (500 max)"}
    room = (str(room or "").strip()[:40] or DEFAULT_ROOM)
    msg = {
        "id": secrets.token_hex(8),
        "room": room,
        "email": (email or "").lower().strip(),
        "name": _handle(email, name),
        "text": text[:500],
        "ctx": (ctx or "").strip()[:60],
        "ts": int(time.time()),
    }
    with _LOCK:
        if _USE_MONGO:
            try:
                _DB["chat_messages"].insert_one(msg)
            except Exception:
                return {"ok": False, "error": "could not save message"}
        else:
            msgs = _load_json()
            msgs.append(msg)
            msgs = msgs[-_MAX_KEEP:]
            _save_json(msgs)
    return {"ok": True, "message": msg}


def history(room, after, limit):
    room = (str(room or "").strip()[:40] or DEFAULT_ROOM)
    after = int(after or 0)
    limit = max(1, min(int(limit or 60), 200))
    out = [m for m in _all() if m.get("room") == room and m.get("ts", 0) > after]
    out.sort(key=lambda m: m.get("ts", 0))          # oldest first
    return {"ok": True, "messages": out[-limit:]}


def delete(id, email, owner):
    email = (email or "").lower().strip()
    with _LOCK:
        if _USE_MONGO:
            try:
                m = _DB["chat_messages"].find_one({"id": id})
                if not m:
                    return {"ok": False, "error": "message not found"}
                if not (owner or m.get("email") == email):
                    return {"ok": False, "error": "not yours to delete"}
                _DB["chat_messages"].delete_one({"id": id})
                return {"ok": True}
            except Exception:
                return {"ok": False, "error": "could not delete"}
        msgs = _load_json()
        for m in msgs:
            if m.get("id") == id:
                if not (owner or m.get("email") == email):
                    return {"ok": False, "error": "not yours to delete"}
                _save_json([x for x in msgs if x.get("id") != id])
                return {"ok": True}
        return {"ok": False, "error": "message not found"}
