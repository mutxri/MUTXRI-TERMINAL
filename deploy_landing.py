#!/usr/bin/env python3
"""deploy_landing.py - deploy the landing page + terminal restructure to gh-pages.
Landing at root, terminal at /terminal/. Uses the contents API (git push hangs).
"""
import urllib.request, json, base64, os, sys, time

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
            resp = urllib.request.urlopen(req, timeout=45)
            return json.loads(resp.read().decode()), None
        except urllib.error.HTTPError as e:
            return None, f"{e.code}"
        except Exception as e:
            if attempt == retries - 1:
                return None, f"ERR {str(e)[:60]}"
            time.sleep(2 * (attempt + 1))
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
    return err is None

def delete_file(repo_path):
    sha = get_sha(repo_path)
    if not sha:
        return True
    d, err = api("DELETE", f"contents/{repo_path}", {"message": f"remove {repo_path}", "sha": sha, "branch": BR})
    return err is None

def main():
    files = []
    for root, dirs, fs in os.walk(DEPLOY):
        for f in fs:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, DEPLOY).replace("\\", "/")
            files.append((rel, full))
    print(f"pushing {len(files)} files...")

    ok = 0
    for rel, full in sorted(files):
        if push_file(rel, full):
            ok += 1
        else:
            print(f"  FAIL {rel}")
        time.sleep(0.15)
    print(f"pushed {ok}/{len(files)}")

    # delete stale root paths that moved to /terminal/
    stale = ["tickerfix.js", "filings_registry.json",
             "features/panels/afri_heatmap.html", "features/panels/afri_screener.html",
             "features/panels/afri_bnd.html", "features/panels/afri_reg.html",
             "features/panels/afri_fx.html", "features/panels/afri_glco.html",
             "features/panels/afri_ratings.html", "features/panels/afri_tas.html",
             "features/panels/afri_financials.html"]
    for p in stale:
        if delete_file(p):
            print(f"  deleted {p}")
        else:
            print(f"  DEL-FAIL {p}")
        time.sleep(0.15)

    # static_data files at root -> move to terminal/static_data/
    tree, err = api("GET", "git/trees/gh-pages?recursive=1")
    if not err:
        for t in tree["tree"]:
            p = t["path"]
            if p.startswith("static_data/") and t["type"] == "blob":
                if delete_file(p):
                    print(f"  moved {p}")
                time.sleep(0.15)

    print("DONE")

if __name__ == "__main__":
    main()
