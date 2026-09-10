#!/usr/bin/env python3
"""news_collect_ngx_nse.py - build static_data/ngx_news.json + nse_news.json.

NGX: doclib.ngxgroup.com SharePoint REST list 'Financial_NewsDocs' (29.5k
     disclosures; Created desc = newest). Title derived from the filename
     slug when the item Title is empty. Schema mirrors the shipped file:
     [{title, publisher:"NGX Disclosure", date:"Sep 4", url:absolute pdf}]
NSE: live.mystocks.co.ke homepage "#otherNewsDiv .newsHead" block
     (Kenya market headlines; ids 6.18M+ in Sep 2026). The old file's
     builder stopped running in Aug; mystocks prices (/m/pricelist) were
     always separate. Date tokens ("Yesterday", "Thu, 6:03 pm") resolve to
     short "Sep 4" dates. Schema: [{id, title, publisher, date, url}].

Both are wired into refresh_all.py (step after jse news) so the scheduled
refresh keeps NGX/NSE news current like JSE news.
"""
import urllib.request, json, os, re, html as html_mod, datetime, sys

BASE = os.path.dirname(os.path.abspath(__file__))
SD = os.path.join(BASE, "static_data")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Accept": "application/json;odata=verbose"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
MAX_NGX = 300


def _get(url, headers=None):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def _short(d):
    return d.strftime("%b %d").replace(" 0", " ").replace("  ", " ") if d else ""


def clean_title(fn):
    """filename slug -> readable headline: '114_NAHCO_PLC_-_Notication_...' ->
    'NAHCO PLC - Notication ...' (strip leading doc-id, keep the rest)."""
    base = os.path.basename(fn)
    base = re.sub(r"\.pdf$", "", base, flags=re.I)
    base = re.sub(r"^\d+_", "", base)          # leading NGX doc id
    t = base.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def collect_ngx():
    url = ("https://doclib.ngxgroup.com/_api/Web/Lists/GetByTitle('Financial_NewsDocs')/items"
           "?$top=%d&$select=FileRef,Title,Created&$orderby=Created%%20desc" % MAX_NGX)
    body = _get(url, {"Accept": "application/json;odata=verbose"})
    data = json.loads(body)
    rows = data.get("value") or data.get("d", {}).get("results", [])
    out = []
    for r_ in rows:
        ref = r_.get("FileRef") or ""
        if "/Financial_NewsDocs/" not in ref:
            continue
        title = (r_.get("Title") or "").strip() or clean_title(ref)
        if not title:
            continue
        try:
            dt = datetime.datetime.fromisoformat((r_.get("Created") or "")[:10]).date()
        except Exception:
            dt = datetime.date.today()
        out.append({"title": title, "publisher": "NGX Disclosure",
                    "date": _short(dt), "url": "https://doclib.ngxgroup.com" + ref})
    return out


def collect_nse():
    body = _get("https://live.mystocks.co.ke/")
    # the Financial News Headlines block
    m = re.search(r'<div id=otherNewsDiv>(.*?)</div>\s*</div>', body, re.S)
    block = m.group(1) if m else body
    rows = re.findall(r"<div class=newsHead><a href='/news=(\d+)'[^>]*>(.*?)</a>\s*"
                      r"<span><i>(.*?)</i>\s*<u>(.*?)</u></span></div>", block, re.S)
    today = datetime.date.today()
    out = []
    WD = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    for nid, title, pub, when in rows:
        title = html_mod.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        w = when.strip()
        d = None
        if w.lower().startswith("today"):
            d = today
        elif w.lower().startswith("yesterday"):
            d = today - datetime.timedelta(days=1)
        else:
            wd = w.split(",")[0].strip()[:3]
            if wd in WD:
                delta = (today.weekday() - WD[wd]) % 7
                d = today - datetime.timedelta(days=delta)
        out.append({"id": int(nid), "title": title, "publisher": html_mod.unescape(pub).strip(),
                    "date": _short(d) if d else w[:16], "url": "https://live.mystocks.co.ke/news=" + nid})
    return out


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else "both"
    os.makedirs(SD, exist_ok=True)
    if only in ("both", "ngx"):
        ngx = collect_ngx()
        with open(os.path.join(SD, "ngx_news.json"), "w", encoding="utf-8") as f:
            json.dump(ngx, f, ensure_ascii=False)
        print("ngx_news.json: %d items, newest %s" % (len(ngx), ngx[0]["date"] if ngx else "-"))
    if only in ("both", "nse"):
        nse = collect_nse()
        with open(os.path.join(SD, "nse_news.json"), "w", encoding="utf-8") as f:
            json.dump(nse, f, ensure_ascii=False)
        print("nse_news.json: %d items, newest %s" % (len(nse), nse[0]["date"] if nse else "-"))
        for it in nse[:3]:
            print("   ", it["date"], "|", it["publisher"], "|", it["title"][:70])


if __name__ == "__main__":
    main()
