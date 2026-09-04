#!/usr/bin/env python3
"""bot/ingest.py - getting a private company's statements into the same shape.

Listed issuers arrive pre-parsed in static_data/financials. Everything else -
a private company's management accounts, an audited PDF, a spreadsheet a founder
emailed - has to be read off whatever format it came in. This module turns those
into the canonical document that bot/statements.py analyses, so a private company
gets exactly the same ratios, trends and flags as a listed one.

Deterministic readers first (CSV, XLSX, JSON, and PDF tables via pdfplumber).
When a PDF is too messy for table extraction - scanned, multi-column, footnoted -
bot/analyst.py can read it with Claude instead. That is extraction, not analysis:
the model reads numbers off a page, then every ratio is recomputed here in Python.
The model never does the arithmetic, and every extracted figure keeps the source
label it came from so a human can audit it against the document.
"""
import csv, datetime as dt, io, json, os, re

from . import statements as S

PERIOD_RE = re.compile(r"(?:FY\s*)?((?:19|20)\d{2})(?:\s*/\s*\d{2,4})?", re.I)


def _looks_like_period(cell):
    s = str(cell or "").strip()
    return bool(s) and bool(PERIOD_RE.search(s)) and len(s) <= 24


def _period_label(cell):
    m = PERIOD_RE.search(str(cell or ""))
    return ("FY" + m.group(1)) if m else str(cell).strip()


def _table_to_sections(rows, entity, source, section_hint=None):
    """Turn a label-plus-values grid into a canonical document.

    The header row is the first row with two or more year-like cells; every row
    after it contributes a label and its values. Rows whose label maps to no
    canonical line item are kept in `unmapped` rather than discarded, so nothing
    silently vanishes from a statement.
    """
    header_idx, periods, period_cols = None, [], []
    for i, row in enumerate(rows[:25]):
        yrs = [(j, c) for j, c in enumerate(row) if _looks_like_period(c)]
        if len(yrs) >= 2:
            header_idx = i
            period_cols = [j for j, _ in yrs]
            periods = [_period_label(c) for _, c in yrs]
            break
    if header_idx is None:
        raise ValueError("could not find a period header row (need >=2 year columns)")

    # Newest-first, matching the parsed-filing convention used across the terminal.
    order = sorted(range(len(periods)),
                   key=lambda k: S._fy(periods[k]) or 0, reverse=True)
    periods = [periods[k] for k in order]
    period_cols = [period_cols[k] for k in order]

    sections = {"income": {}, "balance": {}, "cashflow": {}}
    unmapped, current = [], section_hint
    SECTION_CUES = [
        (r"income statement|profit (?:and|&) loss|statement of (?:comprehensive )?income|p&l", "income"),
        (r"balance sheet|statement of financial position", "balance"),
        (r"cash ?flow", "cashflow"),
    ]

    for row in rows[header_idx + 1:]:
        if not row:
            continue
        label = str(row[0] or "").strip()
        if not label:
            continue
        low = label.lower()
        hit_section = next((sec for pat, sec in SECTION_CUES if re.search(pat, low)), None)
        values = [S._num(row[j]) if j < len(row) else None for j in period_cols]
        if hit_section and all(v is None for v in values):
            current = hit_section          # a section heading, not a data row
            continue
        if all(v is None for v in values):
            continue
        # Try the hinted section first, then any section that recognises the label.
        placed = False
        for sec in ([current] if current else []) + ["income", "balance", "cashflow"]:
            if not sec:
                continue
            key = S._canon(label, S.SECTION_MAPS[sec])
            if key and key not in sections[sec]:
                sections[sec][key] = values
                placed = True
                break
        if not placed:
            unmapped.append({"label": label, "values": values})

    if not any(sections.values()):
        raise ValueError("no recognisable statement lines found")

    return {
        "entity": entity,
        "periods": periods,
        "sections": {k: v for k, v in sections.items() if v},
        "source": source,
        "unmapped": unmapped,
    }


def _entity(name, kind="private", **kw):
    e = {"id": kw.get("id") or re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").upper(),
         "name": name, "kind": kind, "ticker": kw.get("ticker"),
         "currency": kw.get("currency"), "sector": kw.get("sector"),
         "country": kw.get("country")}
    return e


