#!/usr/bin/env python3
"""measure_coverage.py - compute the real coverage numbers for the landing
page and methodology page, straight from the data files.

Measures, per exchange:
  - securities (listing files)
  - income / balance / cashflow (listed securities with a statement file)
  - price history (listed securities with a history file)
  - executive records (listed securities with a non-empty CEO record)
"""
import json, os

SD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static_data")

def load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None

def listing(ex):
    d = load(os.path.join(SD, f"listing_{ex}.json"))
    if d is None:
        return []
    return d.get("stocks", d if isinstance(d, list) else [])

def keys(s):
    """all the ticker spellings a file/record might use for this security"""
    out = []
    sym = (s.get("sym") or "").strip()
    code = (s.get("code") or "").strip()
    for k in (sym, code):
        if k:
            out.append(k)
            out.append(k.split(".")[0])  # 4SI.JO -> 4SI
    return [k for k in dict.fromkeys(out) if k]  # dedupe, keep order

def has_file(kinds, typ):
    def _h(k):
        return os.path.exists(os.path.join(SD, "financials", f"{k}__{typ}.json"))
    return any(_h(k) for k in kinds)

def has_history(kinds, ex):
    def _h(k):
        return (os.path.exists(os.path.join(SD, "history", f"{k}.json")) or
                os.path.exists(os.path.join(SD, "history", f"{k}.max.json")) or
                os.path.exists(os.path.join(SD, "history", f"{ex}_{k}.json")) or
                os.path.exists(os.path.join(SD, "history", f"{ex}_{k}.max.json")))
    return any(_h(k) for k in kinds)

def exec_ok(kinds, ceos):
    for k in kinds:
        v = ceos.get(k)
        if isinstance(v, str):
            if v.strip():
                return True
        elif isinstance(v, dict):
            if any(str(x).strip() for x in v.values() if x is not None):
                return True
    return False

def main():
    ceos = load(os.path.join(SD, "ceos.json")) or {}
    rows = {}
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        st = listing(ex)
        inc = bal = cf = hist = exc = 0
        for s in st:
            k = keys(s)
            if has_file(k, "income"): inc += 1
            if has_file(k, "balance"): bal += 1
            if has_file(k, "cashflow"): cf += 1
            if has_history(k, ex): hist += 1
            if exec_ok(k, ceos): exc += 1
        rows[ex] = {"sec": len(st), "inc": inc, "bal": bal, "cf": cf,
                    "hist": hist, "exec": exc}
    print("=" * 72)
    print(f"{'ex':5} {'sec':>5} {'income':>7} {'balance':>8} {'cashflow':>9} {'history':>8} {'exec':>5}")
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        r = rows[ex]
        print(f"{ex:5} {r['sec']:>5} {r['inc']:>7} {r['bal']:>8} {r['cf']:>9} {r['hist']:>8} {r['exec']:>5}")
    t = {k: sum(rows[e][k] for e in rows) for k in ["sec", "inc", "bal", "cf", "hist", "exec"]}
    print("-" * 72)
    print(f"{'TOTAL':5} {t['sec']:>5} {t['inc']:>7} {t['bal']:>8} {t['cf']:>9} {t['hist']:>8} {t['exec']:>5}")
    print("=" * 72)
    # raw file counts (for the "statement files" line)
    fs = [x for x in os.listdir(os.path.join(SD, "financials"))
          if x.endswith(".json") and not x.startswith("_")]
    by_type = {}
    for f in fs:
        if "__" in f:
            by_type[f.split("__")[-1].replace(".json", "")] = by_type.get(f.split("__")[-1].replace(".json", ""), 0) + 1
    print("statement files on disk:", len(fs), dict(by_type))
    print("ceos.json entries:", len(ceos))
    hd = [x for x in os.listdir(os.path.join(SD, "history"))
          if x.endswith(".json") and not x.endswith(".max.json")]
    print("daily history files:", len(hd))

if __name__ == "__main__":
    main()
