#!/usr/bin/env python3
"""push_backend.py - push hardened backend files to the backend branch."""
import urllib.request, json, base64, os, sys

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "backend"

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
    "login_log.py": r"D:\mutxri-terminal\backend_render\login_log.py",
}
for rel, local in files.items():
    content = open(local, "rb").read()
    st, out = raw(f"contents/{rel}?ref=backend")
    data = {"message": "Sign-in notifications + login log: welcome/new-device emails (SES) and durable attempt log (Mongo login_events, JSON fallback)",
            "content": base64.b64encode(content).decode(), "branch": BR}
    if st == 200:
        data["sha"] = out["sha"]  # update existing file
    elif st == 404:
        pass  # new file - create without sha
    else:
        print(f"{rel}: sha lookup failed ({st})")
        continue
    st2, out2 = raw(f"contents/{rel}", "PUT", data)
    print(f"{rel}: push {st2} ({len(content)} bytes)")
