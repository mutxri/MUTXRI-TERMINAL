"""paper_mail.py - mail a signed-in reader the PDF record of ONE simulated order.

This is a separate module rather than another function in auth_api.py because it
is not about authentication: it needs the session only to learn which mailbox
belongs to the reader who asked for the record.

THE RECIPIENT IS NEVER TAKEN FROM THE REQUEST. The caller resolves it from the
session token, exactly as the chat room's mention mail does. Reading a recipient
out of the request body would turn this route into an open relay that sends
official-looking documents from this domain to anyone who asked.

THE DOCUMENT SAYS WHAT IT IS, EVERYWHERE: the subject line, the message body and
the PDF itself all carry PAPER and the statement that no money moved and no
broker was involved. MUTXRI TERMINAL is not a broker; a document from it that
read like a contract note would be a false claim to be one. Those words are not
softened and are not optional.

The sending mailbox comes from the environment (MAIL_SERVER, MAIL_USER,
MAIL_PASS, MAIL_FROM, MAIL_PORT), the same variables the other mailers read. No
address is written into this file. Without MAIL_PASS the function returns a
stated failure and sends nothing.
"""

import os


def send_order_record(to_address, to_name, order, account):
    """Send the record. Returns (sent, error_message)."""
    try:
        import smtplib
        import html as _html
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication
        from email.utils import formataddr
        import paper_pdf

        server = os.environ.get("MAIL_SERVER", "")
        user = os.environ.get("MAIL_USER", "")
        pwd = os.environ.get("MAIL_PASS", "")
        sender = os.environ.get("MAIL_FROM", "") or user
        if not server or not user or not pwd or not sender:
            print("[paper] mail is not configured - order PDF not sent", flush=True)
            return False, "order emails are not configured on the server yet"
        if not to_address:
            return False, "this account has no address on file"

        pdf = paper_pdf.order_record(order, account)

        whom = str(to_name or "").strip()
        first = _html.escape(whom.split()[0]) if whom else "there"
        side = _html.escape(str(order.get("side", "")))
        sym = _html.escape(str(order.get("sym", "")))
        try:
            qty = _html.escape(format(int(float(order.get("qty", 0))), ","))
        except Exception:
            qty = _html.escape(str(order.get("qty", "")))
        try:
            px = _html.escape(format(float(order.get("px", 0)), ",.2f"))
        except Exception:
            px = _html.escape(str(order.get("px", "")))
        ccy = _html.escape(str(order.get("ccy", "")))

        body = (
            '<div style="background:#000;color:#f0f0f0;font-family:monospace;padding:32px">'
            '<h2 style="color:#33e29a;margin:0 0 4px">MUTXRI TERMINAL</h2>'
            '<div style="color:#e0a340;font-weight:700;letter-spacing:.08em;margin-bottom:18px">'
            'PAPER TRADING RECORD</div>'
            '<p>Hi %s,</p>'
            '<p>Your simulated order filled: <b style="color:#33e29a">%s %s %s</b> at %s %s.</p>'
            '<p style="border-left:3px solid #e0a340;padding-left:12px;color:#d2d2d2">'
            'This was a paper order. It filled against a published end-of-day price inside your '
            'own browser. No order was sent to any exchange, no broker was involved, no money was '
            'paid or received, and no security was bought or sold.</p>'
            '<p>The attached PDF is a record of it. It is not a contract note and has no '
            'settlement value.</p>'
            '<p style="color:#6a6a6a;font-size:12px">MUTXRI TERMINAL is not a broker, a dealer or '
            'an investment adviser, and holds no client money and no client securities. You are '
            'getting this because you switched order emails on in the TRADE panel; switch them '
            'off there at any time.</p></div>'
        ) % (first, side, qty, sym, ccy, px)

        msg = MIMEMultipart()
        # PAPER LEADS THE SUBJECT. In an inbox the subject line is most of what
        # gets read, and "BUY 1,000 SCOM filled" on its own looks exactly like a
        # broker's confirmation at a glance.
        msg["Subject"] = "PAPER (simulated, not a trade): %s %s %s" % (side, qty, sym)
        msg["From"] = formataddr(("MUTXRI TERMINAL (paper trading)", sender))
        msg["To"] = to_address
        msg.attach(MIMEText(body, "html"))

        ref = "".join(ch for ch in str(order.get("ref", "order")) if ch.isalnum() or ch in "-_")
        att = MIMEApplication(pdf, _subtype="pdf")
        att.add_header("Content-Disposition", "attachment",
                       filename="mutxri-paper-record-%s.pdf" % (ref or "order"))
        msg.attach(att)

        with smtplib.SMTP(server, int(os.environ.get("MAIL_PORT", "587")), timeout=30) as sm:
            sm.starttls()
            sm.login(user, pwd)
            sm.sendmail(sender, [to_address], msg.as_string())
        return True, ""
    except Exception as e:
        # The address is not printed: this log is read in a shared dashboard.
        print("[paper] order PDF failed: %s" % str(e)[:160], flush=True)
        return False, "the email could not be sent"
