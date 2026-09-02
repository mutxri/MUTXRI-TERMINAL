#!/usr/bin/env python3
"""Parse a JSE SENS annual-results announcement PDF into the MUTXRI terminal
financials JSON format.

Usage:
    python jse_parse.py <pdf_path> <symbol> <name> <out_dir>

Figures come from the HIGHLIGHTS table and condensed statements using word
coordinates (label -> numbers on the same line to its right). Units per the
table header (R'000 default, R million when stated). Stored in ZAR; EPS/HEPS/DPS
converted from cents. Writes <symbol>__income.json. Exit 0 on success.
"""
import sys, os, re, json
import pymupdf

NUM_TOK = re.compile(r"-?[\d,]+\.?\d*|\([\d,]+\)|−?[\d,]+\.?\d*")


def load_pages_words(pdf):
    doc = pymupdf.open(pdf)
    return [doc[p].get_text("words") for p in range(doc.page_count)]


def parse_num(tok):
    return float(tok.replace(",", "").replace("(", "-").replace(")", "").replace("−", "-"))


def find_row(pages_words, label, label_variants=()):
    """Numbers to the right of (and up to ~22pt below) the label phrase.
    Consecutive digit-only words merge into one number when their gap is small
    ("1 163 457" -> 1163457; a wide gap starts a new column value)."""
    names = [label] + list(label_variants)
    first_words = {n.split()[0].lower() for n in names}
    for page in pages_words:
        for i, w in enumerate(page):
            if len(w) < 5:
                continue
            txt = w[4]
            if txt.lower() not in first_words:
                continue
            # verify the following words on the same line complete one of the labels
            y0 = w[1]
            same_line = sorted([w2 for w2 in page if len(w2) >= 5 and abs(w2[1] - y0) < 3], key=lambda w2: w2[0])
            full_line = " ".join(w2[4] for w2 in same_line)
            # the word directly before this one must not extend the label (e.g. Headline earnings per share)
            prev_word = ""
            for w2 in same_line:
                if w2[2] < w[0] and (not prev_word or w2[0] > prev_word[0]):
                    prev_word = w2
            prev_txt = (prev_word[4] if isinstance(prev_word, tuple) else "").lower()
            ok = False
            for n in names:
                pos = full_line.lower().find(n.lower())
                if pos >= 0 and (pos == 0 or not full_line[pos - 1].isalpha()):
                    first = n.split()[0].lower()
                    if prev_txt and prev_txt in ("headline", "basic", "diluted", "adjusted", "normalised", "normalized", "recurring") and first in ("earnings", "profit", "revenue"):
                        continue
                    ok = True
                    break
            if not ok:
                continue
            x0 = w[0]
            toks = sorted([w2 for w2 in page if len(w2) >= 5 and w2[1] >= y0 - 3 and w2[1] <= y0 + 22 and w2[0] > x0 + 4],
                          key=lambda w2: (w2[1], w2[0]))
            groups, cur, cur_x1 = [], None, None
            for w2 in toks:
                t2 = w2[4]
                if NUM_TOK.fullmatch(t2):
                    if cur is not None and re.fullmatch(r"\d{1,3}", t2) and re.fullmatch(r"\d[\d,]*", cur) \
                            and cur_x1 is not None and (w2[0] - cur_x1) < 20:
                        cur += t2
                        cur_x1 = w2[2]
                    else:
                        if cur is not None:
                            groups.append(parse_num(cur))
                        cur, cur_x1 = t2, w2[2]
                else:
                    if cur is not None:
                        groups.append(parse_num(cur))
                        cur, cur_x1 = None, None
            if cur is not None:
                groups.append(parse_num(cur))
            if groups:
                return groups
    return None


def main():
    pdf, symbol, name, out_dir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    pages_words = load_pages_words(pdf)
    text = "\n".join(p.get_text() for p in pymupdf.open(pdf))

    unit = 1_000_000 if re.search(r"R['’]?\s*million|R['’]?m\b", text[:6000], re.I) else 1_000
    eps_unit = 100

    rev = find_row(pages_words, "Revenue", ("Revenue from contracts",))
    op = find_row(pages_words, "Operating profit", ("Operating Profit", "Operating income"))
    net = find_row(pages_words, "Profit for the year", ("Profit attributable to owners", "Net profit", "Profit after taxation"))
    eps = find_row(pages_words, "Earnings per share", ("Basic earnings per share",))
    heps = find_row(pages_words, "Headline earnings per share", ("Basic headline earnings per share",))
    dps = find_row(pages_words, "Dividend per share", ("Dividends per share",))

    rows = []
    if rev:
        rows.append({"label": "Revenue", "values": [round(v * unit, 2) for v in rev[:2]]})
    if op:
        rows.append({"label": "Operating Profit (EBIT)", "values": [round(v * unit, 2) for v in op[:2]]})
    if net:
        rows.append({"label": "Net Profit", "values": [round(v * unit, 2) for v in net[:2]]})
    if eps:
        rows.append({"label": "EPS", "values": [round(v / eps_unit, 4) for v in eps[:2]]})
    if heps:
        rows.append({"label": "HEPS", "values": [round(v / eps_unit, 4) for v in heps[:2]]})
    if dps:
        rows.append({"label": "DPS", "values": [round(v / eps_unit, 4) for v in dps[:2]]})

    years = sorted({y for y in re.findall(r"20\d\d", text) if 2000 <= int(y) <= 2040}, reverse=True)
    periods = ["FY" + y for y in years[:2]] if years else ["FY2026", "FY2025"]

    os.makedirs(out_dir, exist_ok=True)
    wrote = 0
    if rows:
        out = {
            "ticker": symbol, "name": name, "currency": "ZAR", "source": "JSE SENS (senspdf.jse.co.za)",
            "asOf": (periods[0] if periods else ""), "statement": "income", "statementTitle": "Income Statement",
            "period": "annual", "available": True, "periods": periods, "rows": rows,
        }
        with open(os.path.join(out_dir, f"{symbol}__income.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        wrote += 1
    print(f"{symbol}: wrote {wrote}, periods={periods}, rows={[r['label'] for r in rows]}")
    sys.exit(0 if wrote else 1)


if __name__ == "__main__":
    main()
