#!/usr/bin/env python3
"""bot/cards.py - composing one social card from real, licensed pictures.

Takes the assets bot/images.py resolved - a company logo, portraits of the people
a story names - and lays them out with the headline into a 1200x675 card in the
terminal's palette, with a credit line for every picture used.

Two rules the layout enforces, both of which are about not lying to a reader:

  * No invented faces. When no licensed photograph of a person exists - the common
    case - the card draws a typographic initials tile with the person's name under
    it. A monogram is obviously a monogram; nobody mistakes it for a photograph,
    and it is not a picture of some other person.
  * Credit is part of the image, not the caption. CC BY and CC BY-SA require
    attribution, and a caption can be stripped when a post is quoted or reshared.
    Printing the credit into the pixels means it travels with the picture.

Needs Pillow.
"""
import os

from . import images as I

W, H = 1200, 675
BG = (8, 8, 8)
PANEL = (18, 18, 18)
LINE = (42, 42, 42)
TX = (240, 240, 240)
TX2 = (150, 150, 150)
TX3 = (105, 105, 105)
ACC = (51, 226, 154)

# Windows first (this repo's home), then the usual Linux/macOS paths.
_FONT_CANDIDATES = {
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "mono": ["C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
             "/System/Library/Fonts/Menlo.ttc"],
}


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ImportError:
        raise RuntimeError("Pillow is required to build cards - pip install pillow")


def _font(kind, size):
    _, _, ImageFont = _pil()
    for p in _FONT_CANDIDATES[kind]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_w(draw, s, font):
    return draw.textbbox((0, 0), s, font=font)[2]


