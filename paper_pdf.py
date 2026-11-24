"""paper_pdf.py - the PDF statement for a SIMULATED order, built with the standard library.

WHY THERE IS NO PDF LIBRARY HERE. The backend runs on Render from a plain
requirements set and the rest of it is stdlib; adding reportlab to draw one page
is a dependency, a build and a licence for something a few hundred lines of PDF
syntax does honestly. This writes the file directly: a single A4 page, Helvetica
and Helvetica-Bold, text and ruled lines.

THE LAYOUT IS A CLIENT STATEMENT, because that is what shows a reader they have
bought: who the account belongs to, what the balance was, the purchase itself as
a row with quantity, price, debit and credit, and the balance it left. The owner
asked for this shape (2026-11-24) and it reads far better than a one line
confirmation.

WHAT IT IS NOT, AND WHAT IS DELIBERATELY ABSENT.
  * It is not a broker's statement and names no broker. MUTXRI TERMINAL is not a
    broker, a dealer or an investment adviser, holds no client money and no
    client securities, and cannot place an order on any exchange.
  * There is NO CDS account number, NO national ID, NO passport number and no
    other identifier of that kind anywhere on the page, and this module is never
    given one. A paper account needs none of them, and a document that carried
    them would be a document worth stealing.
  * The reader's own name and the account's own reference are all that identify
    it, and both come from the signed in session.
  * A band across the head states that every row is simulated, that no money
    moved and that it is not a contract note. Every page of it says so.
"""

A4_W, A4_H = 595.28, 841.89
L = 48.0                      # left margin
R = A4_W - 48.0               # right margin


def _esc(t):
    """Escape for a PDF literal, and transliterate anything outside WinAnsi."""
    out = []
    for ch in str(t):
        if ch in ("\\", "(", ")"):
            out.append("\\" + ch)
        elif ord(ch) < 32:
            out.append(" ")
        elif ord(ch) < 127:
            out.append(ch)
        else:
            out.append({"’": "'", "‘": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " ",
                        "·": "-"}.get(ch, "?"))
    return "".join(out)


_W = {}        # crude width table: Helvetica averages, enough to right align


def _width(text, size, bold=False):
    # Helvetica digits and most lower case sit near 0.55em; caps near 0.70em.
    w = 0.0
    for ch in str(text):
        if ch.isupper():
            w += 0.68
        elif ch.isdigit() or ch in ".,":
            w += 0.52 if ch in ".," else 0.556
        elif ch == " ":
            w += 0.28
        else:
            w += 0.52
    return w * size * (1.04 if bold else 1.0)


class Page(object):
    """A tiny drawing surface: text at a point, right aligned text, and rules."""

    def __init__(self):
        self.ops = []

    def text(self, x, y, s, size=9.5, bold=False, grey=False):
        self.ops.append("BT /%s %.1f Tf %s 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
                        % ("F2" if bold else "F1", size,
                           "0.42 0.42 0.42 rg" if grey else "0 0 0 rg",
                           x, y, _esc(s)))

    def right(self, x, y, s, size=9.5, bold=False, grey=False):
        self.text(x - _width(s, size, bold), y, s, size, bold, grey)

    def rule(self, y, x0=L, x1=R, w=0.6, grey=0.75):
        self.ops.append("%.2f %.2f %.2f RG %.2f w %.2f %.2f m %.2f %.2f l S"
                        % (grey, grey, grey, w, x0, y, x1, y))

    def box(self, x0, y0, x1, y1, fill=(0.95, 0.95, 0.95)):
        self.ops.append("%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f"
                        % (fill[0], fill[1], fill[2], x0, y0, x1 - x0, y1 - y0))

    def stream(self):
        return "\n".join(self.ops)


