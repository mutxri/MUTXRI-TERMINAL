#!/usr/bin/env python3
"""build_tiktok.py - a ~30 s vertical TikTok of what MX Terminal does.

Picture: the real 4K scene recordings record_tour.py made of the live site,
cropped to a 9:16 window that pans across the part of the screen each line is
about. The window is 864x1536 device pixels scaled to 1080x1920, so there is
no upscale blur beyond 1.25x.

Voice: a female neural voice (en-US-AvaNeural) reading a TikTok script, one
line per beat. Each line is trimmed to its spoken words using the word
boundaries the voice service returns, and those same boundaries drive the
word-by-word captions, so the captions land on the words.

Note: this sends the script lines to Microsoft's TTS endpoint.

usage: python build_tiktok.py
"""
import asyncio
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import edge_tts

from build_tour import AUDIO_CHAIN

HERE = Path(__file__).resolve().parent
CLIPS = Path(r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
             r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour4k")
WORK = Path(os.environ.get("TT_WORK", HERE / "_tiktok_work"))
OUT = HERE / "media" / "social" / "mx_tiktok.mp4"

VOICE = "en-US-AvaNeural"
RATE = "+6%"
SR = 48000
W, H = 1080, 1920
CW, CH = 864, 1536                 # crop window in 4K device pixels
FPS = 30
HEAD, TAIL = 0.06, 0.22            # kept around each line's words
GREEN = "&H009AE233"               # #33e29a as ASS BGR

# clip id, line, pan start x -> end x (logical 1920x1080 px, left edge of window),
# logical y of the window's top edge
BEATS = [
    ("02_board", "Trying to follow African stocks? Stop juggling four websites.",
     100, 700, 0),
    ("03_tape", "MX Terminal puts Johannesburg, Lagos, Nairobi and Cairo on one screen.",
     0, 1480, 0),
    ("04_watchlist", "Nearly a thousand listed companies, each with its own company sheet.",
     0, 160, 0),
    # typing runs 3.8-5.3 s into the clip, Enter at 6.15: sit on the command
    # box while it is typed, then glide onto the financials panel it opens
    ("06_command", "Type MTN, FIN, and MTN's financials open.",
     1100, 240, 0, {"from": 3.6, "hold": 2.7, "pan_end": 4.0, "extra": 0.8}),
    ("07_heatmap", "See the whole market move on one heatmap.",
     300, 880, 0),
    ("10_screener", "Screen every stock by sector and move.",
     240, 720, 0),
    ("09_news", "Catch every dividend and book closure.",
     470, 640, 0),
    ("11_trade", "And practise with paper trading before you risk real money.",
     240, 760, 0),
    # window sits low on the card so the logo clears the caption line
    ("14_outro", "MX Terminal. Every African market, one terminal. Link in bio.",
     744, 744, 300),
]
HOOK = ("4 African exchanges.", "1 terminal.")


def run(cmd, cwd=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        print(" ".join(str(c) for c in cmd[:12]), "...")
        print(r.stderr[-1500:])
        raise SystemExit(1)
    return r


def duration(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", p]).stdout)


async def speak(text, mp3):
    """Save the line as mp3; return [(word, start_s, end_s)]."""
    words = []
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    with open(mp3, "wb") as fh:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                fh.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                a = ch["offset"] / 1e7
                words.append((ch["text"], a, a + ch["duration"] / 1e7))
    return words


def marks(line, words):
    """Flag the words followed by punctuation in the script line."""
    out, pos = [], 0
    for w, a, b in words:
        i = line.find(w, pos)
        if i < 0:
            out.append((w, a, b, False))
            continue
        pos = i + len(w)
        out.append((w, a, b, line[pos:pos + 1] in (".", ",", "?", "!")))
    if out:                                            # never run into the next beat
        out[-1] = out[-1][:3] + (True,)
    return out


def ass_time(t):
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%05.2f" % (h, m, s)


def caption_events(all_words, total):
    """Chunks of up to three words; the word being spoken is green."""
    # the voice service's word boundaries carry no punctuation, so each word
    # comes with a break flag worked out from the script line (see marks())
    chunks, cur = [], []
    for w in all_words:
        cur.append(w)
        if len(cur) == 3 or w[3]:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    ev = []
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0][1] if ci + 1 < len(chunks) else total
        for wi, (_, a, b, _) in enumerate(ch):
            end = ch[wi + 1][1] if wi + 1 < len(ch) else min(max(b + 0.3, a + 0.4), nxt)
            txt = " ".join(("{\\c%s}%s{\\c&H00FFFFFF&}" % (GREEN, t.upper()))
                           if j == wi else t.upper() for j, (t, _, _, _) in enumerate(ch))
            ev.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s"
                      % (ass_time(a), ass_time(end), txt))
    return ev


def build_ass(all_words, total, hook_end):
    head = [
        "[Script Info]", "ScriptType: v4.00+",
        "PlayResX: %d" % W, "PlayResY: %d" % H, "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        "Style: Cap,Segoe UI Black,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,7,3,5,80,80,0,1",
        "Style: Hook,Segoe UI Black,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,3,26,0,8,60,60,300,1",
        "Style: Url,Segoe UI,44,%s,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,"
        "100,100,1,0,3,12,0,2,60,60,330,1" % GREEN,
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        "Dialogue: 1,0:00:00.00,%s,Hook,,0,0,0,,{\\fad(0,200)}%s\\N{\\c%s}%s"
        % (ass_time(hook_end), HOOK[0], GREEN, HOOK[1]),
        "Dialogue: 1,0:00:00.00,%s,Url,,0,0,0,,mutxriterminal.com" % ass_time(total),
    ]
    body = [e.replace(",,0,0,0,,", ",,0,0,0,,{\\pos(540,1180)}", 1)
            for e in caption_events(all_words, total)]
    return "\n".join(head + body) + "\n"


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    segs, auds, all_words, t = [], [], [], 0.0

    for i, (cid, line, x0, x1, y, *opt) in enumerate(BEATS):
        opt = opt[0] if opt else {}
        mp3 = WORK / ("line_%02d.mp3" % i)
        words = marks(line, asyncio.run(speak(line, str(mp3))))
        a0 = max(words[0][1] - HEAD, 0.0)
        a1 = words[-1][2] + TAIL + opt.get("extra", 0.0)
        if i == len(BEATS) - 1:
            a1 += 0.8                                 # let the logo breathe
        wav = WORK / ("aud_%02d.wav" % i)
        run(["ffmpeg", "-y", "-v", "error", "-i", mp3, "-ss", "%.3f" % a0,
             "-af", "apad", "-t", "%.3f" % (a1 - a0),
             "-ar", SR, "-ac", 2, "-c:a", "pcm_s16le", wav])
        seg_len = duration(wav)

        clip = CLIPS / (cid + ".mp4")
        clen = duration(clip)
        # the clip's payoff is at its end, unless the beat says where to start
        start = opt.get("from", max(clen - seg_len - 0.3, 0.0))
        X0, X1, Y = x0 * 2, x1 * 2, y * 2
        hold = opt.get("hold", 0.0)
        pan_end = opt.get("pan_end", seg_len)
        p = "clip((t-%.3f)/%.3f,0,1)" % (hold, max(pan_end - hold, 0.01))
        vf = ("tpad=stop_mode=clone:stop_duration=10,"
              "crop=%d:%d:x='%d+(%d)*%s*%s*(3-2*%s)':y=%d,"
              "scale=%d:%d:flags=lanczos,setsar=1,fps=%d,format=yuv420p"
              % (CW, CH, X0, X1 - X0, p, p, p, Y, W, H, FPS))
        seg = WORK / ("seg_%02d.mp4" % i)
        run(["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % start, "-i", clip,
             "-vf", vf, "-an", "-t", "%.3f" % seg_len,
             "-c:v", "libx264", "-preset", "medium", "-crf", 18, seg])
        seg_len = duration(seg)
        run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-af", "apad",
             "-t", "%.6f" % seg_len, "-c:a", "pcm_s16le", "-ar", SR, "-ac", 2,
             str(wav) + ".pad.wav"])
        os.replace(str(wav) + ".pad.wav", wav)

        all_words += [(w, a - a0 + t, b - a0 + t, brk) for w, a, b, brk in words]
        segs.append(seg)
        auds.append(wav)
        print("  %-13s %4.1fs  %s" % (cid, seg_len, line))
        t += seg_len

    total = t
    (WORK / "pic.txt").write_text("".join("file '%s'\n" % p.as_posix() for p in segs))
    (WORK / "aud.txt").write_text("".join("file '%s'\n" % p.as_posix() for p in auds))
    (WORK / "cap.ass").write_text(build_ass(all_words, total, BEATS and
                                            all_words[0][1] + 2.4), encoding="utf-8")
    (WORK / "words.json").write_text(json.dumps(all_words, indent=1))

    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", 0, "-i", "pic.txt",
         "-c", "copy", "pic.mp4"], cwd=WORK)
    run(["ffmpeg", "-y", "-v", "error", "-i", "pic.mp4",
         "-f", "concat", "-safe", 0, "-i", "aud.txt",
         "-map", "0:v", "-map", "1:a",
         "-vf", "ass=cap.ass", "-af", AUDIO_CHAIN,
         "-c:v", "libx264", "-preset", "slow", "-crf", 19, "-profile:v", "high",
         "-pix_fmt", "yuv420p", "-r", FPS,
         "-c:a", "aac", "-b:a", "160k", "-ar", SR, "-ac", 2,
         "-shortest", "-movflags", "+faststart", OUT], cwd=WORK)
    print("\n  %s  %.1fs  %.1f MB" % (OUT, duration(OUT), OUT.stat().st_size / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
