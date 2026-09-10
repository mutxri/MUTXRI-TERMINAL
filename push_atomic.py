#!/usr/bin/env python3
"""push_atomic.py - push ALL deploy files as ONE commit to gh-pages.
GitHub Pages builds are flaky with rapid sequential contents-API commits;
a single atomic commit triggers one clean build.
"""
import urllib.request, json, base64, os, time

sec = json.load(open(r"D:\mutxri-terminal\secrets_local.json", encoding="utf-8"))
gh_token = sec["github_pat"]
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "gh-pages"
HDRS = {"Authorization": "Bearer " + gh_token, "Accept": "application/vnd.github+json"}
# the folder assemble_deploy.py actually builds (gh_pages_deploy is dead)
DEPLOY = r"D:\mutxri-terminal\gh_pages_deploy2"

def api(method, path, body=None, retries=5):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=HDRS)
            resp = urllib.request.urlopen(req, timeout=60)
            return json.loads(resp.read().decode()), None
        except urllib.error.HTTPError as e:
            return None, f"{e.code} {e.read().decode(errors='replace')[:150]}"
        except Exception as e:
            if attempt == retries - 1:
                return None, f"ERR {str(e)[:60]}"
            time.sleep(3 * (attempt + 1))
    return None, "retries exhausted"

def main():
    # 1. get current tree sha
    ref, err = api("GET", f"git/ref/heads/{BR}")
    if err:
        print("ERR ref:", err); return
    base_sha = ref["object"]["sha"]

    # 2. build blobs
    blobs = []
    for root, dirs, fs in os.walk(DEPLOY):
        for f in fs:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, DEPLOY).replace("\\", "/")
            content = open(full, "rb").read()
            b, err = api("POST", "git/blobs", {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            if err:
                print(f"blob fail {rel}: {err}"); continue
            blobs.append((rel, b["sha"]))
            if len(blobs) % 20 == 0:
                print(f"  blobs: {len(blobs)}")

    print(f"built {len(blobs)} blobs")

    # 3. build tree
    tree_items = [{"path": rel, "mode": "100644", "type": "blob", "sha": s} for rel, s in blobs]
    tree, err = api("POST", "git/trees", {"base_tree": base_sha, "tree": tree_items})
    if err:
        print("ERR tree:", err); return
    print("tree:", tree["sha"])

    # 4. commit
    commit, err = api("POST", "git/commits", {
        "message": "landing + terminal atomic deploy (history widget, rebrand)",
        "tree": tree["sha"],
        "parents": [base_sha],
    })
    if err:
        print("ERR commit:", err); return
    print("commit:", commit["sha"])

    # 5. update ref (fast-forward)
    upd, err = api("PATCH", f"git/refs/heads/{BR}", {"sha": commit["sha"], "force": True})
    if err:
        print("ERR ref update:", err); return
    print("ref updated:", upd.get("ref"))

if __name__ == "__main__":
    main()
