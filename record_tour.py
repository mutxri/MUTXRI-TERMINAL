#!/usr/bin/env python3
"""record_tour.py - record each tour scene as real 4K video of the live site.

The previous cuts were stills with a cursor drawn over them, which is why the
tape never moved: there was nothing to move. This drives a real browser and
captures what it paints, so the tape scrolls, the watchlist scrolls, panels
load, and text typed into the command line actually runs.

How the 4K comes about: the page is laid out at 1920x1080 CSS pixels with a
device scale factor of 2, and CDP's screencast hands back frames at device
resolution - 3840x2160 of genuine pixels, not an upscale.

Screencast frames only arrive when the page paints, so they are timestamped and
irregular. Each scene is resolved to a constant 25 fps clip afterwards, holding
the last painted frame through any still moment.

The pointer is a DOM element injected into the page (the OS cursor is not part
of what a browser paints), moved with the same easing as the real mouse, so what
you see and what the page receives stay in step.

usage: python record_tour.py [scene_id ...]      (default: every scene)
"""
import base64
import io
import json
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SP = (r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
      r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour4k")
FRAMES = os.path.join(SP, "frames")
VW, VH = 1920, 1080
FPS = 25
TAIL = 0.35                      # the beat after the line, kept rolling on video

CURSOR_JS = r"""
(() => {
  if (window.__mxCur) return;
  const d = document.createElement('div');
  d.id = '__mxcur';
  d.style.cssText = 'position:fixed;left:0;top:0;width:26px;height:38px;' +
    'z-index:2147483647;pointer-events:none;transform:translate(-2px,-2px);' +
    'filter:drop-shadow(0 2px 5px rgba(0,0,0,.65))';
  d.innerHTML = '<svg width="26" height="38" viewBox="0 0 26 38">' +
    '<path d="M2 2 L2 27 L8.5 21 L12.5 30.5 L17 28.5 L13 19.5 L21.5 19 Z" ' +
    'fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.documentElement.appendChild(d);
  let x = window.innerWidth / 2, y = window.innerHeight / 2;
  const put = () => { d.style.left = x + 'px'; d.style.top = y + 'px'; };
  put();
  window.__mxCur = (nx, ny, ms) => {
    const sx = x, sy = y, t0 = performance.now();
    ms = ms || 700;
    const step = (t) => {
      let p = Math.min((t - t0) / ms, 1);
      p = p * p * (3 - 2 * p);                       // smoothstep
      x = sx + (nx - sx) * p; y = sy + (ny - sy) * p; put();
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  window.__mxClick = () => {
    const r = document.createElement('div');
    r.style.cssText = 'position:fixed;left:' + x + 'px;top:' + y + 'px;width:8px;' +
      'height:8px;margin:-4px 0 0 -4px;border-radius:50%;border:2px solid #33e29a;' +
      'z-index:2147483646;pointer-events:none;transition:all .45s ease-out';
    document.documentElement.appendChild(r);
    requestAnimationFrame(() => {
      r.style.width = '46px'; r.style.height = '46px';
      r.style.margin = '-23px 0 0 -23px'; r.style.opacity = '0';
    });
    setTimeout(() => r.remove(), 500);
  };
})();
"""


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(str(c) for c in cmd[:10]), "...")
        print(r.stderr[-1500:])
        raise SystemExit(1)
    return r


