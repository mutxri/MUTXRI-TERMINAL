#!/usr/bin/env python3
"""push_single_commit.py - push the whole deploy folder as ONE commit.

bulk_push.py writes one commit per file. Cloudflare/GitHub Pages builds per
commit, so a change touching hundreds of files (a refresh that rewrites every
statement, say) fires hundreds of builds and most come back "Page build
failed" - the branch is right and the live site silently stays stale. This
pushes every changed file into a single tree, a single commit and a single ref
update, so there is exactly one build.

Uses the Git Data API:
    POST /git/blobs            (one per changed file, parallel)
    POST /git/trees            (base_tree = current, all changes at once)
    POST /git/commits          (one commit)
    PATCH /git/refs/heads/...  (fast-forward the branch)

Deletions are supported: a path whose content is missing locally is removed
from the tree by sending sha=null, which is how stale files get cleaned up
(bulk_push never deletes anything).

Usage:
    python3 push_single_commit.py "commit message" [--dry]
"""
import base64, concurrent.futures as cf, hashlib, json, os, sys, time
import urllib.error, urllib.request

SEC = r"D:\mutxri-terminal\secrets_local.json"
REPO = "mutxri/MUTXRI-TERMINAL"
BRANCH = "gh-pages"
DEPLOY = r"D:\mutxri-terminal\gh_pages_deploy2"
TOKEN = json.load(open(SEC, encoding="utf-8"))["github_pat"]
DRY = "--dry" in sys.argv
MSG = next((a for a in sys.argv[1:] if not a.startswith("--")),
           "Deploy: single-commit push")


def api(path, data=None, method=None, tries=6):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(data).encode() if data is not None else None,
                method=method or ("POST" if data is not None else "GET"))
            req.add_header("Authorization", f"Bearer {TOKEN}")
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            r = urllib.request.urlopen(req, timeout=120)
            body = r.read().decode()
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            # 403 here means GitHub's SECONDARY rate limit (too many requests in
            # parallel), not a permissions problem: back off much harder for it.
            # 429 and the 5xx family are the ordinary transient failures.
            retryable = e.code in (429, 500, 502, 503) or (
                e.code == 403 and "secondary rate limit" in detail.lower())
            if retryable and attempt < tries - 1:
                wait = (30 * (attempt + 1)) if e.code == 403 else (4 * (attempt + 1))
                time.sleep(wait); continue
            raise RuntimeError(f"HTTP {e.code} {path}: {detail}")
        except Exception:
            if attempt < tries - 1:
                time.sleep(4 * (attempt + 1)); continue
            raise
    raise RuntimeError(f"gave up: {path}")


def blob_sha(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def main():
    ref = api(f"git/ref/heads/{BRANCH}")
    parent = ref["object"]["sha"]
    print(f"branch {BRANCH} at {parent[:10]}")

    base = api(f"git/trees/{parent}?recursive=1")
    live = {t["path"]: t["sha"] for t in base["tree"] if t["type"] == "blob"}
    if base.get("truncated"):
        print("WARNING: base tree truncated; comparison may be incomplete")
    print(f"live blobs: {len(live)}")

    local = {}
    for root, dirs, files in os.walk(DEPLOY):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, DEPLOY).replace("\\", "/")
            local[rel] = open(p, "rb").read()

    to_write = [(rel, c) for rel, c in local.items() if live.get(rel) != blob_sha(c)]
    to_delete = [rel for rel in live if rel not in local]
    print(f"changed: {len(to_write)}   stale on branch (to delete): {len(to_delete)}")
    if not to_write and not to_delete:
        print("nothing to do"); return
    if DRY:
        print("(dry run - no commit made)"); return

    # 1. blobs, in parallel: the blobs API has no meaningful per-second write cap
    print("uploading blobs...")
    entries = []
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(api, "git/blobs",
                          {"content": base64.b64encode(c).decode(), "encoding": "base64"}): rel
                for rel, c in to_write}
        done = 0
        for fut in cf.as_completed(futs):
            rel = futs[fut]
            sha = fut.result()["sha"]
            entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": sha})
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(to_write)} blobs")

    # 2. one tree, based on the current one, carrying every change and deletion
    for rel in to_delete:
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": None})
    print(f"creating tree with {len(entries)} entries (batched)...")
    # GitHub answers 504 Gateway Timeout when one git/trees call carries this many
    # entries, and the whole push dies with NO commit made - which is why large
    # changes never reached the site while the branch stayed on an old build.
    # Build the tree in batches, each based on the previous batch's tree.
    BATCH = 200
    tree_sha = base["sha"]
    for i in range(0, len(entries), BATCH):
        chunk = entries[i:i + BATCH]
        t = api("git/trees", {"base_tree": tree_sha, "tree": chunk})
        tree_sha = t["sha"]
        print(f"  tree batch {i // BATCH + 1}/{(len(entries) + BATCH - 1) // BATCH}: {len(chunk)} entries -> {tree_sha[:10]}")
    tree = {"sha": tree_sha}

    # 3+4. commit, then fast-forward. The branch can move under us: the
    # scheduled refresh (MUTXRI_Refresh3h) runs bulk_push and advances gh-pages
    # mid-push, which makes the ref update fail with 422 "not a fast forward".
    # The commit is fine, only the pointer is stale, so re-read the real parent,
    # re-base the tree on it and try again rather than losing the work.
    commit = None
    for attempt in range(6):
        cur = api(f"git/ref/heads/{BRANCH}")["object"]["sha"]
        if cur != parent:
            print(f"  branch moved to {cur[:10]}; re-basing the tree")
            parent = cur
            tree_sha = cur
            for i in range(0, len(entries), 200):
                t = api("git/trees", {"base_tree": tree_sha, "tree": entries[i:i + 200]})
                tree_sha = t["sha"]
            tree = {"sha": tree_sha}
        commit = api("git/commits", {"message": MSG, "tree": tree["sha"], "parents": [parent]})
        print(f"  commit {commit['sha'][:10]} (attempt {attempt + 1})")
        try:
            api(f"git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": False}, method="PATCH")
            break
        except RuntimeError as e:
            if "fast forward" in str(e) or "422" in str(e):
                time.sleep(6 * (attempt + 1)); continue
            raise
    else:
        print("FAILED: branch kept moving; commit created but ref not updated")
        print(f"  recover with: PATCH git/refs/heads/{BRANCH} -> {commit['sha']}")
        return
    print(f"DONE: 1 commit, {len(to_write)} files written, {len(to_delete)} deleted")


if __name__ == "__main__":
    main()
