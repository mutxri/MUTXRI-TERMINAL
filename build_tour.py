#!/usr/bin/env python3
"""build_tour.py - assemble the MX Terminal guide tour.

Rebuilt after the first attempt shipped twelve seconds of black at the head and
more at the tail. The cause was the approach, not the inputs: feeding stills to
the concat demuxer with `duration` directives leaves the encoder guessing at
timestamps, and it filled the gaps with nothing. Every still is now rendered as
its OWN encoded segment with an explicit -t, then the finished segments are
joined - a pipeline that has no way to invent an empty frame.

What each pass does:
  * one segment per scene, still + its narration, -t exactly the audio length
  * a cursor glides across the frame toward whatever the line is describing, so
    the viewer is led rather than left to hunt
  * loudnorm on the narration - raw SAPI output is quiet and flat, and the tour
    it replaces sat around -19.8 dB
  * brand cards open and close it: a welcome, and the logo at the end

usage: python build_tour.py
"""
import io
import json
import os
import subprocess
import sys

SP = (r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
      r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "mutxri_tour_1080p.mp4")
POSTER = os.path.join(HERE, "media", "mutxri_tour_poster.jpg")
CURSOR = os.path.join(HERE, "media", "cursor.png")

W, H = 1920, 1080
SRC_W, SRC_H = 1600, 900
K = W / SRC_W                     # capture space -> output space
TAIL = 0.55                       # beat after each line so scenes do not collide


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(" ".join(str(c) for c in cmd[:12]), "...")
        print(r.stderr[-1200:])
        raise SystemExit(1)
    return r


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def cursor_filter(path, seg_len):
    """A cursor that travels from the first point to the second and settles.

    It moves over the middle 55% of the scene: a beat to register where it
    started, the glide, then a still moment on the target while the line
    finishes. Coordinates come from the script in capture space.
    """
    if not path:
        return None
    (x0, y0), (x1, y1) = path[0], path[1]
    x0, y0, x1, y1 = x0 * K, y0 * K, x1 * K, y1 * K
    t0 = seg_len * 0.22
    t1 = seg_len * 0.72
    # eased progress in [0,1]: clip((t-t0)/(t1-t0)) smoothed
    p = "clip((t-%.3f)/%.3f,0,1)" % (t0, max(t1 - t0, 0.01))
    ease = "(%s*%s*(3-2*%s))" % (p, p, p)          # smoothstep
    x = "%.1f+(%.1f)*%s" % (x0, x1 - x0, ease)
    y = "%.1f+(%.1f)*%s" % (y0, y1 - y0, ease)
    return x, y


def main():
    script = json.load(io.open(os.path.join(HERE, "tour_script.json"),
                               encoding="utf-8"))
    scenes = script["scenes"]
    seg_dir = os.path.join(SP, "segments")
    os.makedirs(seg_dir, exist_ok=True)

    seg_files, total = [], 0.0
    for i, sc in enumerate(scenes):
        still = os.path.join(SP, (sc.get("card") or sc["id"]) + ".png")
        wav = os.path.join(SP, sc["id"] + ".wav")
        for f in (still, wav):
            if not os.path.exists(f):
                print("missing input:", f)
                return 1

        seg_len = duration(wav) + TAIL + float(sc.get("hold", 0))
        total += seg_len
        seg = os.path.join(seg_dir, "seg_%02d.mp4" % i)

        base = ("scale=%d:%d:flags=lanczos,setsar=1,format=yuv420p" % (W, H))
        cur = cursor_filter(sc.get("cursor"), seg_len)
        if cur:
            fc = ("[0:v]%s[bg];[2:v]scale=%d:-1[cur];"
                  "[bg][cur]overlay=x='%s':y='%s':eval=frame[v]"
                  % (base, int(30 * K), cur[0], cur[1]))
            inputs = ["-loop", "1", "-i", still, "-i", wav, "-i", CURSOR]
        else:
            fc = "[0:v]%s[v]" % base
            inputs = ["-loop", "1", "-i", still, "-i", wav]

        cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs +
               ["-filter_complex", fc, "-map", "[v]", "-map", "1:a",
                "-t", "%.3f" % seg_len,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", "25",
                "-af", "loudnorm=I=-18:TP=-1.5:LRA=11,apad",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                seg])
        run(cmd)
        seg_files.append(seg)
        print("  %-14s %5.1fs%s" % (sc["id"], seg_len, "  + cursor" if cur else ""))

    lst = os.path.join(seg_dir, "segments.txt")
    io.open(lst, "w", encoding="utf-8").write(
        "\n".join("file '%s'" % s.replace("\\", "/") for s in seg_files) + "\n")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", "25",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
         "-movflags", "+faststart", OUT])

    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", os.path.join(SP, "card_intro.png"),
         "-vf", "scale=%d:%d:flags=lanczos" % (W, H), "-q:v", "3", POSTER])

    print("\n  %s  %.1f MB  %.0fs" % (OUT, os.path.getsize(OUT) / 1e6, total))
    print("  %s  %.0f KB" % (POSTER, os.path.getsize(POSTER) / 1e3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