def wav_len(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


class Recorder(object):
    """Collects screencast frames with the timestamp the browser painted them."""

    def __init__(self, cdp):
        self.cdp = cdp
        self.frames = []
        cdp.on("Page.screencastFrame", self._on_frame)

    def _on_frame(self, ev):
        self.frames.append((ev["metadata"].get("timestamp") or time.time(),
                            base64.b64decode(ev["data"])))
        try:
            self.cdp.send("Page.screencastFrameAck",
                          {"sessionId": ev["sessionId"]})
        except Exception:
            pass

    def start(self):
        self.frames = []
        self.cdp.send("Page.startScreencast",
                      {"format": "jpeg", "quality": 92,
                       "maxWidth": VW * 2, "maxHeight": VH * 2,
                       "everyNthFrame": 1})

    def stop(self):
        try:
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        return self.frames


def centre(page, sel):
    """Element centre in CSS pixels, or None when the selector misses."""
    try:
        box = page.locator(sel).first.bounding_box(timeout=2500)
    except Exception:
        return None
    if not box:
        return None
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def run_steps(page, steps, rec_len):
    """Play the scene's timeline against the real page while it records."""
    t_start = time.time()

    def wait_until(t):
        d = t_start + t - time.time()
        if d > 0:
            page.wait_for_timeout(d * 1000)

    for st in sorted(steps, key=lambda s: s.get("t", 0)):
        wait_until(st.get("t", 0))
        try:
            if "move" in st or "move_sel" in st:
                pt = st.get("move") or centre(page, st["move_sel"])
                if pt:
                    ms = int(st.get("dur", 0.8) * 1000)
                    page.evaluate("([x,y,m])=>window.__mxCur(x,y,m)",
                                  [pt[0], pt[1], ms])
                    page.mouse.move(pt[0], pt[1], steps=12)
            elif "click" in st or "click_sel" in st:
                pt = st.get("click") or centre(page, st["click_sel"])
                if pt:
                    page.evaluate("([x,y,m])=>window.__mxCur(x,y,m)",
                                  [pt[0], pt[1], 450])
                    page.wait_for_timeout(480)
                    page.evaluate("()=>window.__mxClick()")
                    page.mouse.click(pt[0], pt[1])
            elif "js" in st:
                # A native <select> popup is drawn by the OS, not the page, so the
                # screencast never shows it opening. Glide to the control, pulse
                # the click, and set the value in the page instead - what changes
                # on screen is the real result of the choice.
                if st.get("at"):
                    pt = centre(page, st["at"])
                    if pt:
                        page.evaluate("([x,y,m])=>window.__mxCur(x,y,m)", [pt[0], pt[1], 450])
                        page.wait_for_timeout(480)
                        page.evaluate("()=>window.__mxClick()")
                page.evaluate(st["js"])
            elif "type" in st:
                page.keyboard.type(st["type"], delay=st.get("delay", 95))
            elif "key" in st:
                page.keyboard.press(st["key"])
            elif "wheel" in st:
                pt = centre(page, st["wheel"]) or (VW / 2, VH / 2)
                page.mouse.move(pt[0], pt[1])
                page.evaluate("([x,y,m])=>window.__mxCur(x,y,m)",
                              [pt[0], pt[1], 300])
                n = max(int(st.get("dur", 2.0) * 12), 1)
                per = st.get("dy", 400) / float(n)
                for _ in range(n):
                    page.mouse.wheel(0, per)
                    page.wait_for_timeout(1000.0 / 12)
        except Exception as exc:                     # a step must not kill a scene
            print("      step skipped (%s): %s" % (list(st)[0], str(exc)[:70]))

    wait_until(rec_len)


def encode(frames, out, rec_len):
    """Irregular painted frames -> a constant 25 fps clip of exactly rec_len."""
    if not frames:
        return False
    if os.path.isdir(FRAMES):
        for f in os.listdir(FRAMES):
            os.remove(os.path.join(FRAMES, f))
    os.makedirs(FRAMES, exist_ok=True)

    t0 = frames[0][0]
    paths, times = [], []
    for i, (ts, data) in enumerate(frames):
        p = os.path.join(FRAMES, "f%05d.jpg" % i)
        with open(p, "wb") as fh:
            fh.write(data)
        paths.append(p)
        times.append(ts - t0)

    # hold each painted frame until the next one arrives
    lines = []
    for i, p in enumerate(paths):
        end = times[i + 1] if i + 1 < len(paths) else rec_len
        d = max(end - times[i], 1.0 / 60)
        lines.append("file '%s'\nduration %.4f" % (p.replace("\\", "/"), d))
    lines.append("file '%s'" % paths[-1].replace("\\", "/"))
    lst = os.path.join(FRAMES, "list.txt")
    io.open(lst, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", lst,
        "-vf", "scale=%d:%d:flags=lanczos,setsar=1,format=yuv420p" % (VW * 2, VH * 2),
        "-fps_mode", "cfr", "-r", str(FPS), "-t", "%.3f" % rec_len,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", out])
    return True


def main():
    script = json.load(io.open(os.path.join(HERE, "tour_script.json"),
                               encoding="utf-8"))
    only = set(sys.argv[1:])
    scenes = [s for s in script["scenes"] if not only or s["id"] in only]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            "--hide-scrollbars", "--disable-gpu", "--no-sandbox",
            "--autoplay-policy=no-user-gesture-required"])
        ctx = browser.new_context(viewport={"width": VW, "height": VH},
                                  device_scale_factor=2,
                                  reduced_motion="no-preference")
        # the account menu shows the address the sign-in scene typed, not "Not signed in".
        # Only on the tour views: the sign-in page prefills its email box from the same
        # key, and the scene then typed the address a second time on top of it.
        ctx.add_init_script("try{ if(location.search.indexOf('view=') >= 0 && !localStorage.getItem('mt_email'))"
                            " localStorage.setItem('mt_email','you@example.com'); }catch(e){}")
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        rec = Recorder(cdp)

        for sc in scenes:
            wav = os.path.join(SP, sc["id"] + ".wav")
            if not os.path.exists(wav):
                print("  %-14s no narration yet - skipped" % sc["id"])
                continue
            rec_len = wav_len(wav) + TAIL + float(sc.get("hold", 0))
            out = os.path.join(SP, sc["id"] + ".mp4")

            page.goto(sc["url"], wait_until="load", timeout=90000)
            page.wait_for_timeout(float(sc.get("settle", 6)) * 1000)
            page.evaluate(CURSOR_JS)
            start = sc.get("start") or [VW / 2, VH / 2]
            page.evaluate("([x,y])=>window.__mxCur(x,y,1)", start)
            page.mouse.move(start[0], start[1])

            rec.start()
            run_steps(page, sc.get("steps", []), rec_len)
            frames = rec.stop()

            # a scene that changes settings (theme, paper orders) must not leave
            # them behind for the scenes recorded after it
            try:
                page.evaluate("()=>{try{['mx_settings','mx_paper_v1','mt_ws']"
                              ".forEach(k=>localStorage.removeItem(k));}catch(e){}}")
            except Exception:
                pass

            ok = encode(frames, out, rec_len)
            print("  %-14s %5.1fs  %4d painted frames  %s"
                  % (sc["id"], rec_len, len(frames),
                     "%.1f MB" % (os.path.getsize(out) / 1e6) if ok else "FAILED"))

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
