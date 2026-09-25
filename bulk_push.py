#!/usr/bin/env python3
"""bulk_push.py - push every file in gh_pages_deploy2 whose content differs from
the live gh-pages branch (tree-compare, one GET, then PUT only changed files)."""
import urllib.request, json, base64, os, hashlib, sys, time
from urllib.parse import quote

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
    # live tree (one call) — retry hard: the ~930KB recursive tree GET is where
    # the flaky contents API truncates (http.client.IncompleteRead) and kills runs.
    tree = None
    for attempt in range(8):
        try:
            tree = api("git/trees/gh-pages?recursive=1")
            break
        except Exception as e:
            print(f"tree GET retry {attempt + 1}/8: {str(e)[:70]}")
            time.sleep(6 * (attempt + 1))
    if tree is None:
        print("FATAL: could not fetch the gh-pages tree after 8 attempts")
        return
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

    # REFUSE a mass change. One commit per file means one Pages build per file,
    # and GitHub rate-limits them: a 578-file change fired ~578 builds that
    # cancelled each other, kept the live site on an old build for 20 minutes,
    # and had to be killed. Anything past a handful of files belongs in
    # push_single_commit.py, which does the whole change as ONE commit.
    if len(changed) > 25:
        print(f"\nSTOPPING: {len(changed)} changed files is too many for this tool.")
        print("Each file would be its own commit and its own Pages build, and the")
        print("burst cancels itself while the live site stays stale. Use instead:\n")
        print(f'  python3 push_single_commit.py "{(sys.argv[1] if len(sys.argv) > 1 else "commit message")}"')
        return

    # commit message: pass one as argv[1], else fall back to the old default
    msg = sys.argv[1] if len(sys.argv) > 1 else \
        "Price refresh + screener rebuild + logo globe fix (runbook fixes 3-5)"
    ok = 0
    for rel, content in changed:
        for attempt in range(3):
            try:
                data = {"message": msg, "content": base64.b64encode(content).decode(), "branch": "gh-pages"}
                if rel in live:
                    data["sha"] = live[rel]
                # quote the path: Python's http.client rejects a bare space in a
                # URL, so any file whose name contains one (e.g. "MOFI REIF.png")
                # failed every push with "URL can't contain control characters".
                api(f"contents/{quote(rel, safe='/')}", data)
                ok += 1
                break
            except Exception as e:
                m = str(e)
                print(f"retry {rel}: {m[:60]}")
                # A 422 "sha wasn't supplied" means the path ALREADY EXISTS on the
                # branch while the prefetched tree did not list it. That happens on
                # a rename (the clean path was created by an earlier push) and when
                # a concurrent push lands after this tree read. Without resolving
                # the sha here the create can never succeed, and the file is left
                # silently unpushed - 8 of 13 files were lost this way once.
                if "422" in m:
                    try:
                        cur = api(f"contents/{quote(rel, safe='/')}?ref=gh-pages")
                        if isinstance(cur, dict) and cur.get("sha"):
                            live[rel] = cur["sha"]
                            print(f"        path exists on branch, reusing sha {cur['sha'][:10]}")
                    except Exception:
                        pass
                time.sleep(5)
        time.sleep(1.1)  # contents API: ~1 write/sec
        if ok % 50 == 0:
            print(f"  ...{ok}/{len(changed)} pushed")
    print(f"DONE: {ok}/{len(changed)} pushed")

if __name__ == "__main__":
    main()
