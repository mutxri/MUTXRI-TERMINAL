#!/usr/bin/env python3
"""ocr_remaining_statements.py - OCR the 6 scanned/encrypted statement PDFs
(KQ, Uchumi, Kurwitu, TOTL, AMA, EkoCorp) with RapidOCR, then parse the
income-statement figures from the recognized text."""
import os, re, io, json, sys

BASE = os.path.dirname(os.path.abspath(__file__))
PDFS = {
    "NSE:ke-kq": "ke-kq.pdf",
    "NSE:ke-uchm": "ke-uchm.pdf",
    "NSE:ke-kurv": "ke-kurv.pdf",
    "NSE:ke-totl": "ke-totl.pdf",
    "NSE:ke-orch": "ke-orch.pdf",
    "NGX:ng-ekocor": "ng-ekocor.pdf",
}

def parse_figures(text):
    out = {}
    def scale(v, u):
        v = float(v.replace(",", ""))
        u = (u or "").lower()
        if u in ("billion", "bn", "bln"): return v * 1e9
        if u in ("million", "mn", "m"): return v * 1e6
        if u in ("trillion", "tn"): return v * 1e12
        return v
    pats = {
        "revenue": r"(?:Revenue|Turnover|Gross earnings|Sales revenue|Operating income)[^\d-]{0,60}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
        "gross_profit": r"Gross (?:profit|income)[^\d-]{0,60}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
        "operating_profit": r"(?:Operating (?:profit|income)|Profit from operations|EBIT)[^\d-]{0,60}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
        "profit_after_tax": r"(?:Profit (?:after tax|for the year|for the period)|Net profit|Profit/(?:Loss) after tax|Profit/Loss after tax)[^\d-]{0,60}([\d,]+\.?\d*)\s*(million|billion|trillion|bn|tn|mn)?",
    }
    for key, pat in pats.items():
        m = re.search(pat, text, re.I)
        if m:
            try:
                out[key] = scale(m.group(1), m.group(2))
            except ValueError:
                pass
    return out or None

def main():
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except ImportError:
        print("RapidOCR not installed")
        return

    # need a PDF->image renderer: use pypdf + PIL if pdf2image not available
    from pypdf import PdfReader

    results = {}
    for key, pdf_name in PDFS.items():
        pdf_path = os.path.join(BASE, "pdf_statements", pdf_name)
        print(f"\n=== {key} ===")
        try:
            reader = PdfReader(pdf_path)
            # render pages to images - try pypdf's own rendering (needs pymupdf)
            # fallback: extract embedded images
            texts = []
            for pno, page in enumerate(reader.pages):
                # try extracting embedded images first (common for scans)
                try:
                    imgs = page.images
                    for img in imgs:
                        data = img.data
                        from PIL import Image
                        import io as _io
                        im = Image.open(_io.BytesIO(data))
                        if im.mode != "RGB":
                            im = im.convert("RGB")
                        result, _ = ocr(im)
                        if result:
                            for line in result:
                                texts.append(line[1])
                except Exception:
                    pass
            text = "\n".join(texts)
            print(f"  OCR text length: {len(text)}")
            figs = parse_figures(text)
            if figs:
                results[key] = figs
                print(f"  OK: {figs}")
            else:
                # save text for inspection
                with open(os.path.join(BASE, "pdf_statements", pdf_name.replace(".pdf", ".ocr.txt")), "w", encoding="utf-8") as f:
                    f.write(text)
                results[key] = {"error": "no figures", "text_len": len(text)}
                print(f"  no figures (text saved)")
        except Exception as e:
            results[key] = {"error": str(e)[:100]}
            print(f"  FAIL: {str(e)[:100]}")

    with open(os.path.join(BASE, "pdf_statements", "ocr_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("\nOCR DONE -> pdf_statements/ocr_results.json")

if __name__ == "__main__":
    main()
