#!/usr/bin/env python3
"""build_social.py - cut the approved tour into vertical social videos.

Everything is assembled from the pieces the approved 1:33 tour was built from:
the per-scene 4K picture segments and the per-scene narration chunks, each
already padded to its segment's real length. Sync is inherited, not re-derived,
so none of the audio problems the tour went through can come back this way.

Output is 1080x1920 - TikTok, Reels, Shorts, and LinkedIn/X on a phone:
  top     MX TERMINAL and a two-line hook, readable muted in the first second
  middle  the terminal, full 16:9 frame, nothing cropped out
  below   burned-in captions, phrase by phrase, timed to the words as spoken
  bottom  mutxriterminal.com
Feeds autoplay muted, so the captions carry the message on their own. Their
timings come from words.json: word boundaries from the voice service, mapped
through the same trim the narration went through. That mapping reproduced the
approved cut's audio length to the sample.

usage: python build_social.py [cut ...]        (default: every cut)
"""
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from build_tour import AUDIO_CHAIN          # the approved cut's chain, unchanged

HERE = Path(__file__).resolve().parent
SP = Path(r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
          r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad")
SEG = SP / "tour4k" / "segments"
WORDS = SP / "social" / "words.json"
WORK = SP / "social" / "work"
OUT = HERE / "media" / "social"

W, H = 1080, 1920
VID_Y = 600                      # the terminal sits here, 1080x608
GREEN = "&H009AE233"             # #33e29a as ASS BGR

# name -> (scene ids, hook line 1, hook line 2 in green)
CUTS = {
    "mx_tour_vertical": (
        ["00_landing", "01_signin", "02_board", "03_tape", "04_watchlist",
         "05_rail", "06_command", "07_heatmap", "08_financials", "09_news",
         "10_screener", "11_guide", "12_outro"],
        "Every African market.", "One terminal."),
    "mx_short_command": (
        ["06_command", "12_outro"],
        "Type MTN FIN.", "Get MTN's financials."),
    "mx_short_board": (
        ["02_board", "03_tape", "04_watchlist", "12_outro"],
        "Four African exchanges.", "One board."),
    "mx_short_news": (
        ["09_news", "12_outro"],
        "Every dividend and book closure.", "One wire."),
}


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        print(" ".join(str(c) for c in cmd[:10]), "...")
        print(r.stderr[-1500:])
        raise SystemExit(1)
    return r


def duration(p):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout)


def ass_time(t):
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%05.2f" % (h, m, s)


def phrases(sid, say, words, offset):
    """Group a scene's words into caption phrases on the cut's timeline.

    Display text comes from the script, so punctuation and casing are right;
    timing comes from the spoken words. A phrase closes at punctuation or after
    four words, whichever is first.
    """
    tokens = say.split()
    out, cur = [], []
    for i, (_, a, b) in enumerate(words):
        tok = tokens[i] if i < len(tokens) else words[i][0]
        cur.append((tok, a, b))
        if len(cur) >= 4 or re.search(r"[.,:;!?]$", tok):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [(" ".join(t for t, _, _ in p).rstrip(",;:"),
             p[0][1] + offset, p[-1][2] + offset) for p in out]


def build_ass(cut, scenes, hook1, hook2, starts, words, script, total):
    lines = []
    for sid, cut_start in zip(scenes, starts):
        w = words[sid]
        local = [(t, a - w["start"], b - w["start"]) for t, a, b in w["words"]]
        lines += phrases(sid, script[sid], local, cut_start)
    # hold each phrase until the next begins, capped, so captions never flash
    events = []
    for i, (txt, a, b) in enumerate(lines):
        nxt = lines[i + 1][1] if i + 1 < len(lines) else total
        end = min(max(b + 0.25, a + 0.6), nxt)
        events.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s"
                      % (ass_time(a), ass_time(end), txt))
    head = [
        "[Script Info]", "ScriptType: v4.00+",
        "PlayResX: %d" % W, "PlayResY: %d" % H, "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        "Style: Brand,Segoe UI,38,%s,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,"
        "100,100,6,0,1,0,0,8,60,60,150,1" % GREEN,
        "Style: Hook,Segoe UI,74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,"
        "100,100,0,0,1,0,0,8,60,60,230,1",
        "Style: Cap,Segoe UI,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,"
        "100,100,0,0,3,14,0,8,70,70,1300,1",
        "Style: Url,Segoe UI,46,%s,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,"
        "100,100,1,0,1,0,0,2,60,60,170,1" % GREEN,
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        "Dialogue: 1,0:00:00.00,%s,Brand,,0,0,0,,MX TERMINAL" % ass_time(total),
        "Dialogue: 1,0:00:00.00,%s,Hook,,0,0,0,,%s\\N{\\c%s}%s"
        % (ass_time(total), hook1, GREEN, hook2),
        "Dialogue: 1,0:00:00.00,%s,Url,,0,0,0,,mutxriterminal.com" % ass_time(total),
    ]
    return "\n".join(head + events) + "\n"


def build(cut):
    scenes, hook1, hook2 = CUTS[cut]
    script = {s["id"]: s["say"] for s in json.load(
        io.open(HERE / "tour_script.json", encoding="utf-8"))["scenes"]}
    ids = list(script)
    words = json.load(io.open(WORDS, encoding="utf-8"))
    work = WORK / cut
    work.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    segs = [SEG / ("seg_%02d.mp4" % ids.index(s)) for s in scenes]
    auds = [SEG / ("aud_%02d.wav" % ids.index(s)) for s in scenes]
    starts, t = [], 0.0
    for p in segs:
        starts.append(t)
        t += duration(p)
    total = t

    (work / "pic.txt").write_text("".join("file '%s'\n" % p.as_posix() for p in segs))
    (work / "aud.txt").write_text("".join("file '%s'\n" % p.as_posix() for p in auds))
    (work / "captions.ass").write_text(
        build_ass(cut, scenes, hook1, hook2, starts, words, script, total),
        encoding="utf-8")

    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", "pic.txt", "-c", "copy", "pic.mp4"],
        cwd=work)
    out = OUT / (cut + ".mp4")
    fc = ("color=c=black:s=%dx%d:r=25[bg];"
          "[0:v]scale=%d:-2:flags=lanczos,setsar=1[v];"
          "[bg][v]overlay=0:%d:shortest=1,ass=captions.ass,format=yuv420p[out]"
          % (W, H, W, VID_Y))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", "pic.mp4", "-f", "concat", "-safe", "0", "-i", "aud.txt",
         "-filter_complex", fc, "-map", "[out]", "-map", "1:a",
         "-af", AUDIO_CHAIN,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-profile:v", "high", "-r", "25",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
         "-shortest", "-movflags", "+faststart", str(out)], cwd=work)
    print("  %-18s %5.1fs  %d scenes  %.1f MB"
          % (cut, duration(out), len(scenes), out.stat().st_size / 1e6))
    return out


def main():
    cuts = sys.argv[1:] or list(CUTS)
    for c in cuts:
        build(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
