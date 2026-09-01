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
}
for rel, local in files.items():
    content = open(local, "rb").read()
    st, out = raw(f"contents/{rel}?ref=backend")
    if st != 200:
        print(f"{rel}: sha lookup failed ({st})")
        continue
    data = {"message": "Security hardening: block sensitive files, CORS restrict, POST auth, rate limit, param validation",
            "content": base64.b64encode(content).decode(), "branch": BR, "sha": out["sha"]}
    st2, out2 = raw(f"contents/{rel}", "PUT", data)
    print(f"{rel}: push {st2} ({len(content)} bytes)")
