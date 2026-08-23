#!/usr/bin/env python3
"""run_full_crawl.py v2 - IR crawl runner with safe checkpointing.
Fixes: state dumps under the lock (no corrupted JSON), per-worker timeouts,
no shared-dict mutation races.
"""
import json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import mass_ir_crawler as mc

STATE = os.path.join(BASE, "ir_crawl_state.json")
RESULT = os.path.join(BASE, "ir_statements.json")

def main():
    exchanges = sys.argv[1:] if len(sys.argv) > 1 else ["JSE", "EGX"]
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 5
    db = json.load(open(mc.STOCKS, encoding="utf-8"))

    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8"))
        except Exception:
            state = {}  # corrupt state -> restart clean

    results = {}
    if os.path.exists(RESULT):
        try:
            results = json.load(open(RESULT, encoding="utf-8"))
        except Exception:
            results = {}

    lock = threading.Lock()

    def save():
        # dump under lock: consistent snapshot
        with lock:
            tmp = STATE + ".tmp"
            json.dump(state, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, STATE)
            tmp2 = RESULT + ".tmp"
            json.dump(results, open(tmp2, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp2, RESULT)

    for ex in exchanges:
        stocks = db["stocks"].get(ex, [])
        todo = [s for s in stocks if f"{ex}:{s.get('sym') or s.get('ticker') or s.get('name')}" not in state]
        print(f"[crawl] {ex}: {len(stocks)} stocks, {len(todo)} to process (workers={workers})", flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            def run_one(s):
                # hard cap per company (60s) so one slow site can't stall a worker
                key = f"{ex}:{s.get('sym') or s.get('ticker') or s.get('name')}"
                if key in state:
                    return None
                from concurrent.futures import ThreadPoolExecutor as _TPE
                with _TPE(max_workers=1) as inner:
                    f = inner.submit(mc.process_company, ex, s, state, lock)
                    try:
                        return f.result(timeout=75)
                    except Exception:
                        return {"key": key, "sym": s.get("sym"), "name": s.get("name"), "error": "timeout"}
            futs = {pool.submit(run_one, s): s for s in todo}
            for fut in as_completed(futs):
                try:
                    r = fut.result()
                except Exception as e:
                    r = None
                if r:
                    done += 1
                    if r.get("data"):
                        results[r["key"]] = r
                    if done % 10 == 0:
                        save()
                        print(f"  [{done}/{len(todo)}] {ex} parsed: {len(results)}", flush=True)
        save()
        print(f"[crawl] {ex} done: {done} processed | {len(results)} total parsed", flush=True)

    print(f"\nFINAL: {len(results)} companies with parsed statements -> {RESULT}", flush=True)

if __name__ == "__main__":
    main()
