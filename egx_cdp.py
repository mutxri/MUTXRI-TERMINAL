#!/usr/bin/env python3
"""egx_cdp.py - drive the user's real Chrome (CDP 9222) for EGX scraping.
Stable alternative to the browser-use harness: no IPC races, explicit
wait-for-navigation after each postback click.

Usage:
  python egx_cdp.py search "<company fragment>" <from_dd/mm/yyyy> <to_dd/mm/yyyy>
      -> prints grid rows (NewsID | title)
  python egx_cdp.py detail <NewsID>
      -> prints the disclosure fields (Net Profit, audit status, ...)
"""
import sys, json, time, urllib.request, re
import websocket

CDP = "http://127.0.0.1:9222"

def get_json(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read().decode())

def find_page():
    pages = [t for t in get_json(CDP + "/json/list") if t.get("type") == "page"]
    if not pages:
        return None
    # prefer the newest EGX tab (the harness holds an older one's debugger)
    egx = [t for t in pages if "egx.com.eg" in t.get("url", "")]
    return (egx or pages)[-1]

class Tab:
    def __init__(self, info):
        self.ws = websocket.create_connection(info["webSocketDebuggerUrl"], timeout=30)
        self._id = 0
    def cmd(self, method, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self._id:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})
    def js(self, expr, await_promise=False):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=await_promise)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("text", "js error"))
        return r.get("result", {}).get("value")
    def goto(self, url, wait=6):
        self.cmd("Page.enable")
        self.cmd("Page.navigate", url=url)
        time.sleep(wait)
        for _ in range(30):
            try:
                if self.js("document.readyState") == "complete":
                    return
            except Exception:
                pass
            time.sleep(0.5)

def set_and_search(tab, company, frm, to):
    tab.js("""(() => {
      const set = (id, v) => { const el = document.getElementById(id); if (el) { el.value = v; el.dispatchEvent(new Event('change', {bubbles:true})); } };
      set('ctl00_C_N_DropDownList2', '6');
      set('ctl00_C_N_txtcompany', %s);
      set('ctl00_C_N_txtFrom', %s);
      set('ctl00_C_N_txtTo', %s);
      return true;
    })()""" % (json.dumps(company), json.dumps(frm), json.dumps(to)))
    time.sleep(0.5)
    # click triggers navigation; evaluate returns before teardown
    tab.js("(() => { const b = document.getElementById('ctl00_C_N_Button1'); if (b) b.click(); return !!b; })()")
    time.sleep(7)  # postback round-trip
    for _ in range(30):
        try:
            if tab.js("document.readyState") == "complete":
                break
        except Exception:
            pass
        time.sleep(0.5)
    rows = tab.js("""(() => {
      const g = document.getElementById('ctl00_C_N_GVNews');
      if (!g) return [];
      const out = [], seen = {};
      g.querySelectorAll('tr').forEach(tr => {
        const a = tr.querySelector('a');
        const t = (tr.innerText || '').trim();
        if (t.length > 8 && a && !seen[a.href]) { seen[a.href] = 1; out.push({id: a.href.split('NewsID=')[1] || '', t: t.slice(0, 150)}); }
      });
      return out.slice(0, 15);
    })()""")
    return rows

def detail(tab, nid):
    tab.goto(f"https://www.egx.com.eg/en/NewsDetails.aspx?NewsID={nid}", wait=5)
    txt = tab.js("document.body ? document.body.innerText : ''") or ""
    # extract the disclosure block
    i = txt.find("NEWS DETAILS")
    block = txt[i:i + 1400] if i >= 0 else txt[:1400]
    return re.sub(r"\n{2,}", "\n", block).strip()

if __name__ == "__main__":
    info = find_page()
    if not info:
        print("no chrome page on 9222"); sys.exit(1)
    tab = Tab(info)
    cmd = sys.argv[1]
    if cmd == "search":
        tab.goto("https://www.egx.com.eg/en/NewsSearch.aspx?sec_id=20")
        rows = set_and_search(tab, sys.argv[2], sys.argv[3], sys.argv[4])
        for r in rows:
            print(r["id"], "|", r["t"][:120])
    elif cmd == "detail":
        print(detail(tab, sys.argv[2]))
