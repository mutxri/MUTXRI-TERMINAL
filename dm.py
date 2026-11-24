"""dm.py - direct messages between two signed-in accounts.

HOW A CONVERSATION IS ADDRESSED, AND WHY IT IS NOT ADDRESSED BY ROOM NAME.
The room endpoints take whatever room name the caller sends, which is correct
for public rooms: they are public. A direct message is not, so a caller is never
allowed to name the room. The caller names the OTHER PERSON, by handle, and the
room id is computed here from the caller's own verified email and that person's,
sorted and hashed. Two consequences, both deliberate:

  * You can only ever address a conversation that has your own verified email in
    it. There is no room id a caller could send that would reach a conversation
    they are not part of, because they do not send one.
  * The id is a hash, so the stored room field on a message is not a pair of
    email addresses sitting in the database waiting to be read.

WHAT GOES BACK TO A CLIENT. Handles, text, timestamps and ids. Never an email
address. The public room's history does return the author's email today, which
is a leak in its own right, and this module does not copy it.

A thread is "mine" if I wrote a message in it or one was addressed to me, which
is why every direct message stores dmTo: without it a conversation where only
the other person has written could not be found from a hashed room id.
"""

import hashlib
import time

import chat_room
import auth_api

MAX_TEXT = 500


def _norm(e):
    return str(e or "").strip().lower()


def room_id(a_email, b_email):
    """The canonical room for two accounts. Order does not matter."""
    a, b = _norm(a_email), _norm(b_email)
    if not a or not b or a == b:
        return ""
    lo, hi = sorted([a, b])
    seed = "mutxri-dm|%s|%s" % (lo, hi)
    return "dm:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def handle_of(user):
    u = user or {}
    return chat_room._handle(u.get("email"), u.get("name"), u.get("username"))


def find_by_handle(h):
    """The account whose chat handle is `h`, or None. Case-insensitive."""
    want = str(h or "").strip().lower()
    if not want:
        return None
    for u in auth_api._all_users():
        try:
            if handle_of(u).strip().lower() == want:
                return u
        except Exception:
            continue
    return None


def _clean(m, me_email):
    """One message, as a client may see it. No addresses."""
    return {
        "id": m.get("id"),
        "name": m.get("name"),
        "text": m.get("text"),
        "ts": m.get("ts"),
        "image": m.get("image") or "",
        "mine": _norm(m.get("email")) == _norm(me_email),
    }


def send(me_email, me_name, me_username, to_handle, text, image=""):
    text = str(text or "").strip()
    if not text and not image:
        return {"ok": False, "error": "message is empty"}
    if len(text) > MAX_TEXT:
        return {"ok": False, "error": "message too long (500 max)"}

    other = find_by_handle(to_handle)
    if not other:
        # Named rather than silently dropped: a message that goes nowhere while
        # the sender watches it appear in their own thread is worse than an error.
        return {"ok": False, "error": "no signed-in account uses the handle @%s"
                                      % str(to_handle or "")[:40]}
    other_email = _norm(other.get("email"))
    if other_email == _norm(me_email):
        return {"ok": False, "error": "that is your own handle"}

    room = room_id(me_email, other_email)
    if not room:
        return {"ok": False, "error": "this conversation could not be addressed"}

    res = chat_room.post(me_email, me_name, text, room, "", me_username,
                         "", False, image, extra={"dmTo": other_email})
    if not res.get("ok"):
        return res
    return {"ok": True, "message": _clean(res.get("message") or {}, me_email),
            "with": handle_of(other)}


def history(me_email, with_handle, after=0, limit=60):
    other = find_by_handle(with_handle)
    if not other:
        return {"ok": False, "error": "no signed-in account uses that handle"}
    room = room_id(me_email, other.get("email"))
    if not room:
        return {"ok": False, "error": "this conversation could not be addressed"}
    after = int(after or 0)
    limit = max(1, min(int(limit or 60), 200))
    rows = [m for m in chat_room._all()
            if m.get("room") == room and int(m.get("ts") or 0) > after]
    rows.sort(key=lambda m: int(m.get("ts") or 0))
    rows = rows[-limit:]
    return {"ok": True, "with": handle_of(other),
            "messages": [_clean(m, me_email) for m in rows]}


def threads(me_email):
    """Every conversation this account is part of, newest first."""
    me = _norm(me_email)
    if not me:
        return {"ok": False, "error": "not signed in"}
    # room -> the other account's email, and the newest message seen in it
    seen = {}
    for m in chat_room._all():
        room = str(m.get("room") or "")
        if not room.startswith("dm:"):
            continue
        author = _norm(m.get("email"))
        to = _norm(m.get("dmTo"))
        if me not in (author, to):
            continue
        other = to if author == me else author
        ts = int(m.get("ts") or 0)
        cur = seen.get(room)
        if cur is None or ts > cur["ts"]:
            seen[room] = {"ts": ts, "other": other,
                          "text": str(m.get("text") or "")[:90],
                          "fromMe": author == me}
        elif not cur.get("other"):
            cur["other"] = other

    out = []
    for room in seen:
        v = seen[room]
        u = auth_api._find_user(v["other"]) if v["other"] else None
        if not u:
            continue
        out.append({"with": handle_of(u), "ts": v["ts"],
                    "preview": v["text"], "fromMe": v["fromMe"]})
    out.sort(key=lambda r: r["ts"], reverse=True)
    return {"ok": True, "threads": out[:40]}


def directory(me_email, q="", limit=25):
    """Handles a message can be addressed to. HANDLES ONLY, never addresses.

    This is the one place the product turns its account list into something a
    user can see, so it returns the chat handle and nothing else: no name, no
    address, no count of anything.
    """
    me = _norm(me_email)
    want = str(q or "").strip().lower()
    out = []
    for u in auth_api._all_users():
        try:
            if _norm(u.get("email")) == me:
                continue
            h = handle_of(u)
            if not h:
                continue
            if want and want not in h.lower():
                continue
            out.append(h)
        except Exception:
            continue
    out = sorted(set(out), key=lambda x: x.lower())
    return {"ok": True, "handles": out[:max(1, min(int(limit or 25), 100))]}