# ------------------------------------------------------------------- readers
def from_csv(path, name=None, **kw):
    """Read a CSV/TSV grid: first column labels, later columns periods."""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(f, dialect)]
    return _table_to_sections(
        rows, _entity(name or os.path.splitext(os.path.basename(path))[0], **kw),
        {"kind": "csv", "detail": os.path.basename(path),
         "ingestedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})


def from_xlsx(path, name=None, sheet=None, **kw):
    """Read the first (or named) worksheet as a label/period grid."""
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl is required to read .xlsx - pip install openpyxl")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]
    return _table_to_sections(
        rows, _entity(name or os.path.splitext(os.path.basename(path))[0], **kw),
        {"kind": "xlsx", "detail": "%s#%s" % (os.path.basename(path), ws.title),
         "ingestedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})


def from_json(path, name=None, **kw):
    """Read a statement already in the terminal's {rows,periods} shape."""
    raw = json.load(open(path, encoding="utf-8"))
    if isinstance(raw, dict) and "sections" in raw and "periods" in raw:
        return raw                                   # already canonical
    sections, periods = {}, raw.get("periods") or []
    for section in ("income", "balance", "cashflow"):
        blob = raw.get(section)
        if blob:
            vals, _ = S.normalise_section(blob if isinstance(blob, dict) else {"rows": blob},
                                          section)
            if vals:
                sections[section] = vals
    if not sections and raw.get("rows"):
        guess = raw.get("statement") or "income"
        vals, _ = S.normalise_section(raw, guess)
        sections[guess] = vals
    if not sections:
        raise ValueError("unrecognised JSON statement shape")
    return {"entity": _entity(name or raw.get("name") or "entity", **kw),
            "periods": periods, "sections": sections,
            "source": {"kind": "json", "detail": os.path.basename(path)}}


def pdf_tables(path, max_pages=40):
    """Extract candidate tables from a text-based PDF. Returns list of grids."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is required to read PDFs - pip install pdfplumber")
    grids = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:max_pages]:
            for tbl in page.extract_tables() or []:
                if tbl and len(tbl) >= 3:
                    grids.append(tbl)
    return grids


def pdf_text(path, max_pages=40):
    """Plain text of a PDF, for the model-assisted path and for auditing."""
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is required to read PDFs - pip install pdfplumber")
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:max_pages]:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def from_pdf(path, name=None, **kw):
    """Deterministic PDF path: try each extracted table until one parses.

    Raises when no table yields a statement - the caller can then fall back to
    the model-assisted reader in bot/analyst.py rather than guessing here.
    """
    grids = pdf_tables(path)
    errors = []
    for g in grids:
        try:
            doc = _table_to_sections(
                g, _entity(name or os.path.splitext(os.path.basename(path))[0], **kw),
                {"kind": "pdf-table", "detail": os.path.basename(path),
                 "ingestedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
            return doc
        except ValueError as e:
            errors.append(str(e))
    raise ValueError("no parsable statement table in %s (%d tables tried)"
                     % (os.path.basename(path), len(grids)))


READERS = {".csv": from_csv, ".tsv": from_csv, ".txt": from_csv,
           ".xlsx": from_xlsx, ".xlsm": from_xlsx,
           ".json": from_json, ".pdf": from_pdf}


def ingest(path, name=None, **kw):
    """Read any supported statement file into the canonical document shape."""
    ext = os.path.splitext(path)[1].lower()
    reader = READERS.get(ext)
    if not reader:
        raise ValueError("unsupported statement format %r (support: %s)"
                         % (ext, ", ".join(sorted(READERS))))
    return reader(path, name=name, **kw)


# ------------------------------------------------------------------- storage
PRIVATE_DIR = os.path.join(S.SD, "private")


def save(doc):
    """Persist an ingested private company so later runs can reuse it."""
    os.makedirs(PRIVATE_DIR, exist_ok=True)
    eid = doc["entity"]["id"]
    p = os.path.join(PRIVATE_DIR, "%s.json" % re.sub(r"[^A-Za-z0-9_.-]", "_", eid))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return p


def load_private(entity_id):
    p = os.path.join(PRIVATE_DIR, "%s.json"
                     % re.sub(r"[^A-Za-z0-9_.-]", "_", entity_id))
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def available_private():
    if not os.path.isdir(PRIVATE_DIR):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(PRIVATE_DIR)
                  if f.endswith(".json"))


def load_any(entity_id):
    """Resolve an id to a document, public statements first, then private."""
    return S.load_public(entity_id) or load_private(entity_id)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        print("usage: python -m bot.ingest <file> [--name NAME] [--save]")
        raise SystemExit(1)
    src = sys.argv[1]
    nm = None
    if "--name" in sys.argv:
        nm = sys.argv[sys.argv.index("--name") + 1]
    d = ingest(src, name=nm)
    a = S.analyse(d)
    print("%s (%s) - periods %s" % (a["entity"]["name"], a["entity"]["kind"],
                                    ", ".join(a["periods"])))
    for r in a["metrics"]:
        print("  %-8s rev %14s net %13s margin %7s" %
              (r["period"],
               "%.0f" % r["revenue"] if r["revenue"] is not None else "-",
               "%.0f" % r["net_profit"] if r["net_profit"] is not None else "-",
               "%.1f%%" % r["net_margin"] if r["net_margin"] is not None else "-"))
    for f in a["flags"]:
        print("  [%s] %s - %s" % (f["severity"].upper(), f["label"], f["detail"]))
    if d.get("unmapped"):
        print("  unmapped lines kept:", len(d["unmapped"]))
    if "--save" in sys.argv:
        print("saved:", save(d))
