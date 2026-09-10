#!/usr/bin/env python3
"""push_backend.py - push hardened backend files to the backend branch.

GUARD: refuses to push anything that reintroduces scrapped features
(welcome/sign-in emails, login attempt log, GitHub OAuth) - these were
deliberately removed 2026-09-03 per user instruction.
"""
import urllib.request, json, base64, os, sys

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "backend"

# Content that must NEVER come back on the backend branch
BANNED_TOKENS = ["signin_notify", "login_log", "notify_signin",
                 'provider == "github"', "GITHUB_CLIENT_ID"]

def raw(path, method="GET", data=None):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(data).encode() if data else None)
    req.add_header("Authorization", f"Bearer {gh_token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200]

files = {
    "afri_server.py": r"D:\mutxri-terminal\backend_render\afri_server.py",
    "auth_api.py": r"D:\mutxri-terminal\backend_render\auth_api.py",
    "chat_room.py": r"D:\mutxri-terminal\backend_render\chat_room.py",
}
for rel, local in files.items():
    content = open(local, "rb").read()
    text = content.decode("utf-8", "replace")
    for tok in BANNED_TOKENS:
        if tok in text:
            print(f"BLOCKED: {rel} contains banned token '{tok}' - refusing to push.")
            print("(Scrapped features must not be reintroduced. Remove it first.)")
            sys.exit(1)
    st, out = raw(f"contents/{rel}?ref=backend")
    data = {"message": "Backend update (auth/persistence)",
            "content": base64.b64encode(content).decode(),
            "branch": BR, "sha": out["sha"] if st == 200 else None}
    st2, out2 = raw("contents/" + rel, "PUT", data)
    print(f"{rel}: push {st2} ({len(content)} bytes)")
    if st2 not in (200, 201):
        print("  response:", str(out2)[:200])
