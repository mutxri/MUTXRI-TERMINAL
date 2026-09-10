#!/usr/bin/env python3
"""deploy.py - one command for a full deploy.

    python deploy.py "what changed"

Does, in order:
  1. assemble_deploy.py            - rebuild gh_pages_deploy2 from the sources
  2. push_backend.py               - only if the backend files actually differ
                                     from the backend branch (Render deploys it)
  3. deploy_changed.py             - push the changed files to gh-pages
  4. verify against the live site  - poll mutxriterminal.com until it serves
                                     what was just pushed

Step 4 is the point of this script. A push that returns 200 is not a deploy:
GitHub Pages rebuilds on its own schedule, a write can 500 after every blob is
uploaded, and this repo has already had one "successful" deploy publish a stale
file. Nothing here reports success until the public URL serves the new bytes.

    --only <path>    limit the gh-pages push to a path or prefix (repeatable)
    --dry-run        show what would go out, push nothing
    --skip-backend   frontend only
    --no-verify      push without waiting for the live site
    --backend        push the backend even if it looks unchanged
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.join(BASE, "gh_pages_deploy2")
SITE = "https://mutxriterminal.com"
BACKEND_FILES = ["afri_server.py", "auth_api.py", "chat_room.py"]
BACKEND_DIR = os.path.join(BASE, "backend_render")
REPO = "mutxri/MUTXRI-TERMINAL"
_TOKEN = None
VERIFY_MAX = 6            # files to check on the live site
VERIFY_TRIES = 28         # ~7 minutes at 15s; Pages has taken over five
VERIFY_WAIT = 15
# checked but never worth blocking a deploy on: rewritten by every data refresh
VERIFY_SKIP = ("README.md", "robots.txt", "sitemap.xml", "CNAME")


def run(title, args, tail=None):
    """Run a step, echo its output, stop the deploy if it fails.

    `tail` keeps a chatty step readable: assemble_deploy.py lists all ~4,900
    files it copied, which buries everything that matters.
    """
    print("\n== %s ==" % title, flush=True)
    p = subprocess.run([sys.executable] + args, cwd=BASE, capture_output=True, text=True)
    out = (p.stdout or "").rstrip()
    err = (p.stderr or "").rstrip()
    if out:
        lines = out.splitlines()
        if tail and len(lines) > tail:
            print("  (%d lines)" % len(lines))
            print("\n".join(lines[:2]))
            print("  ...")
            print("\n".join(lines[-tail:]))
        else:
            print(out)
    if err:
        print(err, file=sys.stderr)
    if p.returncode != 0:
        # never let a failed step read as a success - this script exists because
        # a piped deploy once reported the exit code of `tail`
        print("FAILED: %s (exit %d)" % (title, p.returncode))
        sys.exit(p.returncode)
    return out


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "mutxri-deploy",
                                               "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def backend_differs():
    """True when a backend file on disk differs from the deployed branch.

    Unreadable is NOT a difference. Pushing on uncertainty writes a commit per
    file even when the content is identical, and every one of those restarts
    Render - the live API bouncing because a check timed out is worse than a
    backend change waiting for the next deploy. --backend forces a push.
    """
    unknown = []
    for name in BACKEND_FILES:
        local_path = os.path.join(BACKEND_DIR, name)
        if not os.path.exists(local_path):
            continue
        want = local_blob_sha(open(local_path, "rb").read())
        have = gh_blob_sha(name, "backend")
        if have is None:
            unknown.append(name)
            continue
        if have != want:
            print("  %s differs from the backend branch" % name)
            return True
    if unknown:
        print("  could not check %s - leaving the backend alone (--backend forces it)"
              % ", ".join(unknown))
    return False

def gh_blob_sha(path, ref):
    """The sha GitHub holds for this path on this branch, or None if unreadable.

    The API is authenticated - 5000 requests an hour - where raw.githubusercontent
    is not and answers 429/503 under any load. It also hands back the git blob
    sha, so a comparison costs one small request instead of downloading the file.
    """
    global _TOKEN
    if _TOKEN is None:
        try:
            _TOKEN = json.load(open(os.path.join(BASE, "secrets_local.json"),
                                    encoding="utf-8"))["github_pat"]
        except Exception:
            _TOKEN = ""
    if not _TOKEN:
        return None
    url = "https://api.github.com/repos/%s/contents/%s?ref=%s" % (REPO, path, ref)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + _TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "mutxri-deploy"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode()).get("sha")
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def local_blob_sha(data):
    """the sha git itself would give this content"""
    h = hashlib.sha1()
    h.update(b"blob " + str(len(data)).encode() + b"\0")
    h.update(data)
    return h.hexdigest()



def changed_from(output):
    """The paths deploy_changed.py said it pushed (it lists the first 25)."""
    return [l.strip()[2:].strip() for l in output.splitlines() if l.strip().startswith("* ")]


def verify(paths):
    """Poll the live site until it serves the bytes we just pushed."""
    targets = []
    for rel in paths:
        if os.path.basename(rel) in VERIFY_SKIP:
            continue
        full = os.path.join(DEPLOY, *rel.split("/"))
        if os.path.exists(full) and os.path.getsize(full) < 4_000_000:
            targets.append((rel, hashlib.sha1(open(full, "rb").read()).hexdigest()))
        if len(targets) >= VERIFY_MAX:
            break
    if not targets:
        print("  nothing worth verifying (data files only)")
        return True
    pending = dict(targets)
    for attempt in range(1, VERIFY_TRIES + 1):
        for rel, want in list(pending.items()):
            try:
                live = hashlib.sha1(fetch("%s/%s" % (SITE, rel))).hexdigest()
            except Exception:
                continue
            if live == want:
                print("  live: %s" % rel)
                pending.pop(rel)
        if not pending:
            print("  all %d verified on %s" % (len(targets), SITE))
            return True
        if attempt < VERIFY_TRIES:
            time.sleep(VERIFY_WAIT)
    # Timed out. That is not the same as a failed deploy, and the difference is
    # the whole question: is the push on the branch and Pages is just slow, or
    # did the push not land? Ask the branch directly.
    failed, unknown = False, 0
    for rel, want in pending.items():
        branch = gh_blob_sha(rel, "gh-pages")
        want = local_blob_sha(open(os.path.join(DEPLOY, *rel.split("/")), "rb").read())
        err = "the API did not answer"
        if branch is None:
            # a rate-limited CHECK is not a failed push. raw.githubusercontent
            # answers 429/503 when asked for several files at once, and calling
            # that a failed deploy sends you re-pushing work that already landed.
            print("  %s: could not check the branch (%s)" % (rel, err))
            unknown += 1
            continue
        if branch == want:
            print("  on the branch, not yet served by Pages: %s" % rel)
        else:
            print("  NOT ON THE BRANCH: %s - the push did not land" % rel)
            failed = True
    if unknown:
        print("  (%d file(s) could not be checked - the push reported a commit, "
              "so treat those as landed unless the site stays stale)" % unknown)
    return not failed


def main():
    args = sys.argv[1:]
    msg = args[0] if args and not args[0].startswith("--") else "site update"
    dry = "--dry-run" in args
    skip_backend = "--skip-backend" in args
    no_verify = "--no-verify" in args
    force_backend = "--backend" in args
    only = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--only"]

    run("rebuild the deploy folder", ["assemble_deploy.py"], tail=3)

    if not skip_backend:
        print("\n== backend ==")
        if force_backend or backend_differs():
            if dry:
                print("  (dry run - not pushed)")
            else:
                run("push the backend", ["push_backend.py"])
        else:
            print("  already up to date with the backend branch")

    push_args = ["deploy_changed.py", msg]
    for p in only:
        push_args += ["--only", p]
    if dry:
        push_args.append("--dry-run")
    out = run("push to gh-pages", push_args)

    if dry or "nothing to deploy" in out:
        print("\nDone (nothing pushed).")
        return 0
    if no_verify:
        print("\nPushed. Skipped live verification (--no-verify).")
        return 0

    print("\n== verify on the live site ==")
    if not verify(changed_from(out)):
        print("\nThe push did NOT land - see above. Re-run this command.")
        return 1
    print("\nDeployed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
