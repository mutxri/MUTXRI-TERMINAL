#!/usr/bin/env python3
"""run_full_crawl.py - launch the full IR crawl for JSE + EGX in the background.
Processes all stocks, resumable via ir_crawl_state.json, writes parsed
statements to ir_statements.json (sidecar). Run with --exchange to target one.
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import mass_ir_crawler as mc

def main():
    exchanges = sys.argv[1:] if len(sys.argv) > 1 else ["JSE", "EGX"]
    workers = 5
    db = json.load(open(mc.STOCKS, encoding="utf-8"))

    state = {}
    if os.path.exists(mc.STATE):
        try:
            state = json.load(open(mc.STATE, encoding="utf-8"))
        except Exception:
            state = {}

    results = {}
    if os.path.exists(mc.STATE.replace("state", "statements")):
        try:
            results = json.load(open(mc.STATE.replace("state", "statements"), encoding="utf-8"))
        except Exception:
            results = {}

    lock = threading.Lock() if False else __import__("threading").Lock()

    for ex in exchanges:
        stocks = db["stocks"].get(ex, [])
        todo = [s for s in stocks if f"{ex}:{s.get('sym') or s.get('ticker') or s.get('name')}" not in state]
        print(f"[crawl] {ex}: {len(stocks)} stocks, {len(todo)} to process (workers={workers})")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(mc.process_company, ex, s, state, lock) for s in todo]
            for f in futs:
                try:
                    r = f.result()
                except Exception as e:
                    r = None
                if r:
                    done += 1
                    if r.get("data"):
                        results[r["key"]] = r
                    if done % 10 == 0:
                        json.dump(state, open(mc.STATE, "w", encoding="utf-8"), ensure_ascii=False)
                        json.dump(results, open(mc.STATE.replace("state", "statements"), "w", encoding="utf-8"), ensure_ascii=False)
                        print(f"  [{done}/{len(todo)}] {ex} parsed so far: {len(results)}")
        json.dump(state, open(mc.STATE, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(results, open(mc.STATE.replace("state", "statements"), "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[crawl] {ex} done: {done} processed | {len(results)} total parsed")

    print(f"\nFINAL: {len(results)} companies with parsed statements saved to ir_statements.json")

if __name__ == "__main__":
    main()
