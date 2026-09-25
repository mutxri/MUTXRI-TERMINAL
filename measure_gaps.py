#!/usr/bin/env python3
"""measure_gaps.py - authoritative gap audit across financials, logos, company
info, history and executive records, for every active listed security.

Outputs a per-exchange + total table, and dumps the exact gap lists to
static_data/_gap_audit_<ts>.json for follow-up work.
"""
import json, os, sys
from collections import defaultdict

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
    out = []
    sym = (s.get("sym") or "").strip()
    tick = (s.get("ticker") or "").strip()
    code = (s.get("code") or "").strip()
    for k in (sym, tick, code):
        if k:
            out.append(k)
            out.append(k.split(".")[0])
    return [k for k in dict.fromkeys(out) if k]

def has_file(kinds, typ):
    return any(os.path.exists(os.path.join(SD, "financials", f"{k}__{typ}.json")) for k in kinds)

def has_history(kinds, ex):
    for k in kinds:
        for p in (f"{k}.json", f"{k}.max.json", f"{ex}_{k}.json", f"{ex}_{k}.max.json"):
            if os.path.exists(os.path.join(SD, "history", p)):
                return True
    return False

def exec_ok(kinds, ceos):
    for k in kinds:
        v = ceos.get(k)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, dict) and any(str(x).strip() for x in v.values() if x is not None):
            return True
    return False

def logo_ok(kinds, logo_map):
    for k in kinds:
        v = logo_map.get(k)
        if v and str(v).strip() and str(v).lower() not in ("none", "null"):
            return True
    return False

def info_ok(kinds, ci):
    for k in kinds:
        if k in ci:
            v = ci[k]
            if isinstance(v, dict) and (v.get("description") or v.get("name") or v.get("listed")):
                return True
    return False

def main():
    logo_map = load(os.path.join(SD, "logos.json")) or {}
    ci = load(os.path.join(SD, "company_info.json")) or {}
    ceos = load(os.path.join(SD, "ceos.json")) or {}

    # how many logo URLs point at a file that is actually on disk
    logo_dir = os.path.join(SD, "logos_img")
    logo_files = set(os.listdir(logo_dir)) if os.path.isdir(logo_dir) else set()

    rows = {}
    gaps = defaultdict(lambda: defaultdict(list))
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        st = listing(ex)
        c = {"sec": len(st), "inc": 0, "bal": 0, "cf": 0, "any": 0,
             "hist": 0, "exec": 0, "logo": 0, "info": 0}
        for s in st:
            k = keys(s)
            has_inc = has_file(k, "income")
            has_bal = has_file(k, "balance")
            has_cf = has_file(k, "cashflow")
            has_any = has_inc or has_bal or has_cf
            has_h = has_history(k, ex)
            has_e = exec_ok(k, ceos)
            has_l = logo_ok(k, logo_map)
            has_i = info_ok(k, ci)

            c["inc"] += has_inc; c["bal"] += has_bal; c["cf"] += has_cf
            c["any"] += has_any; c["hist"] += has_h; c["exec"] += has_e
            c["logo"] += has_l; c["info"] += has_i

            ident = {"sym": s.get("sym") or s.get("ticker") or "", "name": s.get("name", ""),
                     "ticker": s.get("ticker", ""), "instrument": s.get("instrument", ""),
                     "sector": s.get("sector", "")}
            if not has_any: gaps[ex]["no_statement"].append(ident)
            if not has_inc: gaps[ex]["no_income"].append(ident)
            if not has_bal: gaps[ex]["no_balance"].append(ident)
            if not has_cf: gaps[ex]["no_cashflow"].append(ident)
            if not has_l: gaps[ex]["no_logo"].append(ident)
            if not has_i: gaps[ex]["no_info"].append(ident)
            if not has_h: gaps[ex]["no_history"].append(ident)
            if not has_e: gaps[ex]["no_exec"].append(ident)
        rows[ex] = c

    print("=" * 96)
    print(f"{'ex':5}{'sec':>5}{'inc':>5}{'bal':>5}{'cf':>5}{'any':>5}{'hist':>6}{'exec':>5}{'logo':>6}{'info':>5}")
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        r = rows[ex]
        print(f"{ex:5}{r['sec']:>5}{r['inc']:>5}{r['bal']:>5}{r['cf']:>5}{r['any']:>5}{r['hist']:>6}{r['exec']:>5}{r['logo']:>6}{r['info']:>5}")
    t = {k: sum(rows[e][k] for e in rows) for k in ["sec", "inc", "bal", "cf", "any", "hist", "exec", "logo", "info"]}
    print("-" * 96)
    print(f"{'TOT':5}{t['sec']:>5}{t['inc']:>5}{t['bal']:>5}{t['cf']:>5}{t['any']:>5}{t['hist']:>6}{t['exec']:>5}{t['logo']:>6}{t['info']:>5}")
    print("=" * 96)

    # gap totals
    print("\nGAP TOTALS (missing):")
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        g = gaps[ex]
        print(f"  {ex}: no_statement={len(g['no_statement'])} no_income={len(g['no_income'])} "
              f"no_balance={len(g['no_balance'])} no_cashflow={len(g['no_cashflow'])} "
              f"no_logo={len(g['no_logo'])} no_info={len(g['no_info'])} "
              f"no_history={len(g['no_history'])} no_exec={len(g['no_exec'])}")

    # logo file existence check (broken images -> monogram fallback)
    broken = 0
    for k, v in logo_map.items():
        if isinstance(v, str) and "/logos_img/" in v:
            fn = v.split("/logos_img/")[-1]
            if fn not in logo_files:
                broken += 1
    print(f"\nlogo_map entries: {len(logo_map)} | logos_img files on disk: {len(logo_files)} | broken logo file refs: {broken}")

    out_path = os.path.join(SD, "_gap_audit_full.json")
    json.dump({ex: dict(gaps[ex]) for ex in gaps}, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("gap lists written to", out_path)

if __name__ == "__main__":
    main()
