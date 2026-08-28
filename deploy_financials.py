#!/usr/bin/env python3
"""deploy_financials.py - push static_data/financials/* + index + the
financials panel to gh-pages via contents API."""
import urllib.request, json, base64, os, time, sys

sec = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets_local.json"), encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "gh-pages"
HDRS = {"Authorization": "Bearer " + gh_token, "Accept": "application/vnd.github+json"}
BASE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(BASE, "gh_pages_deploy")

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

# 1. the financials panel (static fetch wiring)
ok = push_file("terminal/features/panels/afri_financials.html",
               os.path.join(DEPLOY, "terminal", "features", "panels", "afri_financials.html"))
print(f"afri_financials.html: {'✓' if ok else 'FAIL'}")

# 2. financials_index.json
ok = push_file("terminal/static_data/financials_index.json",
               os.path.join(DEPLOY, "terminal", "static_data", "financials_index.json"))
print(f"financials_index.json: {'✓' if ok else 'FAIL'}")

# 3. all statement files
fin_dir = os.path.join(DEPLOY, "terminal", "static_data", "financials")
files = sorted(os.listdir(fin_dir))
print(f"pushing {len(files)} financial statement files...")
okc = failc = 0
for i, f in enumerate(files):
    r = push_file("terminal/static_data/financials/" + f, os.path.join(fin_dir, f))
    if r: okc += 1
    else: failc += 1
    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{len(files)} (ok {okc}, fail {failc})", flush=True)
    time.sleep(0.12)
print(f"DONE: {okc} pushed, {failc} failed")