def _build(page, title="PAPER TRADING STATEMENT"):
    content = page.stream().encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
         "/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>"
         % (A4_W, A4_H)).encode("latin-1"),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ("<< /Title (%s) /Producer (MUTXRI TERMINAL paper trading) >>" % _esc(title)).encode("latin-1"),
    ]
    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(buf)
    n = len(objs) + 1
    buf += b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        buf += ("%010d 00000 n \n" % off).encode()
    buf += (b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R /Info "
            + str(len(objs)).encode() + b" 0 R >>\nstartxref\n"
            + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(buf)


def _wrap(text, width, size, bold=False):
    """Break `text` into lines that fit `width` points, on spaces."""
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur and _width(trial, size, bold) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def _money(x, ccy=""):
    try:
        return ("%s %s" % (ccy, format(float(x), ",.2f"))).strip()
    except Exception:
        return "-"


def _qty(x):
    try:
        f = float(x)
        return format(int(f), ",") if f == int(f) else format(f, ",.4f")
    except Exception:
        return str(x)


def order_record(order, account):
    """One page: the account, the purchase or sale, and the balance it left."""
    def g(k, d=""):
        v = order.get(k, d)
        return d if v is None else v

    p = Page()
    ccy = str(g("ccy", ""))
    side = str(g("side", "")).upper()
    sym = str(g("sym", ""))
    qty = g("qty", 0)
    px = g("px", 0)
    try:
        gross = float(qty) * float(px)
    except Exception:
        gross = 0.0
    try:
        fees = float(order.get("fees", 0) or 0)
    except Exception:
        fees = 0.0
    buying = side in ("BUY",)
    # A BUY takes cash out of the account (a debit); a SELL or a SHORT puts cash
    # in (a credit). The consideration carries the costs on the side that pays
    # them, which is the side the cash actually moved on.
    debit = gross + fees if buying else 0.0
    credit = 0.0 if buying else max(gross - fees, 0.0)

    y = A4_H - 52

    # ---- the firm block. No broker is named because none is involved. --------
    p.text(L, y, "MUTXRI TERMINAL", 15, bold=True)
    y -= 13
    p.text(L, y, "African markets terminal - paper trading", 8.5, grey=True)
    y -= 10
    p.text(L, y, "mutxriterminal.com", 8.5, grey=True)
    p.right(R, A4_H - 52, "PAPER TRADING STATEMENT", 13, bold=True)
    p.right(R, A4_H - 65, "Simulated orders only", 8.5, grey=True)

    y -= 16
    # ---- the band. It is the first thing read and it is not subtle. ----------
    p.box(L, y - 20, R, y + 2, fill=(0.97, 0.90, 0.72))
    p.text(L + 8, y - 7, "SIMULATED. NOT A CONTRACT NOTE. NO MONEY MOVED AND NO SECURITY CHANGED HANDS.",
           9, bold=True)
    y -= 34

    # ---- who the account belongs to -----------------------------------------
    def field(x, yy, k, v, kw=92):
        p.text(x, yy, k, 8.5, grey=True)
        p.text(x + kw, yy, ":  " + str(v), 9)

    mid = L + 262
    field(L, y, "Account name", account.get("name") or "-")
    field(mid, y, "Statement date", g("filled", "-"))
    y -= 13
    field(L, y, "Paper account", account.get("ref") or "-")
    field(mid, y, "Market", g("ex", "-"))
    y -= 13
    field(L, y, "Account type", "Simulated (no custody)")
    field(mid, y, "Reference", g("ref", "-"))
    y -= 13
    # The absence is stated. A reader who has seen a real statement will look for
    # these lines, and silence would read as an omission rather than a choice.
    p.text(L, y, "No CDS account, national ID or passport number is held for a paper account.",
           8, grey=True)
    y -= 16
    p.rule(y)
    y -= 16

    # ---- the transaction ----------------------------------------------------
    p.text(L, y, "ACCOUNT ACTIVITY", 9.5, bold=True)
    y -= 14

    # COLUMN EDGES, MEASURED RATHER THAN GUESSED. The first cut put the price
    # column's right edge 68pt from the debit column's, and a five figure debit
    # ran straight through the price beside it: the page read "33.5|4,203.50"
    # where it should have read "33.50" and "34,203.50". Each money column is
    # given room for a figure in the millions with its separators.
    cDate, cType, cPart = L, L + 58, L + 120
    cQtyR, cPxR, cDrR, cCrR = L + 312, L + 374, L + 452, R

    p.box(L - 4, y - 4, R + 4, y + 10, fill=(0.93, 0.93, 0.93))
    p.text(cDate, y, "Date", 8, bold=True)
    p.text(cType, y, "Type", 8, bold=True)
    p.text(cPart, y, "Particulars", 8, bold=True)
    p.right(cQtyR, y, "Qty.", 8, bold=True)
    p.right(cPxR, y, "Price", 8, bold=True)
    p.right(cDrR, y, "Debit", 8, bold=True)
    p.right(cCrR, y, "Credit", 8, bold=True)
    y -= 15

    p.text(cDate, y, g("filled", "-"), 8.5)
    p.text(cPart, y, "Opening balance", 8.5)
    p.right(cCrR, y, _money(account.get("opening"), ccy), 8.5)
    y -= 13

    word = "Purchase" if buying else ("Sale" if side == "SELL" else "Short sale")
    particulars = "%s of %s %s at %s%s" % (
        word, _qty(qty), sym, _money(px, ccy),
        (" - " + str(g("name"))) if g("name") else "")
    p.text(cDate, y, g("filled", "-"), 8.5)
    p.text(cType, y, word, 8.5)
    # WRAPPED ON A WORD, not on a character count. Cutting at a fixed width put
    # "Safarico" on one line and "m Plc" on the next.
    lines = _wrap(particulars, cQtyR - 8 - cPart, 8.5)
    p.text(cPart, y, lines[0] if lines else "", 8.5)
    p.right(cQtyR, y, _qty(qty), 8.5)
    p.right(cPxR, y, _money(px), 8.5)
    p.right(cDrR, y, _money(debit) if buying else "0.00", 8.5)
    p.right(cCrR, y, "0.00" if buying else _money(credit), 8.5)
    y -= 12
    for extra in lines[1:3]:
        p.text(cPart, y, extra, 8, grey=True)
        y -= 11
    p.text(cPart, y, "Order type %s, simulated fill against the published close."
           % str(g("type", "MKT")), 8, grey=True)
    y -= 12
    if fees:
        p.text(cPart, y, "Costs modelled on the %s schedule: %s" % (g("ex", ""), _money(fees, ccy)),
               8, grey=True)
    else:
        p.text(cPart, y, "No costs modelled on this order.", 8, grey=True)
    y -= 14
    p.rule(y)
    y -= 14

    p.text(cPart, y, "Closing balance", 9, bold=True)
    p.right(cCrR, y, _money(account.get("cash"), ccy), 9, bold=True)
    y -= 20

    # ---- the holding this left ----------------------------------------------
    p.text(L, y, "HOLDING AFTER THIS ORDER", 9.5, bold=True)
    y -= 14
    p.text(L, y, "%s" % sym, 8.5)
    p.text(cPart, y, str(account.get("position") or "-"), 8.5)
    y -= 13
    p.text(L, y, "Realised to date", 8.5, grey=True)
    p.text(cPart, y, _money(account.get("realised"), ccy), 8.5)
    y -= 22

    p.rule(y)
    y -= 14
    p.text(L, y, "*** End of statement ***", 8.5, grey=True)
    y -= 22

    for line in [
        "MUTXRI TERMINAL is not a broker, a dealer or an investment adviser. It holds no client money",
        "and no client securities, and it cannot place an order on any exchange. This statement records",
        "orders simulated in your own browser against published end-of-day prices. No order reached a",
        "market, no money was paid or received, and no security was bought or sold. The document has no",
        "settlement value, gives you title to nothing, and is not advice or a recommendation.",
        "",
        "You are receiving this because you switched order emails on in the TRADE panel.",
    ]:
        p.text(L, y, line, 7.5, grey=True)
        y -= 9.5

    return _build(p)
