#!/usr/bin/env python3
"""bulk_push.py - push every file in gh_pages_deploy2 whose content differs from
the live gh-pages branch (tree-compare, one GET, then PUT only changed files)."""
import urllib.request, json, base64, os, hashlib, sys, time

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
DEPLOY = r"D:\mutxri-terminal\gh_pages_deploy2"

def api(path, data=None, method=None):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 method=method or ("PUT" if data else "GET"))
    req.add_header("Authorization", f"Bearer {gh_token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        r = urllib.request.urlopen(req, timeout=90)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        raise

def git_blob_sha(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()

def main():
    # live tree (one call)
    tree = api("git/trees/gh-pages?recursive=1")
    live = {t["path"]: t["sha"] for t in tree["tree"] if t["type"] == "blob"}
    print(f"live branch: {len(live)} blobs")

    changed = []
    for root, dirs, files in os.walk(DEPLOY):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, DEPLOY).replace("\\", "/")
            content = open(p, "rb").read()
            sha = git_blob_sha(content)
            if live.get(rel) != sha:
                changed.append((rel, content))
    print(f"changed files to push: {len(changed)}")

    msg = "Price refresh + screener rebuild + logo globe fix (runbook fixes 3-5)"
    ok = 0
    for rel, content in changed:
        for attempt in range(3):
            try:
                data = {"message": msg, "content": base64.b64encode(content).decode(), "branch": "gh-pages"}
                if rel in live:
                    data["sha"] = live[rel]
                api(f"contents/{rel}", data)
                ok += 1
                break
            except Exception as e:
                print(f"retry {rel}: {str(e)[:60]}")
                time.sleep(5)
        time.sleep(1.1)  # contents API: ~1 write/sec
        if ok % 50 == 0:
            print(f"  ...{ok}/{len(changed)} pushed")
    print(f"DONE: {ok}/{len(changed)} pushed")

if __name__ == "__main__":
    main()
