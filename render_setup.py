"""
render_setup.py — permanent MongoDB env fix for MUTXRI-TERMINAL (Render).
Run this in YOUR OWN terminal on this machine. Secrets you type here never
leave this machine and never go through chat.

What it does:
  1. asks for your Render API key (one time; saved to secrets_local.json, gitignored)
  2. asks for the Atlas database-user password (never saved)
  3. builds the MONGODB_URI with the password URL-encoded (kills the ? trap)
  4. reads the service's current env vars via the Render API and merges the URI
     in (keeps GOOGLE_CLIENT_ID / SECRET / OAUTH_BASE untouched)
  5. triggers a deploy and polls /api/health until "db": "mongo" (or fails loudly)

Usage:
  cd /d D:\mutxri-terminal
  python render_setup.py
"""
import json, os, sys, time, urllib.request, urllib.parse, getpass

BASE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(BASE, "secrets_local.json")
API = "https://api.render.com/v1"
SERVICE_NAME = "MUTXRI-TERMINAL"
HEALTH = "https://mutxri-terminal.onrender.com/api/health"
USER = "jimmymuturi99_db_user"
HOST = "terminaldatabase.5p16fjt.mongodb.net"


def api(url, token, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8", "replace")
        return (r.status, json.loads(raw)) if raw.strip() else (r.status, {})


def main():
    # --- secrets -------------------------------------------------------
    token = ""
    if os.path.exists(SECRETS):
        try:
            token = json.load(open(SECRETS, encoding="utf-8")).get("render_api_key", "")
        except Exception:
            token = ""
    if not token:
        token = input("Render API key (Account Settings > API Keys > Create): ").strip()
        sec = {}
        if os.path.exists(SECRETS):
            try:
                sec = json.load(open(SECRETS, encoding="utf-8"))
            except Exception:
                sec = {}
        sec["render_api_key"] = token
        json.dump(sec, open(SECRETS, "w", encoding="utf-8"))
        print("API key saved to secrets_local.json (gitignored).")
    pw = getpass.getpass("Atlas password for %s: " % USER)

    # --- find the service ----------------------------------------------
    _, svcs = api(API + "/services", token)
    svc = next((s for s in svcs if s.get("name", "").upper() == SERVICE_NAME), None)
    if not svc:
        svc = next((s for s in svcs if "mutxri" in s.get("name", "").lower()), None)
    if not svc:
        print("FAIL: no Render service found. Check the API key has service access.")
        sys.exit(1)
    sid = svc["id"]
    print("Service:", svc["name"], "|", sid)

    # --- build URI with URL-encoded password -----------------------------
    uri = "mongodb+srv://%s:%s@%s/?appName=TERMINALDATABASE" % (USER, urllib.parse.quote(pw, safe=""), HOST)

    # --- read current env vars, merge MONGODB_URI ------------------------
    _, envs = api(API + "/services/%s/env-vars" % sid, token)
    print("Current env keys:", sorted(e["key"] for e in envs))
    merged = [e for e in envs if e["key"] != "MONGODB_URI"]
    merged.append({"key": "MONGODB_URI", "value": uri})
    _, res = api(API + "/services/%s/env-vars" % sid, token, method="PUT",
                 body={"envVars": merged})
    print("Env vars written. Keys now:",
          sorted(e.get("key") for e in (res.get("envVars", res) if isinstance(res, dict) else [])) or "see API response")

    # --- trigger deploy ---------------------------------------------------
    _, dep = api(API + "/services/%s/deploys" % sid, token, method="POST",
                 body={"clearCache": "do_not_clear"})
    print("Deploy triggered:", dep.get("id", "?"), "| commit:", (dep.get("commit", {}) or {}).get("id", "?")[:7])

    # --- poll health -------------------------------------------------------
    print("Waiting for deploy + Mongo connect (up to 10 min)...")
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(20)
        try:
            req = urllib.request.Request(HEALTH, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                h = json.loads(r.read())
            db = h.get("db")
            print("  health db =", db)
            if db == "mongo":
                print("SUCCESS: MongoDB connected. Accounts now survive redeploys.")
                sys.exit(0)
        except Exception as e:
            print("  health probe:", str(e)[:70])
    print("TIMEOUT: still not mongo. Re-run with the API key already saved and")
    print("double-check the Atlas password, or screenshot the Render deploy log.")
    sys.exit(1)


if __name__ == "__main__":
    main()
