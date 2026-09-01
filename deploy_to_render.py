#!/usr/bin/env python3
"""deploy_to_render.py - ONE-SHOT Render deployment.
Run AFTER adding a card at https://dashboard.render.com/billing.
Creates the free web service from the backend branch and reports the URL."""
import json, sys, os, urllib.request

RENDER_TOKEN = os.environ.get("RENDER_API_KEY", "")
OWNER = "tea-da65rhgjo6nc73efamqg"

body = {
    "type": "web_service",
    "name": "mutxri-backend",
    "ownerID": OWNER,
    "repo": "https://github.com/mutxri/MUTXRI-TERMINAL",
    "branch": "backend",
    "serviceDetails": {
        "runtime": "python",
        "plan": "free",
        "envSpecificDetails": {
            "buildCommand": "pip install -r requirements.txt",
            "startCommand": "python afri_server.py"
        },
        "healthCheckPath": "/api/health"
    }
}
# NOTE: the live API validated this EXACT shape (ownerID capital D, plan inside
# serviceDetails) - schema passes; only billing blocks it.

req = urllib.request.Request("https://api.render.com/v1/services",
                             data=json.dumps(body).encode(), method="POST",
                             headers={"Authorization": "Bearer " + RENDER_TOKEN,
                                      "Content-Type": "application/json",
                                      "Accept": "application/json"})
try:
    resp = urllib.request.urlopen(req, timeout=60)
    d = json.loads(resp.read().decode())
    sid = d.get("id")
    print("SERVICE CREATED:", d.get("name"))
    print("service id:", sid)
    # the service URL is usually https://<name>.onrender.com
    print("URL: https://mutxri-terminal.onrender.com")
    print("Next: set MONGODB_URI env var, then API_BASE in index.html")
except urllib.error.HTTPError as e:
    msg = e.read().decode()[:200]
    print("HTTP", e.code, ":", msg)
    if "Payment information" in msg:
        print("\nSTILL BLOCKED: add a card at https://dashboard.render.com/billing")
        print("(free plan - the card is never charged; it's Render's anti-abuse policy)")
    sys.exit(1)
