#!/usr/bin/env python3
"""signin_notify.py - email a user when their account is signed into.

Two jobs, one entry point:
  * a welcome note the first time an account is created
  * a security notice on later sign-ins, but only from a device we have not
    seen for that account before

Sending happens on a daemon thread. A sign-in must never wait on SMTP, and a
mail failure must never fail the sign-in - the user is already authenticated by
the time this is called.

Configured entirely by environment (same variables the rest of the backend
uses). With SES_SERVER / SES_USER / SES_PASS unset this becomes a no-op, so
local development never tries to send mail.
"""
import hashlib
import html
import os
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SITE = "https://mutxriterminal.com"

# Godel palette: mint on black (matches the terminal and the existing signup email).
INK = "#000000"
INK2 = "#0a0a0a"
LINE = "#1a1a1a"
TX = "#f0f0f0"
TX2 = "#9a9a9a"
TX3 = "#6a6a6a"
ACC = "#33e29a"

PROVIDERS = {"google": "Google", "github": "GitHub", "password": "email and password"}


def _cfg():
    return {
        "server": os.environ.get("SES_SERVER", ""),
        "port": int(os.environ.get("SES_PORT", "587")),
        "user": os.environ.get("SES_USER", ""),
        "password": os.environ.get("SES_PASS", ""),
        "sender": os.environ.get("BRIEF_FROM", "jimmy@mutxri.com"),
    }


def describe_device(user_agent):
    """A User-Agent string is unreadable in an email; a person needs to
    recognise their own device at a glance or the notice is useless."""
    ua = (user_agent or "").lower()
    if not ua:
        return "an unrecognised device"

    if "edg/" in ua:
        browser = "Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "chrome" in ua and "chromium" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    else:
        browser = "an unrecognised browser"

    if "android" in ua:
        platform = "Android"
    elif "iphone" in ua:
        platform = "iPhone"
    elif "ipad" in ua:
        platform = "iPad"
    elif "windows" in ua:
        platform = "Windows"
    elif "mac os" in ua or "macintosh" in ua:
        platform = "macOS"
    elif "linux" in ua:
        platform = "Linux"
    else:
        platform = None

    return f"{browser} on {platform}" if platform else browser


def device_fingerprint(user_agent, ip):
    """Identifies a device well enough to avoid emailing on every sign-in,
    without storing the raw address. Only the first three octets are used so a
    normal DHCP change on the same network does not read as a new device."""
    net = ".".join((ip or "").split(".")[:3])
    raw = f"{describe_device(user_agent)}|{net}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _plain(first, new_account, provider_label, when, device, ip):
    if new_account:
        opening = (
            f"Hi {first},\n\n"
            "Your MUTXRI TERMINAL account is ready. You signed up with "
            f"{provider_label}.\n\n"
            "You now have end-of-day quotes, financial statements and filings for "
            "1,021 securities across the JSE, NGX, NSE and EGX."
        )
    else:
        opening = (
            f"Hi {first},\n\n"
            f"Your MUTXRI TERMINAL account was just signed into with {provider_label} "
            "from a device we have not seen before."
        )
    return (
        f"{opening}\n\n"
        f"  When    {when}\n"
        f"  Device  {device}\n"
        f"  IP      {ip or 'unknown'}\n\n"
        f"Open the terminal: {SITE}/terminal/\n\n"
        "If this was not you, reply to this email and we will lock the account.\n"
        "MUTXRI TERMINAL\n"
    )


