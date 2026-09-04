#!/usr/bin/env python3
"""push_nse_financials.py - per-file contents-API push of the NSE financial
statements + index (bulk_push's giant tree GET keeps truncating)."""
import subprocess, os, sys, glob, time

HERE = r"D:\mutxri-terminal"
fin = os.path.join(HERE, "gh_pages_deploy2", "terminal", "static_data", "financials")
files = [os.path.join(fin, os.path.basename(f)) for f in
         sorted(glob.glob(os.path.join(HERE, "static_data", "financials", "*__income.json")) +
                glob.glob(os.path.join(HERE, "static_data", "financials", "*__balance.json")) +
                glob.glob(os.path.join(HERE, "static_data", "financials", "*__cashflow.json")))]
# restrict to NSE-merged set (KES statements added today)
ok = fail = 0
nse_set = set(open(os.path.join(HERE, "_nse_ok.txt")).read().split()) if os.path.exists(os.path.join(HERE, "_nse_ok.txt")) else None
for f in files:
    base = os.path.basename(f)
    sym = base.split("__")[0]
    if nse_set is not None and sym not in nse_set:
        continue
    rel = "terminal/static_data/financials/" + base
    r = subprocess.run([sys.executable, os.path.join(HERE, "push_one.py"), rel,
                        f"NSE audited {base}"], capture_output=True, text=True, timeout=120,
                       cwd=HERE)
    if "pushed" in r.stdout or "up to date" in r.stdout or r.returncode == 0:
        ok += 1
    else:
        fail += 1
        print("FAIL", base, (r.stdout or r.stderr)[-120:])
    if (ok + fail) % 25 == 0:
        print(f"... {ok + fail} done ({ok} ok)", flush=True)
# index last
r = subprocess.run([sys.executable, os.path.join(HERE, "push_one.py"),
                    "terminal/static_data/financials_index.json",
                    "NSE financials index: 32 audited KES statements"],
                   capture_output=True, text=True, timeout=120, cwd=HERE)
print("index:", "ok" if r.returncode == 0 else (r.stdout or r.stderr)[-200:])
print(f"DONE {ok} ok {fail} fail")
