#!/usr/bin/env python3
"""AFRI Terminal - Morning Brief email.
Pulls the terminal's dashboard data (indices, top movers, FX, rates, news, dividends)
and emails a clean morning brief to the owner via Zoho SMTP.
Run: python morning_brief.py [--to jimmy@mutxri.com]
"""
import json, smtplib, ssl, time, urllib.request, sys, os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

API = "http://127.0.0.1:8081"

# Mail credentials - from environment (see .env.example); never commit real creds.
# Zoho, not SES: the SES account is sandboxed (200/day, verified recipients only)
# and its domain identity is unverified, so SES mail is signed with Amazon's default
# key and fails DMARC alignment for mutxri.com. Zoho's 'zmail' DKIM aligns.
# smtppro.zoho.com is the host for custom-domain (paid) accounts; free/personal
# accounts use smtp.zoho.com. Override with MAIL_SERVER.
MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtppro.zoho.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
MAIL_USER = os.environ.get("MAIL_USER", "")
MAIL_PASS = os.environ.get("MAIL_PASS", "")
FROM = os.environ.get("MAIL_FROM", MAIL_USER or "jimmy@mutxri.com")

def api_get(path):
    try:
        req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"error": str(e)}

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def build_brief():
    now = datetime.now().strftime("%A, %d %B %Y · %H:%M")
    rows = []

    # 1) FX
    fx = api_get("/api/quotes?symbols=USDZAR=X,USDEGP=X,USDKES=X,USDNGN=X,EURZAR=X,GBPZAR=X")
    fx_html = ""
    if isinstance(fx, dict) and fx:
        pairs = [("USD/ZAR", "USDZAR=X"), ("USD/EGP", "USDEGP=X"), ("USD/KES", "USDKES=X"),
                 ("USD/NGN", "USDNGN=X"), ("EUR/ZAR", "EURZAR=X"), ("GBP/ZAR", "GBPZAR=X")]
        fx_html = "<table cellpadding='6' style='border-collapse:collapse;width:100%'>"
        fx_html += "<tr style='background:#111'><th style='text-align:left;color:#33e29a;border-bottom:1px solid #333'>Pair</th><th style='text-align:right;color:#33e29a;border-bottom:1px solid #333'>Rate</th><th style='text-align:right;color:#33e29a;border-bottom:1px solid #333'>Day</th></tr>"
        for label, sym in pairs:
            q = fx.get(sym, {})
            if q and q.get("price") is not None:
                chg = q.get("changePct")
                col = "#33e29a" if (chg or 0) >= 0 else "#f87171"
                sign = "+" if (chg or 0) >= 0 else ""
                fx_html += f"<tr><td style='border-bottom:1px solid #222'>{label}</td><td style='text-align:right;border-bottom:1px solid #222'><b>{q['price']:.4f}</b></td><td style='text-align:right;color:{col};border-bottom:1px solid #222'>{sign}{chg:.2f}%</td></tr>"
        fx_html += "</table>"

    # 2) Indices (JSE Top40 + EGX30 live)
    idx_html = ""
    idx_data = []
    for sym, label in [("^J203.JO", "JSE Top 40"), ("^EGX30.CA", "EGX30")]:
        q = api_get(f"/api/quotes?symbols={urllib.parse.quote(sym)}")
        if isinstance(q, dict):
            val = q.get(sym, {})
            if val and val.get("price") is not None:
                idx_data.append((label, val))
    if idx_data:
        idx_html = "<table cellpadding='6' style='border-collapse:collapse;width:100%'>"
        idx_html += "<tr style='background:#111'><th style='text-align:left;color:#33e29a;border-bottom:1px solid #333'>Index</th><th style='text-align:right;color:#33e29a;border-bottom:1px solid #333'>Level</th><th style='text-align:right;color:#33e29a;border-bottom:1px solid #333'>Day</th></tr>"
        for label, q in idx_data:
            chg = q.get("changePct") or 0
            col = "#33e29a" if chg >= 0 else "#f87171"
            sign = "+" if chg >= 0 else ""
            idx_html += f"<tr><td style='border-bottom:1px solid #222'>{label}</td><td style='text-align:right;border-bottom:1px solid #222'><b>{q['price']:,.0f}</b></td><td style='text-align:right;color:{col};border-bottom:1px solid #222'>{sign}{chg:.2f}%</td></tr>"
        idx_html += "</table>"

    # 3) Rates
    rates = api_get("/api/rates")
    rates_html = ""
    if isinstance(rates, dict) and rates.get("central_banks"):
        rates_html = "<table cellpadding='6' style='border-collapse:collapse;width:100%'>"
        rates_html += "<tr style='background:#111'><th style='text-align:left;color:#33e29a;border-bottom:1px solid #333'>Bank</th><th style='text-align:right;color:#33e29a;border-bottom:1px solid #333'>Rate</th><th style='text-align:right;color:#33e29a;border-bottom:1px solid #333'>As of</th></tr>"
        for r in rates["central_banks"]:
            rates_html += f"<tr><td style='border-bottom:1px solid #222'>{esc(r['country'])} ({esc(r['bank'])})</td><td style='text-align:right;border-bottom:1px solid #222'><b>{r['rate']}%</b></td><td style='text-align:right;border-bottom:1px solid #222'>{esc(r['updated'])}</td></tr>"
        rates_html += "</table>"

    # 4) Top news (headlines only)
    news = api_get("/api/news")
    news_html = ""
    if isinstance(news, list) and news:
        items = []
        for n in news[:12]:
            items.append(f"<li style='margin:6px 0'><b>{esc(n['title'][:110])}</b> <span style='color:#888'>- {esc(n['source'])}</span></li>")
        news_html = "<ul style='padding-left:18px;margin:0'>" + "".join(items) + "</ul>"

    # 5) Market status
    status = "Market data via local terminal proxy. JSE/EGX live, NGX/NSE EOD."

    html = f"""<div style="background:#000;color:#f0f0f0;font-family:'Segoe UI',Arial,sans-serif;padding:24px;max-width:640px">
  <div style="border-bottom:2px solid #33e29a;padding-bottom:10px;margin-bottom:16px">
    <div style="font-size:22px;font-weight:800;color:#33e29a;letter-spacing:1px">AFRI TERMINAL · MORNING BRIEF</div>
    <div style="color:#9a9a9a;font-size:12px">{now} · {status}</div>
  </div>

  <div style="font-size:13px;font-weight:700;color:#33e29a;margin:14px 0 6px">INDICES</div>
  {idx_html or '<p style="color:#666">indices unavailable</p>'}

  <div style="font-size:13px;font-weight:700;color:#33e29a;margin:14px 0 6px">FX</div>
  {fx_html or '<p style="color:#666">fx unavailable</p>'}

  <div style="font-size:13px;font-weight:700;color:#33e29a;margin:14px 0 6px">CENTRAL BANK RATES</div>
  {rates_html or '<p style="color:#666">rates unavailable</p>'}

  <div style="font-size:13px;font-weight:700;color:#33e29a;margin:14px 0 6px">HEADLINES</div>
  {news_html or '<p style="color:#666">news unavailable</p>'}

  <div style="border-top:1px solid #333;margin-top:20px;padding-top:10px;color:#666;font-size:11px">
    Generated by the AFRI Terminal (localhost:8081). Research only - not investment advice.<br>
    Live: JSE + EGX via Yahoo · EOD: NGX + NSE via African Financials.
  </div>
</div>"""

    return html

def send(to_addr):
    html = build_brief()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Morning Brief · {datetime.now().strftime('%a %d %b')} · African Markets"
    msg["From"] = FROM
    msg["To"] = to_addr
    msg.attach(MIMEText("Morning brief - open in HTML-enabled mail client.", "plain"))
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=30) as s:
        s.starttls(context=ctx)
        s.login(MAIL_USER, MAIL_PASS)
        s.sendmail(FROM, [to_addr], msg.as_string())
    print(f"Morning brief sent to {to_addr} ({len(html)} chars)")

if __name__ == "__main__":
    to = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--to" else "jimmy@mutxri.com"
    send(to)
