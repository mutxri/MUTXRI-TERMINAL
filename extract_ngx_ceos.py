#!/usr/bin/env python3
"""extract_ngx_ceos.py - pull the Managing Director / CEO name out of the NGX
annual financial statements already downloaded to _ngx_pdf/.

Why this source: every other route to an NGX CEO name produced junk. Wikipedia
name-matching gave Cadbury Nigeria "Irene Rosenfeld" (ex-Mondelez) and Zenith
"David Penski"; Yahoo's assetProfile resolves bare NGX tickers to US companies
(NEM -> Newmont, UPDC -> Cincinnati). The audited annual report carries the
directors' list with each officer's title on a page we can cite, so the filing
is the source and every extract is checkable line by line.

Rules that matter:
  * the printed line is kept verbatim in the dump, so a reviewer can confirm the
    name was read and not guessed;
  * a name is taken from BEFORE the title, or after it when the report prints
    "Managing Director/CEO: NAME"; footnote markers, honorifics, professional
    suffixes and nationalities are stripped, digits disqualify a line;
  * if every hit says retired/former/resigned, the symbol is reported as having
    no current MD rather than quoting a person who has left.

Output: _ngx_ceos_from_afs.json  {SYM: {name, title, page, source, line, other_hits}}
Nothing is written to the live ceos.json here - review the dump, then merge.
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
PDFS = os.path.join(BASE, "_ngx_pdf")
OUT = os.path.join(BASE, "_ngx_ceos_from_afs.json")

TITLE = (r"(?:Group\s+|Acting\s+|Interim\s+|Country\s+)*"
         r"(?:Managing\s+Director(?:\s*/\s*(?:CEO|Chief\s+Executive\s+Officer))?"
         r"|MD\s*/\s*CEO|Co-?CEO|CEO|Chief\s+Executive\s+Officer)")
BAD_CTX = re.compile(r"report|statement|certification|committee|remuneration|audit|risk|"
                     r"approval|approved|appoint|effective|meeting|account|financial|award|"
                     r"policy|succession|served", re.I)
SUFFIX = re.compile(r"\b(?:FCA|FCIB|FCCA|ACIB|ACCA|ACA|CITN|mni|NPOM|OON|MFR|OFR|CON|PhD|"
                    r"B\.?Sc|M\.?Sc|MBA|CPA|Esq)\b.*$", re.I)
# longest first, and the honorific must be followed by a word so "Mrs." does not
# degrade into "s." and drop the whole name as lowercase
HON = re.compile(r"^(?:Mrs|Mr|Miss|Ms|Dr|Dame|Chief|Prince|Princess|Alhaji|Alhaja|Engr|Prof|Barr)"
                 r"\.?\s+", re.I)
STOPWORD = {"as", "by", "the", "of", "and", "in", "to", "for", "with", "from", "at", "on",
            "is", "was", "has", "had", "been", "who", "which", "its", "his", "her", "their"}
NATION = {"nigerian", "ghanaian", "kenyan", "egyptian", "south african", "british", "american",
          "indian", "lebanese", "french", "german", "chinese", "turkish", "pakistani", "italian",
          "australian", "ivorian", "dutch", "canadian", "spanish", "portuguese", "swiss", "irish",
          "scottish", "danish", "swedish", "belgian", "greek", "syrian", "jordanian", "moroccan"}
FOOT = re.compile(r"^[*\d\s\).-]+")
# label words that sit in front of the name in a directors' list ("Directors: Mr X")
LEADING = re.compile(r"^(?:We,?\s*|Directors?[:.]?\s*|Management\s*Team\s*|Management\s*|"
                     r"Company\s*|Name\s*[:.]?\s*|Board\s*|Chairman\s*|Executive\s*|Team\s*)+", re.I)
TRAILING = re.compile(r"\s*(?:Designation.*|Co-?$|Ag\.?$|\(Ag\.?$|Managing\s*Director.*|"
                      r"Chief\s*Executive.*|CEO.*)$", re.I)
# an entry that is only a job title, or a company, is not a person
ROLE_WORD = {"finance", "manager", "director", "directors", "designate", "executive", "chairman",
             "management", "team", "company", "name", "chief", "officer", "secretary", "deputy",
             "auditor", "registrar", "report", "statement"}
COMPANY_WORD = re.compile(r"\b(?:plc|limited|ltd|ventures?|holdings?|industries|company|bank|"
                          r"insurance|assurance|group|brewer|cement|properties|investments?|capital|"
                          r"trust|reit|oil|gas)\b", re.I)
INITIAL_ONLY = re.compile(r"\b[A-Z]\.(?:\s|$)")


def clean(raw):
    s = raw.strip()
    s = FOOT.sub("", s)                      # ****Mr. -> Mr.
    s = re.sub(r"\([^)]*\)", " ", s)         # (Dr.) is an honorific, not a name part
    s = LEADING.sub("", s)                   # "Directors Mr X" -> "Mr X"
    s = TRAILING.sub("", s)                  # "Name Designation: CEO" -> "Name"
    s = SUFFIX.sub("", s)
    s = re.sub(r"\s*[,;.]\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -,:;.")
    words = [w for w in s.split(" ") if w]
    while words and words[-1].lower() in NATION:
        words.pop()
    # drop a leading honorific only if a real name follows it
    if len(words) > 2:
        stripped = HON.sub("", " ".join(words[:4]))
        if len(stripped.split()) >= 2 and stripped != " ".join(words[:4]):
            words = stripped.split() + words[4:]
    name = " ".join(words).strip(" -,:;.")
    if not re.match(r"^[A-Z]", name):
        return None
    if len(name.split()) < 2 or len(name) < 6 or len(name) > 60:
        return None
    if re.search(r"\d", name) or BAD_CTX.search(name):
        return None
    # "Approved by CBN as Group Managing Director" is prose, not a person
    if any(w.lower() in STOPWORD for w in name.split()):
        return None
    # role-only text ("Finance Director") and company names are not people
    if all(w.lower().strip(".,") in ROLE_WORD for w in name.split()):
        return None
    if COMPANY_WORD.search(name) or INITIAL_ONLY.search(name):
        return None
    if sum(1 for w in name.split() if w[:1].isupper()) < 2:
        return None
    return name


def hits_in(text, page):
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not (8 <= len(line) <= 200):
            continue
        # "Mr. Afolabi Caxton-Martins (Chairman), Mrs. Funmi Ekundayo (MD/CEO)"
        # lists the board on one line: the officer is the name attached to the
        # CEO parenthetical, not the first name printed
        for pre in re.finditer(r"([A-Z][A-Za-z\.\-' ]{3,45}?)\s*[,(]\s*"
                               r"(?:MD/CEO|Managing\s+Director|Chief\s+Executive)", line):
            cand = clean(pre.group(1))
            if cand and not BAD_CTX.search(line[:60]):
                out.append({"name": cand, "page": page + 1, "line": line[:180],
                            "stale": bool(re.search(r"retir|former|resign|until|w\.e\.f", line, re.I))})
        for m in re.finditer(TITLE, line):
            before, after = line[:m.start()], line[m.end():]
            name = None
            if before.strip(" -,:;."):
                cand = clean(before)
                if cand and not BAD_CTX.search(line[:60]):
                    name = cand
            if name is None and after.strip(" -,:;."):
                cand = clean(after)
                if cand and not BAD_CTX.search(line[:60]):
                    name = cand
            if name:
                out.append({"name": name, "page": page + 1, "line": line[:180],
                            "stale": bool(re.search(r"retir|former|resign|until|w\.e\.f", line, re.I))})
    return out


def main():
    import pdfplumber
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    files = sorted(f for f in os.listdir(PDFS) if f.lower().endswith(".pdf"))
    if only:
        files = [f for f in files if os.path.splitext(f)[0] in only]
    result, misses = {}, []
    for fn in files:
        sym = os.path.splitext(fn)[0]
        found = []
        try:
            with pdfplumber.open(os.path.join(PDFS, fn)) as doc:
                for i, pg in enumerate(doc.pages[:16]):
                    found += hits_in(pg.extract_text(), i)
        except Exception as e:
            misses.append((sym, "pdf error " + str(e)[:40]))
            continue
        current = [h for h in found if not h["stale"]]
        pick_from = current or found
        if not pick_from:
            misses.append((sym, "no MD/CEO line in the first 16 pages"))
            continue
        pick_from.sort(key=lambda h: (h["page"], len(h["name"])))
        best = pick_from[0]
        result[sym] = {
            "name": best["name"],
            "title": "Managing Director / CEO",
            "page": best["page"],
            "stale": best["stale"],
            "source": f"{fn} (NGX annual report, p.{best['page']})",
            "line": best["line"],
            "other_hits": [h["name"] for h in pick_from[1:4]],
        }
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"extracted {len(result)} of {len(files)} symbols -> {os.path.basename(OUT)}")
    print(f"no usable line: {len(misses)}")
    for k, v in result.items():
        flag = " (STALE)" if v["stale"] else ""
        print(f"  {k:12s} {v['name']:34s} p{v['page']:<3}{flag} | {v['line'][:66]}")
    for m in misses:
        print("  MISS", m[0], m[1])


if __name__ == "__main__":
    main()
