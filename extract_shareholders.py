#!/usr/bin/env python3
"""extract_shareholders.py - pull major-shareholder sections from the JSE
annual report PDFs (jse_pdfs/) and merge into company_info.json.

Format in the PDFs (SBK example):
  "Industrial and Commercial Bank of China Limited (ICBC)  19.7  19.6"
  name ... pct_2025  pct_2024

Only 5%+ holders are listed in these sections (per JSE disclosure rules) -
that's the honest data these free reports provide.
"""
import json, os, re, sys
from pypdf import PdfReader

BASE = os.path.dirname(os.path.abspath(__file__))
PDFS = os.path.join(BASE, "jse_pdfs")
CI = os.path.join(BASE, "static_data", "company_info.json")
JSE_DATA = os.path.join(BASE, "jse_financials_data.json")

def find_pdf_for_issuer(code):
    """Match issuer code to a PDF: SBK -> SBK_*.pdf / SBKE_*.pdf."""
    for f in os.listdir(PDFS):
        fl = f.lower()
        if not fl.endswith(".pdf"):
            continue
        base = fl[:-4].split("_")[0].upper()
        if base == code.upper() or base == code.upper() + "E" or base == code.upper()[:3] + "E":
            return os.path.join(PDFS, f)
    return None

def extract_holders(pdf_path):
    """Return list of {holder, stake} from the analysis-of-shareholders page.
    Only checks the FIRST 12 pages (the section always appears early in the
    directors' report); returns [] if the report lacks the standard section."""
    try:
        reader = PdfReader(pdf_path)
    except Exception:
        return []
    holders = []
    for page in reader.pages[:12]:
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        tl = txt.lower()
        if not ("analysis of shareholders" in tl or "major shareholders" in tl):
            continue
        if "interests in excess of 5%" not in tl:
            continue
        lines = txt.split("\n")
        # find the start of the table (after the intro sentence)
        start = 0
        for i, l in enumerate(lines):
            if "were as follows" in l.lower():
                start = i + 1
                break
        prev_names = []  # accumulate multi-line name fragments
        for i in range(start, len(lines)):
            l = lines[i].strip()
            if not l:
                continue
            # stop at obvious section breakers
            if re.match(r"^(Directors|Refer to note|% held|Ordinary shares|6\.5%|Non-cumulative)", l):
                if l.startswith(("Directors", "Refer to note")):
                    break
                continue
            # a holder line: name + 1-2 numbers (pct 2025 [2024])
            m = re.match(r"^(.*?)\s+(\d{1,2}(?:\.\d+)?)\s+(?:\d{1,2}(?:\.\d+)?)?\s*$", l)
            if m and m.group(2):
                name_frag = m.group(1).strip()
                pct = float(m.group(2))
                # if the name fragment itself contains a number+text (two fused
                # rows), take only the part before the first number
                name_frag = re.split(r"\s+\d", name_frag)[0].strip()
                if name_frag and pct <= 100 and len(name_frag) > 3:
                    # multi-line name: prepend accumulated fragments
                    full_name = (prev_names[-1] + " " if prev_names else "") + name_frag
                    # but only if prev fragment looks like a name continuation
                    if prev_names:
                        full_name = prev_names[-1] + " " + name_frag
                    if full_name and pct <= 100 and not re.match(r"^(?:2025|2024|%|The|At)", full_name):
                        holders.append({"holder": full_name, "stake": f"~{pct:g}%"})
                        prev_names = []
                        continue
            prev_names.append(l)
        if holders:
            break  # found the table
    return holders

def main():
    jse_data = json.load(open(JSE_DATA, encoding="utf-8"))
    ci = json.load(open(CI, encoding="utf-8"))
    # issuer code -> sym mapping from jse_financials_data keys + stocks.json
    # NOTE: jse_data keys carry a trailing 'E' (4SIE, ABGE) - strip it to match
    stocks = json.load(open(os.path.join(BASE, "stocks.json"), encoding="utf-8"))["stocks"]
    code_to_sym = {}
    for s in stocks.get("JSE", []):
        code = s.get("code")
        sym = s.get("sym")
        if code and sym:
            code_to_sym[code.upper()] = sym
            code_to_sym[code.upper() + "E"] = sym
            # also handle 3-char truncated codes used in jse_data keys
            if len(code) >= 3:
                code_to_sym[code.upper()[:3] + "E"] = sym
    # issuer code from jse_data keys (they're like 'ABG', 'SBK')
    done = found = 0
    for code in jse_data:
        code_upper = code.upper()
        sym = code_to_sym.get(code_upper)
        if not sym:
            continue
        # skip if already has shareholders
        entry = ci.get(sym) or {}
        if entry.get("shareholders"):
            continue
        pdf = find_pdf_for_issuer(code_upper)
        if not pdf:
            continue
        holders = extract_holders(pdf)
        if holders:
            ci.setdefault(sym, {})
            ci[sym]["shareholders"] = holders
            ci[sym]["shareholder_source"] = f"JSE annual report ({os.path.basename(pdf)})"
            found += 1
        done += 1
        if done % 10 == 0:
            print(f"  processed {done}/{len(jse_data)}, found {found}", flush=True)
    with open(CI, "w", encoding="utf-8") as f:
        json.dump(ci, f, ensure_ascii=False, indent=1)
    print(f"DONE: {found} companies got shareholders from {done} PDFs")

if __name__ == "__main__":
    main()
