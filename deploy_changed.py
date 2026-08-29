#!/usr/bin/env python3
"""deploy_changed.py - push ONLY the files that actually changed to gh-pages,
as one atomic commit.

push_atomic.py re-uploads the whole deploy folder every time. That folder is
now ~196 MB (145 MB of it NGX source PDFs that never change), so a routine data
refresh meant thousands of redundant blob uploads. This diffs local content
against the remote tree by git blob SHA and uploads only what differs, then
commits with base_tree set to the existing tree so untouched paths are kept.

usage: deploy_changed.py "commit message" [--dry-run]
"""
import urllib.request, urllib.error, json, base64, os, sys, hashlib, time

BASE = os.path.dirname(os.path.abspath(__file__))
sec = json.load(open(os.path.join(BASE, "secrets_local.json"), encoding="utf-8"))
REPO = "mutxri/MUTXRI-TERMINAL"
BR = "gh-pages"
HDRS = {"Authorization": "Bearer " + sec["github_pat"],
        "Accept": "application/vnd.github+json",
        "User-Agent": "mutxri-deploy"}
DEPLOY = os.path.join(BASE, "gh_pages_deploy")


def api(method, path, body=None, retries=5):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=HDRS)
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode()), None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code in (502, 503, 504) and a < retries - 1:
                time.sleep(3 * (a + 1))
                continue
            return None, f"{e.code} {detail}"
        except Exception as e:
            if a == retries - 1:
                return None, f"ERR {str(e)[:80]}"
            time.sleep(3 * (a + 1))
    return None, "retries exhausted"


def blob_sha(data: bytes) -> str:
    """the SHA git itself would give this content"""
    h = hashlib.sha1()
    h.update(b"blob " + str(len(data)).encode() + b"\0")
    h.update(data)
    return h.hexdigest()


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "data refresh"
    dry = "--dry-run" in sys.argv

    ref, err = api("GET", f"git/ref/heads/{BR}")
    if err:
        print("ERR ref:", err); return 1
    head = ref["object"]["sha"]
    commit, err = api("GET", f"git/commits/{head}")
    if err:
        print("ERR head commit:", err); return 1
    base_tree = commit["tree"]["sha"]

    remote, err = api("GET", f"git/trees/{base_tree}?recursive=1")
    if err:
        print("ERR tree:", err); return 1
    if remote.get("truncated"):
        print("WARNING: remote tree truncated - falling back to uploading everything")
    have = {i["path"]: i["sha"] for i in remote.get("tree", []) if i["type"] == "blob"}

    changed = []
    scanned = 0
    for root, _, files in os.walk(DEPLOY):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, DEPLOY).replace("\\", "/")
            data = open(full, "rb").read()
            scanned += 1
            if have.get(rel) != blob_sha(data):
                changed.append((rel, data))

    print(f"{scanned} local files, {len(have)} remote blobs -> {len(changed)} changed")
    for rel, _ in changed[:25]:
        print("   *", rel)
    if len(changed) > 25:
        print(f"   ... and {len(changed) - 25} more")
    if not changed:
        print("nothing to deploy")
        return 0
    if dry:
        print("(dry run - nothing pushed)")
        return 0

    items = []
    for i, (rel, data) in enumerate(changed, 1):
        b, err = api("POST", "git/blobs",
                     {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        if err:
            print(f"  blob FAIL {rel}: {err}")
            return 1
        items.append({"path": rel, "mode": "100644", "type": "blob", "sha": b["sha"]})
        if i % 25 == 0:
            print(f"  uploaded {i}/{len(changed)}", flush=True)

    tree, err = api("POST", "git/trees", {"base_tree": base_tree, "tree": items})
    if err:
        print("ERR tree create:", err); return 1
    new, err = api("POST", "git/commits",
                   {"message": msg, "tree": tree["sha"], "parents": [head]})
    if err:
        print("ERR commit:", err); return 1
    upd, err = api("PATCH", f"git/refs/heads/{BR}", {"sha": new["sha"]})
    if err:
        print("ERR ref update:", err); return 1
    print(f"deployed {len(changed)} files as {new['sha'][:8]} -> {upd.get('ref')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