def _wrap(draw, text, font, max_w):
    """Wrap to pixel width - textwrap counts characters, which is wrong for a
    proportional face where 'W' is three times the width of 'i'."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _text_w(draw, trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _ellipsise(draw, text, font, max_w):
    """Trim to fit a single line, ending in an ellipsis."""
    if _text_w(draw, text, font) <= max_w:
        return text
    base = text.rstrip("… ").rstrip()
    while base and _text_w(draw, base + "…", font) > max_w:
        base = base[:-1].rstrip()
    return (base + "…") if base else ""


def _shorten_name(draw, name, font, max_w):
    """Fit a name to one line, keeping the given name and surname intact."""
    parts = name.split()
    if len(parts) > 2:
        cand = " ".join([parts[0]] + [p[0] + "." for p in parts[1:-1]] + [parts[-1]])
        if _text_w(draw, cand, font) <= max_w:
            return cand
    if len(parts) > 1:
        cand = parts[0][0] + ". " + parts[-1]
        if _text_w(draw, cand, font) <= max_w:
            return cand
    return _ellipsise(draw, name, font, max_w)


def _initials(name):
    parts = [p for p in name.split() if p and p[0].isalpha()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def _monogram(size, name, Image, ImageDraw):
    """Typographic stand-in when no licensed photograph exists."""
    tile = Image.new("RGB", (size, size), PANEL)
    d = ImageDraw.Draw(tile)
    d.ellipse([0, 0, size - 1, size - 1], fill=(26, 26, 26), outline=LINE, width=2)
    f = _font("bold", int(size * 0.36))
    ini = _initials(name)
    bb = d.textbbox((0, 0), ini, font=f)
    d.text(((size - (bb[2] - bb[0])) / 2 - bb[0],
            (size - (bb[3] - bb[1])) / 2 - bb[1]), ini, font=f, fill=TX2)
    return tile


def _circle(img, size, Image, ImageDraw):
    """Cover-crop to a square and mask to a circle."""
    src = img.convert("RGB")
    w, h = src.size
    side = min(w, h)
    # Crop from the upper third: on a portrait the face sits above centre.
    top = max(0, min(h - side, int((h - side) * 0.3)))
    left = (w - side) // 2
    src = src.crop((left, top, left + side, top + side)).resize((size, size),
                                                                Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGB", (size, size), BG)
    out.paste(src, (0, 0), mask)
    return out


def _trim_alpha(im):
    """Crop transparent padding so the mark fills the space it is given."""
    try:
        bbox = im.getchannel("A").getbbox()
        return im.crop(bbox) if bbox else im
    except Exception:
        return im


def _load(path, Image):
    if not path or not os.path.exists(path) or path.lower().endswith(".svg"):
        return None
    try:
        return Image.open(path)
    except Exception:
        return None


def build(headline, out_path, *, logo=None, people=None, exchange=None,
          eyebrow=None, source=None, date=None):
    """Compose the card.

    `logo` is an image asset (fetched) or None. `people` is a list of
    {"name": str, "role": str, "asset": asset-or-None}. Anyone without an asset
    gets a monogram, and the card reports which faces are not photographs.
    """
    Image, ImageDraw, _ = _pil()
    people = people or []
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    f_brand = _font("mono", 22)
    f_eyebrow = _font("mono", 20)
    f_head = _font("bold", 52)
    f_name = _font("bold", 24)
    f_role = _font("regular", 19)
    f_foot = _font("mono", 15)

    pad = 56
    # Header band
    d.rectangle([0, 0, W, 92], fill=(4, 4, 4))
    d.line([0, 92, W, 92], fill=LINE, width=2)
    d.text((pad, 34), "MUTXRI", font=f_brand, fill=ACC)
    bw = _text_w(d, "MUTXRI", f_brand)
    d.text((pad + bw + 10, 34), "TERMINAL", font=f_brand, fill=TX2)
    if exchange:
        tag = exchange.upper()
        tw = _text_w(d, tag, f_brand)
        d.rectangle([W - pad - tw - 22, 28, W - pad, 64], outline=ACC, width=2)
        d.text((W - pad - tw - 11, 34), tag, font=f_brand, fill=ACC)

    # Portrait rail on the right, so the headline always gets a stable text column.
    # Tile size follows the count: two 190px portraits plus their captions do not
    # fit between the header and the footer, and the second would run off the card.
    shown = people[:2]
    n = len(shown)
    tile = 190 if n <= 1 else 150
    f_name_r = f_name if n <= 1 else _font("bold", 21)
    f_role_r = f_role if n <= 1 else _font("regular", 17)
    rail_x = W - pad - tile
    top, bottom = 128, H - 108
    slot = (bottom - top) / n if n else 0
    placeholders = []
    for i, p in enumerate(shown):
        asset = p.get("asset")
        src = _load((asset or {}).get("localPath"), Image)
        if src is not None:
            face = _circle(src, tile, Image, ImageDraw)
        else:
            face = _monogram(tile, p.get("name", "?"), Image, ImageDraw)
            placeholders.append(p.get("name"))
        y = int(top + i * slot)
        img.paste(face, (rail_x, y))
        cy = y + tile + 8
        # With two portraits the caption block must stay one name line high, or
        # the role runs behind the next circle. Rather than truncate a surname -
        # which loses the part of a name that identifies someone - middle names
        # are reduced to initials first: "Jane Wanjiru Mwangi" -> "Jane W. Mwangi".
        name_lines = _wrap(d, p.get("name", ""), f_name_r, tile)
        if n > 1 and len(name_lines) > 1:
            name_lines = [_shorten_name(d, p.get("name", ""), f_name_r, tile)]
        for line in name_lines[:2]:
            d.text((rail_x + (tile - _text_w(d, line, f_name_r)) / 2, cy),
                   line, font=f_name_r, fill=TX)
            cy += f_name_r.size + 4
        if p.get("role"):
            # With two portraits there is only room for a single role line -
            # a second one runs into the next person's circle.
            max_role_lines = 2 if n <= 1 else 1
            role_lines = _wrap(d, p["role"], f_role_r, tile)
            if len(role_lines) > max_role_lines:
                role_lines = role_lines[:max_role_lines]
                role_lines[-1] = _ellipsise(d, role_lines[-1] + " …", f_role_r, tile)
            for line in role_lines:
                d.text((rail_x + (tile - _text_w(d, line, f_role_r)) / 2, cy),
                       line, font=f_role_r, fill=TX3)
                cy += f_role_r.size + 3

    text_right = rail_x - 40 if shown else W - pad
    col_w = text_right - pad

    # Logo sits above the headline, scaled to a fixed height.
    ty = 132
    logo_img = _load((logo or {}).get("localPath"), Image)
    if logo_img is not None:
        # Commons logo files are often square with heavy padding, so a height-only
        # fit renders the mark tiny. Fit to a box and take whichever axis binds.
        box_h, box_w = 76, 320
        logo_img = logo_img.convert("RGBA")
        logo_img = _trim_alpha(logo_img)
        ratio = min(box_h / logo_img.height, box_w / logo_img.width)
        lw = max(1, int(logo_img.width * ratio))
        lh = max(1, int(logo_img.height * ratio))
        logo_img = logo_img.resize((lw, lh), Image.LANCZOS)
        bg = Image.new("RGB", logo_img.size, BG)
        bg.paste(logo_img, (0, 0), logo_img)
        img.paste(bg, (pad, ty))
        ty += lh + 26

    if eyebrow:
        d.text((pad, ty), eyebrow.upper()[:70], font=f_eyebrow, fill=ACC)
        ty += 34

    for line in _wrap(d, headline, f_head, col_w)[:5]:
        d.text((pad, ty), line, font=f_head, fill=TX)
        ty += 62

    # Footer: source, date, and one credit line per picture used.
    credits = []
    for a in [logo] + [p.get("asset") for p in people]:
        if a and a.get("attribution"):
            subj = a.get("subject") or ""
            credits.append("%s: %s" % (subj, a["attribution"]) if subj
                           else a["attribution"])
    foot_y = H - 30 - 18 * max(1, len(credits))
    d.line([pad, foot_y - 18, W - pad, foot_y - 18], fill=LINE, width=1)
    meta = " · ".join(x for x in [source, date, "mutxriterminal.com"] if x)
    d.text((pad, foot_y - 44), meta[:120], font=f_foot, fill=TX3)
    for cl in credits[:3]:
        d.text((pad, foot_y), ("Image: " + cl)[:150], font=f_foot, fill=TX3)
        foot_y += 18

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return {"path": out_path, "width": W, "height": H,
            "monograms": placeholders,
            "credits": credits,
            "bytes": os.path.getsize(out_path)}


# ------------------------------------------------------- planning from a story
# Words that begin a capitalised run without being part of a person's name.
_NOT_NAME = {
    "The", "A", "An", "And", "But", "For", "New", "Its", "His", "Her", "Their",
    "This", "That", "After", "Before", "As", "At", "In", "On", "Of", "To", "By",
    "With", "From", "Over", "Under", "Up", "Down", "Group", "Bank", "Plc", "Ltd",
    "Limited", "Holdings", "Exchange", "Securities", "Market", "Markets", "Board",
    "Chief", "Executive", "Officer", "Chairman", "Chairwoman", "Director",
    "Managing", "Deputy", "Acting", "Interim", "Company", "Corporation",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December", "Monday", "Tuesday",
    "Wednesday", "Thursday", "Friday", "Nigeria", "Kenya", "Egypt", "Africa",
    "African", "South", "North", "East", "West", "NSE", "NGX", "JSE", "EGX",
    "CEO", "CFO", "COO", "MD", "Q1", "Q2", "Q3", "Q4", "FY",
    # Industry nouns: "Dangote Refinery" is a plant, not a person, and a
    # capitalised-run heuristic will happily read it as one.
    "Refinery", "Refineries", "Cement", "Telecom", "Telecoms", "Insurance",
    "Airways", "Airlines", "Air", "Breweries", "Brewery", "Industries",
    "Industry", "Mills", "Motors", "Energy", "Power", "Oil", "Gas", "Mines",
    "Mining", "Resources", "Investments", "Investment", "Capital", "Partners",
    "Ventures", "Systems", "Technologies", "Technology", "Communications",
    "Media", "Press", "Sugar", "Tea", "Coffee", "Farms", "Plantations",
    "Properties", "Estates", "Stores", "Supermarkets", "Hotels", "Cotton",
    "Steel", "Glass", "Paper", "Foods", "Food", "Beverages", "Water",
    "Electric", "Electricity", "Trust", "Fund", "Index", "Refining",
}


def _company_surfaces():
    """Company name surfaces from the real listing, so a company is never read
    as a person. Cached on first use; empty if the universe is unavailable."""
    global _COMPANY_SURFACES
    if _COMPANY_SURFACES is None:
        try:
            from . import universe as U
            idx = U.build_index(U.load())
            _COMPANY_SURFACES = set(idx["names"])
        except Exception:
            _COMPANY_SURFACES = set()
    return _COMPANY_SURFACES


_COMPANY_SURFACES = None
_ROLE_CUES = [
    (r"\b(chief executive|ceo)\b", "Chief Executive"),
    (r"\b(chairman|chairwoman|chair)\b", "Chair"),
    (r"\b(chief financial officer|cfo)\b", "Chief Financial Officer"),
    (r"\b(managing director|md)\b", "Managing Director"),
    (r"\b(board member|director|non-executive)\b", "Board member"),
]


def people_in_text(text, exclude=()):
    """Heuristically pull personal names out of a headline.

    Two or three capitalised words in a row, minus the words that start a
    capitalised run without being a name. This is a guess, not an identification:
    everything it returns is checked against Wikipedia by bot/images.py before any
    picture is attached, and a human still approves the card.
    """
    import re as _re
    ex = {e.lower() for e in exclude if e}
    out, seen = [], set()
    for m in _re.finditer(r"\b([A-Z][a-z'\-]{1,15}(?:\s+[A-Z][a-z'\-]{1,15}){1,2})\b",
                          text or ""):
        cand = m.group(1)
        words = cand.split()
        if words[0] in _NOT_NAME or words[-1] in _NOT_NAME:
            continue
        if any(w in _NOT_NAME for w in words):
            continue
        low = cand.lower()
        if low in seen or any(low in e or e in low for e in ex):
            continue
        # A name that matches a listed company is a company.
        surfaces = _company_surfaces()
        if low in surfaces or any(low.startswith(s + " ") or s == low
                                  for s in surfaces if len(s) > 4):
            continue
        seen.add(low)
        out.append(cand)
    return out


def _role_for(text, name):
    """Nearest role cue to a name, or a neutral default."""
    import re as _re
    window = text
    i = text.find(name)
    if i >= 0:
        window = text[max(0, i - 60): i + len(name) + 60]
    for pat, label in _ROLE_CUES:
        if _re.search(pat, window, _re.I):
            return label
    return "Named in the story"


def plan_from_signal(signal, use_model=True):
    """Work out what a card for this signal should contain.

    The company comes from the securities the signal is already linked to - that
    binding was computed against the real listing, so it beats asking a model to
    guess an issuer from a headline. Only the people and the headline wording need
    reading, and the model does that when it is available.
    """
    secs = signal.get("securities") or []
    company = secs[0].get("name") if secs else None
    ticker = secs[0].get("ticker") if secs else None
    text = " ".join(filter(None, [signal.get("title"), signal.get("summary")]))
    plan = {"company": company, "ticker": ticker,
            "exchange": signal.get("exchange"),
            "headline": (signal.get("title") or "").strip(),
            "people": [], "eyebrow": None, "source": signal.get("publisher"),
            "readBy": "heuristic", "confidence": "low"}

    if use_model:
        try:
            from . import analyst
            if analyst.available():
                got = analyst.read_story(signal.get("title", ""),
                                         signal.get("summary", ""))
                plan["headline"] = got.get("headline") or plan["headline"]
                plan["company"] = company or got.get("company")
                plan["people"] = [{"name": p["name"], "role": p.get("role")}
                                  for p in got.get("people", [])][:2]
                plan["eyebrow"] = (got.get("event_type") or "").replace("_", " ")
                plan["readBy"] = "model"
                plan["confidence"] = got.get("confidence", "medium")
                return plan
        except Exception as e:
            plan["modelError"] = str(e)[:120]

    names = people_in_text(text, exclude=[company or "", signal.get("publisher") or ""])
    plan["people"] = [{"name": n, "role": _role_for(text, n)} for n in names[:2]]
    return plan


def build_for_story(headline, out_path, *, company=None, ticker=None, exchange=None,
                    people=None, eyebrow=None, source=None, date=None,
                    allow_unlicensed=False):
    """Resolve every picture for a story, then compose the card.

    Returns (result, provenance). Provenance lists what was found, what was
    refused on licensing, and who ended up as a monogram - so the human approving
    the post can see exactly what is in the image and on what terms.
    """
    prov = {"logo": None, "people": [], "refused": [], "notes": []}

    logo_asset = None
    if company:
        a, rep = I.find_logo(company, ticker)
        if a:
            ok, refused = I.publishable([a], allow_unlicensed)
            if ok:
                logo_asset = I.fetch(a)
                if logo_asset is None:
                    prov["notes"].append("logo found but could not be downloaded: %s"
                                         % a.get("error"))
            else:
                prov["refused"].append(
                    {"what": "logo", "subject": company,
                     "licence": a.get("licence"), "reuse": a["reuse"],
                     "why": "licence not established for republication"})
            prov["logo"] = a
        else:
            prov["notes"].append("no logo found for %s (%s)"
                                 % (company, rep.get("reason", "")))

    resolved = []
    for p in (people or []):
        name, role = p.get("name"), p.get("role")
        asset, rep = I.find_person(name, company)
        entry = {"name": name, "role": role, "found": bool(asset),
                 "reason": rep.get("reason")}
        if asset:
            ok, refused = I.publishable([asset], allow_unlicensed)
            if ok:
                fetched = I.fetch(asset)
                if fetched is None:
                    entry["found"] = False
                    entry["reason"] = "download failed: %s" % asset.get("error")
                    asset = None
                else:
                    entry.update({"licence": asset.get("licence"),
                                  "confidence": asset.get("confidence"),
                                  "needsVisualCheck": asset.get("needsVisualCheck"),
                                  "source": asset.get("sourcePage")})
            else:
                prov["refused"].append(
                    {"what": "portrait", "subject": name,
                     "licence": asset.get("licence"), "reuse": asset["reuse"],
                     "why": "licence not established for republication"})
                asset = None
                entry["found"] = False
                entry["reason"] = "found but licence not republishable"
        resolved.append({"name": name, "role": role, "asset": asset})
        prov["people"].append(entry)

    result = build(headline, out_path, logo=logo_asset, people=resolved,
                   exchange=exchange, eyebrow=eyebrow, source=source, date=date)
    if result["monograms"]:
        prov["notes"].append(
            "no licensed photograph found for %s - shown as initials, not a photo"
            % ", ".join(result["monograms"]))
    return result, prov
