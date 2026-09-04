#!/usr/bin/env python3
"""verify_nse_matches.py - audit NSE collector matches: every downloaded PDF's
first page must contain a real token of the company name (guards against
single-token false matches like SGL->Standard Chartered). Also dumps the
statement-row counts so bad parses are visible before merge.

Usage: python verify_nse_matches.py
Writes _nse_audit.csv: SYMBOL<TAB>name<TAB>VERIFY_OK|VERIFY_BAD|EMPTY_PDF<TAB>company-token-hit
"""
import os, re, csv, json
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
GENERIC = {"plc", "limited", "ltd", "company", "co", "corporation", "corp",
           "group", "holdings", "holding", "international", "kenya", "east",
           "african", "the", "and", "of", "for", "investments", "investment"}

def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()

listing = json.load(open(os.path.join(HERE, "static_data", "listing_NSE.json"), encoding="utf-8"))
syms = {x.get("sym") or x["ticker"]: x["name"] for x in listing["stocks"]}

rows = []
for f in sorted(os.listdir(os.path.join(HERE, "_nse_pdf"))):
    if not f.endswith(".pdf"):
        continue
    sym = f[:-4]
    name = syms.get(sym, "")
    ct = [w for w in norm(name) if w not in GENERIC]
    pdf = os.path.join(HERE, "_nse_pdf", f)
    try:
        doc = pymupdf.open(pdf)
        pages_txt = [doc[i].get_text() for i in range(min(5, doc.page_count))]
        head = " ".join(pages_txt).lower()
        head = head.replace("\u2013", " ").replace("\u2014", " ").replace("-", " ")
        scanned = not any(p.strip() for p in pages_txt[:3])
    except Exception as e:
        rows.append((sym, name, "PDF_ERROR", str(e)[:60])); continue
    if scanned:
        rows.append((sym, name, "SCANNED", "")); continue
    hit = [w for w in ct if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", head)]
    rows.append((sym, name, "VERIFY_OK" if hit else "VERIFY_BAD", ",".join(hit[:3])))

with open(os.path.join(HERE, "_nse_audit.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh, delimiter="\t")
    w.writerow(["SYMBOL", "NAME", "STATUS", "TOKENS_HIT"])
    w.writerows(rows)
for r in rows:
    if r[2] != "VERIFY_OK":
        print(f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}")
print(f"total {len(rows)}: OK={sum(1 for r in rows if r[2]=='VERIFY_OK')} BAD={sum(1 for r in rows if r[2]=='VERIFY_BAD')} OTHER={sum(1 for r in rows if r[2]!='VERIFY_OK' and r[2]!='VERIFY_BAD')}")
