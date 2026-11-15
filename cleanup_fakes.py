#!/usr/bin/env python3
"""cleanup_fakes.py - remove bot and test signups, keep the real ones.

WHAT COUNTS AS FAKE, and why each rule is here:
  1. A domain that cannot belong to a real person: example.com/.org/.net, test.*,
     localhost, invalid, and the disposable-inbox services (mailinator, yopmail,
     tempmail, guerrillamail, 10minutemail, trashmail, dispostable, spam4.me ...).
     These are the addresses a script or a test run types, not a customer.
  2. A test-shaped local part (test, testing, signup, signup1, bot, fake, dummy,
     sample, demo, foo, bar, asdf, qwerty, user1, no-reply, noreply) on ANY domain,
     because "test@<anything>" is a fixture, not a person.
  3. A name that is a fixture: "Test User", "Signup Person", "Bot", "asdf".
  4. A Gmail address that duplicates a real one under Google's own rules: dots are
     ignored and "+tag" is ignored, so j.o.h.n+x@gmail.com is the same mailbox as
     john@gmail.com. The earliest account keeps the mailbox; later duplicates go.

Anything not matched is KEPT. This never guesses: an address it cannot classify as
fake stays, and the count of kept rows is printed so the result is checkable.

Usage:
  python cleanup_fakes.py --dry     report what would go, change nothing
  python cleanup_fakes.py           delete the fakes from users.json / signins.json
                                    / login_events.json, and from MongoDB when
                                    MONGODB_URI is set
"""
import json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
USERS = os.path.join(HERE, "users.json")
SIGNINS = os.path.join(HERE, "signins.json")
EVENTS = os.path.join(HERE, "login_events.json")

BAD_DOMAINS = {
    "example.com", "example.org", "example.net", "test.com", "test.org",
    "localhost", "invalid", "test", "domain.com", "email.com", "yourdomain.com",
    "mailinator.com", "yopmail.com", "guerrillamail.com", "sharklasers.com",
    "10minutemail.com", "tempmail.com", "temp-mail.org", "throwawaymail.com",
    "trashmail.com", "dispostable.com", "spam4.me", "getnada.com", "maildrop.cc",
    "fakeinbox.com", "mytemp.email", "moakt.com", "tempr.email",
}
BAD_LOCAL = {
    "test", "tests", "testing", "test1", "test2", "tester", "signup", "signup1",
    "signups", "bot", "bots", "fake", "dummy", "sample", "demo", "foo", "bar",
    "asdf", "qwerty", "abc", "xyz", "user", "user1", "user2", "noreply",
    "no-reply", "no_reply", "donotreply", "none", "null", "a", "t", "testuser",
}
BAD_NAMES = {"test user", "signup person", "test", "bot", "asdf", "demo user", "fake user"}


def split(addr):
    a = (addr or "").strip().lower()
    if "@" not in a:
        return a, ""
    local, _, dom = a.rpartition("@")
    return local, dom


def gmail_key(local, dom):
    """Google ignores dots and everything from + on, in gmail.com only."""
    if dom not in ("gmail.com", "googlemail.com"):
        return None
    return local.split("+", 1)[0].replace(".", "")


def classify(email, name=""):
    """Return (is_fake, reason). Anything not positively identified is real."""
    local, dom = split(email)
    if not local or not dom:
        return True, "not an address"
    if dom in BAD_DOMAINS:
        return True, "domain " + dom
    if local in BAD_LOCAL:
        return True, "local part " + local
    if re.fullmatch(r"(test|signup|bot)[0-9]*", local):
        return True, "test-shaped local part"
    if (name or "").strip().lower() in BAD_NAMES:
        return True, "fixture name " + name
    return False, ""


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def purge_users(dry):
    d = _load(USERS, {})
    if isinstance(d, dict) and "users" not in d and isinstance(next(iter(d.values()), None), dict):
        rows = list(d.values())
        is_map = True
    else:
        rows = d.get("users") if isinstance(d, dict) else d
        is_map = False
    rows = rows or []
    keep, gone = [], []
    seen_gmail = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        email = r.get("email") or ""
        fake, why = classify(email, r.get("name"))
        local, dom = split(email)
        if not fake:
            key = gmail_key(local, dom)
            if key:
                if key in seen_gmail:
                    fake, why = True, "duplicate gmail mailbox of " + seen_gmail[key]
                else:
                    seen_gmail[key] = email
        (gone if fake else keep).append((email, why) if fake else email)
    print("  users.json: %d total | keep %d | delete %d" % (len(rows), len(keep), len(gone)))
    for e, why in gone[:20]:
        print("     del", e, "|", why)
    if gone and not dry:
        if is_map:
            d = {k: v for k, v in d.items() if (v.get("email") if isinstance(v, dict) else k) not in dict(gone)}
        elif isinstance(d, dict):
            d["users"] = [r for r in rows if r.get("email") not in dict(gone)]
        else:
            d = [r for r in rows if r.get("email") not in dict(gone)]
        _save(USERS, d)
        print("     written")
    return len(gone)


def purge_list(path, label, dry):
    d = _load(path, [])
    rows = d.get("items") if isinstance(d, dict) else d
    rows = rows or []
    keep, gone = [], []
    for r in rows:
        email = (r.get("email") if isinstance(r, dict) else str(r)) or ""
        name = r.get("name") if isinstance(r, dict) else ""
        fake, why = classify(email, name)
        (gone.append((email, why)) if fake else keep.append(r))
    print("  %s: %d total | keep %d | delete %d" % (label, len(rows), len(keep), len(gone)))
    for e, why in gone[:20]:
        print("     del", e, "|", why)
    if gone and not dry:
        if isinstance(d, dict):
            d["items"] = keep
            _save(path, d)
        else:
            _save(path, keep)
        print("     written")
    return len(gone)


def purge_mongo(dry):
    uri = os.environ.get("MONGODB_URI", "")
    if not uri:
        print("  Mongo: MONGODB_URI not set, skipped")
        return 0
    try:
        from pymongo import MongoClient
    except Exception as e:
        print("  Mongo: pymongo missing (%s), skipped" % e)
        return 0
    cli = MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = cli.get_default_database()
    total = 0
    for coll in ("login_events", "users", "signins"):
        c = db[coll]
        rows = list(c.find({}, {"email": 1, "name": 1}))
        ids, shown = [], 0
        for r in rows:
            fake, why = classify(r.get("email"), r.get("name"))
            if fake:
                ids.append(r["_id"])
                if shown < 10:
                    print("     del", r.get("email"), "|", why)
                    shown += 1
        print("  mongo.%s: %d rows | delete %d" % (coll, len(rows), len(ids)))
        if ids and not dry:
            c.delete_many({"_id": {"$in": ids}})
            print("     written")
        total += len(ids)
    return total


def main():
    dry = "--dry" in sys.argv
    print("cleanup_fakes: %s" % ("DRY RUN, nothing is written" if dry else "live, files will be rewritten"))
    n = 0
    n += purge_users(dry)
    n += purge_list(SIGNINS, "signins.json", dry)
    n += purge_list(EVENTS, "login_events.json", dry)
    n += purge_mongo(dry)
    print("  TOTAL fake rows %s: %d" % ("identified" if dry else "deleted", n))
    if not dry and n:
        print("  backup kept as users.json.bak_<stamp> style copies are NOT made: commit the change or re-run --dry to review")


if __name__ == "__main__":
    main()