def _html(first, new_account, provider_label, when, device, ip):
    # escape here rather than trusting the caller - this is the only function
    # that renders markup, so it is the only place that can get it wrong
    first = html.escape(str(first or ""))
    device = html.escape(str(device or ""))
    ip = html.escape(str(ip or ""))
    provider_label = html.escape(str(provider_label or ""))
    when = html.escape(str(when or ""))
    if new_account:
        headline = "Your account is ready"
        body = (
            f"You signed up with {provider_label}. You now have end-of-day quotes, "
            "financial statements and filings for 1,021 securities across the JSE, "
            "NGX, NSE and EGX."
        )
    else:
        headline = "New sign-in to your account"
        body = (
            f"Your account was just signed into with {provider_label}, from a device "
            "we have not seen before."
        )

    def row(label, value):
        return (
            f'<tr>'
            f'<td style="padding:7px 0;color:{TX3};font-size:12px;letter-spacing:.09em;'
            f'text-transform:uppercase;width:82px">{label}</td>'
            f'<td style="padding:7px 0;color:{TX};font-size:14px">{value}</td>'
            f'</tr>'
        )

    return f"""<!doctype html>
<html><body style="margin:0;background:{INK};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{INK};padding:36px 16px">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:520px;background:{INK};border:1px solid {LINE};border-radius:8px">
    <tr><td style="padding:22px 28px;border-bottom:1px solid {LINE}">
      <span style="font-family:'Oxygen Mono',Consolas,monospace;font-size:13px;
                   letter-spacing:.14em;font-weight:700;color:{TX}">MUTXRI
        <span style="color:{ACC}">TERMINAL</span></span>
    </td></tr>

    <tr><td style="padding:32px 28px 8px">
      <div style="font-family:'Oxygen Mono',Consolas,monospace;font-size:11px;
                  letter-spacing:.2em;text-transform:uppercase;color:{ACC};
                  margin-bottom:14px">Account</div>
      <h1 style="margin:0 0 14px;font-family:Inter,Helvetica,Arial,sans-serif;
                 font-size:24px;line-height:1.2;color:{TX};font-weight:700">{headline}</h1>
      <p style="margin:0 0 6px;font-family:Inter,Helvetica,Arial,sans-serif;
                font-size:15px;line-height:1.6;color:{TX2}">Hi {first},</p>
      <p style="margin:0;font-family:Inter,Helvetica,Arial,sans-serif;
                font-size:15px;line-height:1.6;color:{TX2}">{body}</p>
    </td></tr>

    <tr><td style="padding:20px 28px">
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%"
             style="background:{INK2};border:1px solid {LINE};border-radius:6px;padding:14px 18px;
                    font-family:'Oxygen Mono',Consolas,monospace">
        {row('When', when)}
        {row('Device', device)}
        {row('IP', ip or 'unknown')}
      </table>
    </td></tr>

    <tr><td style="padding:6px 28px 30px">
      <a href="{SITE}/terminal/"
         style="display:inline-block;background:{ACC};color:#00160e;text-decoration:none;
                font-family:'Oxygen Mono',Consolas,monospace;font-size:13px;font-weight:700;
                padding:12px 22px;border-radius:5px">Open Terminal &rarr;</a>
    </td></tr>

    <tr><td style="padding:18px 28px 26px;border-top:1px solid {LINE}">
      <p style="margin:0;font-family:Inter,Helvetica,Arial,sans-serif;font-size:12px;
                line-height:1.6;color:{TX3}">
        If this was not you, reply to this email and we will lock the account immediately.
      </p>
    </td></tr>
  </table>
</td></tr>
</table>
</body></html>"""


def _send(to_email, first, new_account, provider_label, when, device, ip):
    cfg = _cfg()
    subject = ("Welcome to MUTXRI TERMINAL"
               if new_account else
               f"New sign-in to MUTXRI TERMINAL from {device}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"MUTXRI TERMINAL <{cfg['sender']}>"
    msg["To"] = to_email
    msg.attach(MIMEText(_plain(first, new_account, provider_label, when, device, ip),
                        "plain", "utf-8"))
    msg.attach(MIMEText(_html(first, new_account, provider_label, when, device, ip),
                        "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP(cfg["server"], cfg["port"], timeout=30) as smtp:
        smtp.starttls(context=context)
        smtp.login(cfg["user"], cfg["password"])
        smtp.sendmail(cfg["sender"], [to_email], msg.as_string())


def notify_signin(email, name="", provider="password", new_account=False,
                  user_agent="", ip="", known_devices=None, on_new_device=None):
    """Email the user about this sign-in. Returns the device fingerprint so the
    caller can persist it, or None when nothing was sent.

    known_devices  fingerprints already seen for this account
    on_new_device  called with the new fingerprint when one is recorded, so the
                   caller can save it against the user
    """
    cfg = _cfg()
    email = (email or "").strip()
    if not email:
        return None
    if not (cfg["server"] and cfg["user"] and cfg["password"]):
        return None  # mail not configured; stay silent rather than raise

    fingerprint = device_fingerprint(user_agent, ip)
    if not new_account and fingerprint in set(known_devices or []):
        return fingerprint  # same device as last time - no email, no noise

    if callable(on_new_device):
        try:
            on_new_device(fingerprint)
        except Exception as exc:
            print(f"[signin] could not record device for {email}: {str(exc)[:80]}", flush=True)

    first = ((name or "").strip().split() or [email])[0]
    device = describe_device(user_agent)
    provider_label = PROVIDERS.get(provider, provider or "email and password")
    when = datetime.now(timezone.utc).strftime("%d %b %Y at %H:%M UTC")
    client_ip = (ip or "").strip()

    def worker():
        try:
            _send(email, first, new_account, provider_label, when, device, client_ip)
            kind = "welcome" if new_account else "new-device"
            print(f"[signin] {kind} email sent to {email}", flush=True)
        except Exception as exc:
            # the user is already signed in; mail is best effort
            print(f"[signin] email failed for {email}: {str(exc)[:120]}", flush=True)

    threading.Thread(target=worker, name="signin-notify", daemon=True).start()
    return fingerprint


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target:
        print("usage: python signin_notify.py you@example.com [--welcome]")
        raise SystemExit(1)
    cfg = _cfg()
    if not (cfg["server"] and cfg["user"] and cfg["password"]):
        print("SES_SERVER / SES_USER / SES_PASS are not set - nothing would be sent.")
        raise SystemExit(1)
    notify_signin(
        target,
        name="Jimmy Muturi",
        provider="google",
        new_account="--welcome" in sys.argv,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36",
        ip="102.68.77.14",
    )
    time.sleep(20)  # let the daemon thread finish before the process exits
    print("done - check the inbox")
