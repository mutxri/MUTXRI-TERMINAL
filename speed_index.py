#!/usr/bin/env python3
"""speed_index.py - everything that can be done from here to get the site indexed faster.

Google has no public "index this now" API for ordinary pages: its Indexing API is
limited to job postings and livestream pages, and the sitemap ping endpoint was
retired in 2023. What moves Google is Search Console (verify the domain, submit the
sitemap, request indexing - it needs the owner's Google sign-in), accurate sitemap
dates, and one clean, consistent address for every page.

This script does the rest:

  audit    (default) fetch the live site as Googlebot and check every signal that
           decides whether the homepage can be indexed, then print what is left
           for the owner to do, with direct Search Console links.
  sitemap  rewrite sitemap.xml with <lastmod> set to the date the page's source
           last changed - an honest date, the only kind Google uses.
  submit   notify IndexNow (Bing, Yandex, Seznam, Naver; Bing also feeds Yahoo and
           DuckDuckGo) about every URL in the sitemap. Google does not take
           IndexNow. The key file must be deployed first (assemble_deploy.py
           copies it to the site root).

The IndexNow key is not a secret: the protocol requires it to be served publicly
at https://mutxriterminal.com/<key>.txt.

usage: python speed_index.py [audit|sitemap|submit]
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = "https://mutxriterminal.com"
HOST = "mutxriterminal.com"
KEYFILE = os.path.join(HERE, "indexnow_key.txt")
SITEMAP = os.path.join(HERE, "sitemap.xml")
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
# pages meant to appear in search results, and the source file each is built from.
# The guide was made indexable on 2026-09-14 (no noindex, own canonical); leaving
# it out here would drop it from the sitemap on the next run.
PAGES = [("/", "landing/index.html"), ("/guide.html", "guide.html")]


def key(create=True):
    if os.path.exists(KEYFILE):
        k = open(KEYFILE, encoding="utf-8").read().strip()
        if re.fullmatch(r"[a-f0-9]{32}", k):
            return k
    if not create:
        return None
    k = secrets.token_hex(16)
    with open(KEYFILE, "w", encoding="utf-8") as f:
        f.write(k)
    return k


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(url, follow=True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": GOOGLEBOT})
    try:
        r = opener.open(req, timeout=30)
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, ""
    except Exception as e:
        return None, {}, str(e)


def audit():
    rows = []

    def add(ok, name, detail=""):
        rows.append((ok, name, detail))

    st, hd, body = fetch(SITE + "/")
    add(st == 200, "homepage loads for Googlebot", "HTTP %s" % st)
    rm = re.search(r'<meta[^>]+name=["\']robots["\'][^>]*content=["\']([^"\']+)', body, re.I)
    add(not (rm and "noindex" in rm.group(1).lower()), "homepage has no noindex tag", rm.group(1) if rm else "no robots meta")
    xr = hd.get("x-robots-tag", "")
    add("noindex" not in xr.lower(), "no noindex header", xr or "none")
    can = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', body, re.I)
    add(bool(can) and can.group(1).rstrip("/") == SITE, "canonical is %s/" % SITE, can.group(1) if can else "missing")
    add(bool(re.search(r"<title>[^<]{10,}</title>", body)), "title present")
    add(bool(re.search(r'<meta[^>]+name=["\']description["\']', body, re.I)), "meta description present")
    ld = False
    for b in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', body, re.S | re.I):
        try:
            json.loads(b)
            ld = True
        except ValueError:
            pass
    add(ld, "structured data (JSON-LD) parses")

    st, _, rb = fetch(SITE + "/robots.txt")
    blocked = bool(re.search(r"^\s*Disallow:\s*/\s*$", rb, re.M))
    add(st == 200 and not blocked, "robots.txt allows crawling", "HTTP %s%s" % (st, ", 'Disallow: /' found" if blocked else ""))
    add("sitemap:" in rb.lower(), "robots.txt points to the sitemap")
    st, _, sb = fetch(SITE + "/sitemap.xml")
    locs = re.findall(r"<loc>(.*?)</loc>", sb)
    add(st == 200 and SITE + "/" in locs, "sitemap lists the homepage", "%d URL(s)" % len(locs))
    add(bool(re.search(r"<lastmod>\d{4}-\d{2}-\d{2}", sb)), "sitemap carries lastmod dates")

    # one address per page: every other spelling should 301 to https://mutxriterminal.com/
    redirect_fail = False
    for u in ("http://mutxriterminal.com/", "http://www.mutxriterminal.com/", "https://www.mutxriterminal.com/"):
        st, hd, _ = fetch(u, follow=False)
        loc = hd.get("location", "")
        ok = st in (301, 308) and loc.startswith(SITE + "/")
        redirect_fail = redirect_fail or not ok
        add(ok, "%s redirects to %s/" % (u, SITE), "HTTP %s -> %s" % (st, loc or "no redirect"))

    k = key(create=False)
    if k:
        st, _, kb = fetch("%s/%s.txt" % (SITE, k))
        add(st == 200 and kb.strip() == k, "IndexNow key file is live", "HTTP %s" % st)
    else:
        add(False, "IndexNow key file is live", "no key yet - run: python speed_index.py submit")

    width = max(len(r[1]) for r in rows)
    print("\nLIVE INDEXING AUDIT  %s  (as Googlebot)\n" % time.strftime("%Y-%m-%d %H:%M"))
    for ok, name, detail in rows:
        print("  %s  %-*s  %s" % ("PASS" if ok else "FAIL", width, name, detail))
    fails = sum(1 for r in rows if not r[0])
    print("\n  %d of %d checks pass\n" % (len(rows) - fails, len(rows)))

    rid = urllib.parse.quote("sc-domain:" + HOST, safe="")
    print("LEFT FOR THE SITE OWNER (needs your own sign-in)\n")
    step = 1
    if redirect_fail:
        print("  %d. Cloudflare > SSL/TLS > Edge Certificates > Always Use HTTPS: On." % step)
        print("     Until then Google sees http:// and https:// as two copies of the site.")
        step += 1
    print("  %d. Verify the domain in Google Search Console (Domain property, DNS TXT record -" % step)
    print("     Cloudflare can add it automatically):  https://search.google.com/search-console/welcome")
    step += 1
    print("  %d. Submit the sitemap:  https://search.google.com/search-console/sitemaps?resource_id=%s" % (step, rid))
    step += 1
    print("  %d. Request indexing of the homepage:" % step)
    print("     https://search.google.com/search-console/inspect?resource_id=%s&id=%s" % (rid, urllib.parse.quote(SITE + "/", safe="")))
    step += 1
    print("  %d. Optional: Bing Webmaster Tools can import the Search Console property in one click:" % step)
    print("     https://www.bing.com/webmasters\n")
    return 0 if fails == 0 else 1


def last_changed(src):
    path = os.path.join(HERE, src)
    try:
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", src], cwd=HERE).returncode != 0
        if not dirty:
            out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", src], cwd=HERE,
                                 capture_output=True, text=True).stdout.strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", out):
                return out
    except Exception:
        pass
    return time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(path)))


def sitemap():
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, src in PAGES:
        lines += ["  <url>", "    <loc>%s%s</loc>" % (SITE, url),
                  "    <lastmod>%s</lastmod>" % last_changed(src), "  </url>"]
    lines.append("</urlset>")
    new = "\n".join(lines) + "\n"
    old = open(SITEMAP, encoding="utf-8").read() if os.path.exists(SITEMAP) else ""
    if new.replace("\r\n", "\n") == old.replace("\r\n", "\n"):
        print("sitemap.xml already current")
    else:
        with open(SITEMAP, "w", encoding="utf-8", newline="\n") as f:
            f.write(new)
        print("sitemap.xml updated:", ", ".join("%s%s (%s)" % (SITE, u, last_changed(s)) for u, s in PAGES))
    return 0


def submit():
    k = key()
    st, _, kb = fetch("%s/%s.txt" % (SITE, k))
    if st != 200 or kb.strip() != k:
        print("The key file is not live yet at %s/%s.txt (HTTP %s)." % (SITE, k, st))
        print("Run assemble_deploy.py and bulk_push.py, then submit again.")
        return 1
    urls = re.findall(r"<loc>(.*?)</loc>", open(SITEMAP, encoding="utf-8").read())
    payload = json.dumps({"host": HOST, "key": k, "keyLocation": "%s/%s.txt" % (SITE, k), "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=payload, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": "speed_index.py (+%s)" % SITE})
    try:
        code = urllib.request.urlopen(req, timeout=30).status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        print("IndexNow unreachable:", e)
        return 1
    meaning = {200: "accepted", 202: "accepted, key check pending", 400: "bad request",
               403: "key not valid for this host", 422: "URLs do not match the host or key",
               429: "too many submissions - try later"}
    print("IndexNow: HTTP %s (%s) for %d URL(s): %s" % (code, meaning.get(code, "unexpected"), len(urls), ", ".join(urls)))
    print("This reaches Bing, Yandex, Seznam and Naver. Google does not use IndexNow.")
    return 0 if code in (200, 202) else 1


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "audit").lower()
    fn = {"audit": audit, "sitemap": sitemap, "submit": submit}.get(cmd)
    if not fn:
        print(__doc__)
        sys.exit(2)
    sys.exit(fn())
