#!/usr/bin/env python3
"""push_one.py - push a single file to the gh-pages branch via contents API."""
import urllib.request, json, base64, os, sys, time

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "gh-pages"

def api(path, data=None, method=None):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 method=method or ("PUT" if data else "GET"))
    req.add_header("Authorization", f"Bearer {gh_token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        r = urllib.request.urlopen(req, timeout=60)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"HTTP {e.code}: {body[:300]}")
        raise

def push_file(path, content, msg):
    b64 = base64.b64encode(content).decode()
    sha = None
    try:
        sha = api(f"contents/{path}?ref=gh-pages")["sha"]
    except Exception:
        pass
    data = {"message": msg, "content": b64, "branch": BR}
    if sha:
        data["sha"] = sha
    api(f"contents/{path}", data)
    print(f"pushed {path} ({len(content)} bytes)")

if __name__ == "__main__":
    rel = sys.argv[1]
    msg = sys.argv[2] if len(sys.argv) > 2 else "update"
    content = open(os.path.join(r"D:\mutxri-terminal\gh_pages_deploy2", rel), "rb").read()
    push_file(rel, content, msg)
