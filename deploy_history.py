#!/usr/bin/env python3
"""deploy_history.py - push the static_data/history/* files to gh-pages
via the contents API (the reliable Pages trigger). Only pushes files with
real bars (>=2) - empty markers stay local as pending-retry state."""
import json, os, base64, time, urllib.request

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
TOKEN = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "gh-pages"
HDRS = {"Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json"}
HIST = r"D:\mutxri-terminal\static_data\history"

def api(method, path, body=None, retries=4):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=HDRS)
            resp = urllib.request.urlopen(req, timeout=60)
            return json.loads(resp.read().decode()), None
        except urllib.error.HTTPError as e:
            return None, f"{e.code}"
        except Exception:
            if attempt == retries - 1:
                return None, "ERR"
            time.sleep(3 * (attempt + 1))
    return None, "retries exhausted"

def push_file(repo_path, local_path):
    content = open(local_path, "rb").read()
    b64 = base64.b64encode(content).decode()
    d, err = api("GET", f"contents/{repo_path}?ref={BR}")
    sha = d.get("sha") if d and not err else None
    body = {"message": f"deploy {repo_path}", "content": b64, "branch": BR}
    if sha:
        body["sha"] = sha
    d, err = api("PUT", f"contents/{repo_path}", body)
    return err is None

def main():
    files = []
    for f in sorted(os.listdir(HIST)):
        if not f.endswith(".json"):
            continue
        p = os.path.join(HIST, f)
        try:
            with open(p, encoding="utf-8") as fh:
                n = len(json.load(fh).get("bars", []))
        except Exception:
            continue
        if n >= 2:
            files.append((f, p))
    print(f"pushing {len(files)} history files with real bars...")
    ok = fail = 0
    for i, (f, p) in enumerate(files):
        r = push_file("terminal/static_data/history/" + f, p)
        if r:
            ok += 1
        else:
            fail += 1
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(files)} (ok {ok}, fail {fail})", flush=True)
        time.sleep(0.15)
    print(f"DONE: {ok} pushed, {fail} failed")

if __name__ == "__main__":
    main()
