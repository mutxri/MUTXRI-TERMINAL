#!/usr/bin/env python3
"""build_tour.py - assemble the MX Terminal guide tour from stills + narration.

The old tour was recorded on 8 September and showed an eleven-tab strip that
included REG and CORP; both tabs were removed the next day, so a new viewer was
watching a UI they could not find. This rebuilds the tour from live captures of
the current product, narrated with the name people actually say - "MX Terminal".

Inputs, all produced beforehand into the scratch directory:
  <id>.wav   narration for the scene (Windows SAPI)
  <id>.png   a 1600x900 capture of the real, live page

Each still is held exactly as long as its own narration plus a short beat, so
the picture never changes mid-sentence.
"""
import io
import json
import os
import subprocess
import sys

SP = (r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
      r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour")
GAP = 0.45          # beat after each line, so scenes do not run together
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "media", "mutxri_tour_1080p.mp4")
POSTER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "media", "mutxri_tour_poster.jpg")


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return float(out)


def fwd(p):
    """ffmpeg concat lists want forward slashes even on Windows."""
    return p.replace("\\", "/")


def main():
    scenes = json.load(io.open("tour_script.json", encoding="utf-8"))["scenes"]

    frames, audio, total = [], [], 0.0
    for s in scenes:
        wav = os.path.join(SP, s["id"] + ".wav")
        png = os.path.join(SP, s["id"] + ".png")
        for f in (wav, png):
            if not os.path.exists(f):
                print("missing input: %s" % f)
                return 1
        d = duration(wav) + GAP
        total += d
        frames.append("file '%s'" % fwd(png))
        frames.append("duration %.3f" % d)
        audio.append("file '%s'" % fwd(wav))
    # the concat demuxer drops the last image without a repeat of the filename
    frames.append("file '%s'" % fwd(os.path.join(SP, scenes[-1]["id"] + ".png")))

    fl = os.path.join(SP, "frames.txt")
    al = os.path.join(SP, "audio.txt")
    io.open(fl, "w", encoding="utf-8").write("\n".join(frames) + "\n")
    io.open(al, "w", encoding="utf-8").write("\n".join(audio) + "\n")

    silence = os.path.join(SP, "gap.wav")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
                    "-t", "%.3f" % GAP, silence], check=True)

    # narration track: each line followed by its beat, so audio and stills stay
    # locked together for the whole run
    seq = []
    for s in scenes:
        seq.append("file '%s'" % fwd(os.path.join(SP, s["id"] + ".wav")))
        seq.append("file '%s'" % fwd(silence))
    io.open(al, "w", encoding="utf-8").write("\n".join(seq) + "\n")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", fl,
        "-f", "concat", "-safe", "0", "-i", al,
        "-vf", ("scale=1920:1080:flags=lanczos,format=yuv420p,"
                "fade=t=in:st=0:d=0.6,fade=t=out:st=%.2f:d=0.8" % (total - 0.8)),
        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
        "-r", "25", "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", "-shortest", OUT,
    ]
    print("  encoding %d scenes, %.0fs ..." % (len(scenes), total))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return 1

    # poster: the opening board, which is what the guide page shows at rest
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", os.path.join(SP, scenes[0]["id"] + ".png"),
                    "-vf", "scale=1920:1080:flags=lanczos", "-q:v", "3",
                    POSTER], check=True)

    print("  wrote %s (%.1f MB)" % (OUT, os.path.getsize(OUT) / 1e6))
    print("  wrote %s (%.0f KB)" % (POSTER, os.path.getsize(POSTER) / 1e3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
