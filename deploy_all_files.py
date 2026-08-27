#!/usr/bin/env python3
"""deploy_all_files.py - push every deploy file via the contents API (the
approach that reliably triggers GitHub Pages builds). Sequential, retried.
"""
import urllib.request, json, base64, os, time

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "gh-pages"
HDRS = {"Authorization": "Bearer " + gh_token, "Accept": "application/vnd.github+json"}
DEPLOY = r"D:\mutxri-terminal\gh_pages_deploy"

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
        except Exception as e:
            if attempt == retries - 1:
                return None, f"ERR {str(e)[:60]}"
            time.sleep(3 * (attempt + 1))
    return None, "retries exhausted"

def get_sha(repo_path):
    d, err = api("GET", f"contents/{repo_path}?ref={BR}")
    if err or not d or isinstance(d, list):
        return None
    return d.get("sha")

def push_file(repo_path, local_path):
    content = open(local_path, "rb").read()
    b64 = base64.b64encode(content).decode()
    sha = get_sha(repo_path)
    body = {"message": f"deploy {repo_path}", "content": b64, "branch": BR}
    if sha:
        body["sha"] = sha
    d, err = api("PUT", f"contents/{repo_path}", body)
    return err is None, err

def main():
    files = []
    for root, dirs, fs in os.walk(DEPLOY):
        for f in fs:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, DEPLOY).replace("\\", "/")
            files.append((rel, full))
    print(f"pushing {len(files)} files (sequential, retried)...")
    ok = 0
    for i, (rel, full) in enumerate(files, 1):
        good, err = push_file(rel, full)
        if good:
            ok += 1
        else:
            print(f"  FAIL {rel}: {err}")
        if i % 10 == 0:
            print(f"  {i}/{len(files)} ({ok} ok)")
        time.sleep(0.4)
    print(f"DONE: {ok}/{len(files)} pushed")

if __name__ == "__main__":
    main()
