#!/usr/bin/env python3
"""build_tour.py - assemble the MX Terminal guide tour.

Rebuilt after the first attempt shipped twelve seconds of black at the head and
more at the tail. The cause was the approach, not the inputs: feeding stills to
the concat demuxer with `duration` directives leaves the encoder guessing at
timestamps, and it filled the gaps with nothing. Every still is now rendered as
its OWN encoded segment with an explicit -t, then the finished segments are
joined - a pipeline that has no way to invent an empty frame.

What each pass does:
  * one PICTURE segment per scene, -t exactly the narration length plus a beat
  * the narration assembled separately as PCM and laid over the finished
    picture in one piece, so no scene boundary ever falls inside the audio
  * loudnorm once over the whole track rather than per scene
  * the logo card closes it

usage: python build_tour.py
"""
import io
import json
import os
import subprocess
import sys

SP = (r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
      r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour4k")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "mx_terminal_tour_4k.mp4")
POSTER = os.path.join(HERE, "media", "mx_terminal_tour_poster.jpg")
VTT = os.path.join(HERE, "media", "mx_terminal_tour.vtt")
CURSOR = os.path.join(HERE, "media", "cursor.png")

W, H = 3840, 2160                 # true 4K: a 1920x1080 layout captured at 2x
SRC_W, SRC_H = 1920, 1080         # script coordinates are in logical CSS space
K = W / SRC_W                     # script space -> output space (2.0)
TAIL = 0.35                       # beat after each line so scenes do not collide


# The narration is now a neural voice, which arrives even and full-bodied, so
# this is a light touch rather than the repair job the SAPI track needed:
#   highpass   - clears anything below the voice
#   compand    - lifts the unstressed words the voice throws away. Aria puts
#                "the" and "from" 5-10 dB under the rest of the line; on a
#                laptop speaker that is heard as a missing word, so quiet
#                syllables come up while the loud ones stay put. Slow release,
#                so it lifts rather than pumps.
#   equalizer  - a small presence lift at 3 kHz for phone speakers
#   loudnorm   - lands on a consistent -18 LUFS with headroom to spare
AUDIO_CHAIN = (
    "highpass=f=80,"
    "compand=attacks=0.008:decays=0.28:"
    "points=-70/-70|-46/-28|-30/-19|-16/-12|0/-7:soft-knee=6:gain=2,"
    "equalizer=f=3000:t=q:w=1.4:g=1.5,"
    "loudnorm=I=-18:TP=-1.5:LRA=9"
)


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


def ts(sec):
    """seconds -> WEBVTT timestamp."""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%06.3f" % (h, m, s)


def frame_map(crop):
    """Return (fn, prefix): script coords -> output coords, and any crop filter.

    A scene may frame part of the page instead of the whole of it - the sign-in
    box is a small card on a mostly empty screen, and shown full width it reads
    as the black frame the first cut was rejected for. The crop is given in the
    same 1920x1080 logical space as everything else in the script.
    """
    if not crop:
        return (lambda x, y: (x * K, y * K)), ""
    cx, cy, cw, ch = crop
    s = float(W) / (cw * K)                      # cropped pixels -> output
    pre = "crop=%d:%d:%d:%d," % (cw * K, ch * K, cx * K, cy * K)
    return (lambda x, y: ((x - cx) * K * s, (y - cy) * K * s)), pre


def cursor_filter(path, seg_len, xf):
    """A cursor that travels from the first point to the second and settles.

    It moves over the middle 55% of the scene: a beat to register where it
    started, the glide, then a still moment on the target while the line
    finishes. Coordinates come from the script in logical space.
    """
    if not path:
        return None
    x0, y0 = xf(*path[0])
    x1, y1 = xf(*path[1])
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

    seg_files, aud_files, total, cues = [], [], 0.0, []
    for i, sc in enumerate(scenes):
        # record_tour.py writes <id>.mp4 - real video of the live page, cursor
        # and all. The still path is the fallback for a scene not yet recorded.
        clip = os.path.join(SP, sc["id"] + ".mp4")
        still = os.path.join(SP, (sc.get("card") or sc["id"]) + ".png")
        wav = os.path.join(SP, sc["id"] + ".wav")
        src = clip if os.path.exists(clip) else still
        for f in (src, wav):
            if not os.path.exists(f):
                print("missing input:", f)
                return 1

        seg_len = duration(wav) + TAIL + float(sc.get("hold", 0))
        seg = os.path.join(seg_dir, "seg_%02d.mp4" % i)

        if src == clip:
            # a recorded clip is already 4K, so the only geometry left is an
            # optional crop - the sign-in card is small on a dark page
            _, pre = frame_map(sc.get("crop"))
            fc = ("[0:v]%sscale=%d:%d:flags=lanczos,setsar=1,format=yuv420p[v]"
                  % (pre, W, H))
            inputs = ["-i", clip, "-i", wav]
        else:
            xf, pre = frame_map(sc.get("crop"))
            base = (pre + "scale=%d:%d:flags=lanczos,setsar=1,format=yuv420p"
                    % (W, H))
            cur = cursor_filter(sc.get("cursor"), seg_len, xf)
            if cur:
                fc = ("[0:v]%s[bg];[2:v]scale=%d:-1[cur];"
                      "[bg][cur]overlay=x='%s':y='%s':eval=frame[v]"
                      % (base, int(30 * K), cur[0], cur[1]))
                inputs = ["-loop", "1", "-i", still, "-i", wav, "-i", CURSOR]
            else:
                fc = "[0:v]%s[v]" % base
                inputs = ["-loop", "1", "-i", still, "-i", wav]

        # video only. The narration is assembled separately and laid over the
        # finished picture in one piece - see the note on the join below.
        cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs +
               ["-filter_complex", fc, "-map", "[v]", "-an",
                "-t", "%.3f" % seg_len,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-r", "25",
                seg])
        run(cmd)
        seg_files.append(seg)

        # The encoder rounds a segment up to a whole frame at 25 fps, so the
        # picture is up to 20 ms longer than the length asked for. Pad the audio
        # to what the segment ACTUALLY runs, not the nominal figure - matching
        # the nominal one left the sound ~19 ms short per scene, and thirteen
        # scenes of that put the voice a quarter of a second ahead of the
        # picture by the outro.
        seg_dur = duration(seg)
        # the cue runs over the narration only, not the beat that follows it
        cues.append((total, total + duration(wav), sc["say"]))
        total += seg_dur

        wseg = os.path.join(seg_dir, "aud_%02d.wav" % i)
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav,
             "-af", "apad", "-t", "%.6f" % seg_dur,
             "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", wseg])
        aud_files.append(wseg)
        print("  %-14s %5.1fs  %s" % (sc["id"], seg_len,
                                      "recorded" if src == clip else "still"))

    lst = os.path.join(seg_dir, "segments.txt")
    io.open(lst, "w", encoding="utf-8").write(
        "\n".join("file '%s'" % s.replace("\\", "/") for s in seg_files) + "\n")
    alst = os.path.join(seg_dir, "audio.txt")
    io.open(alst, "w", encoding="utf-8").write(
        "\n".join("file '%s'" % s.replace("\\", "/") for s in aud_files) + "\n")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Picture joins by stream copy - every segment carries identical encoder
    # settings, so there is nothing to re-encode and no way to invent a frame.
    #
    # Audio does NOT join that way, and an earlier cut shipped because of it.
    # Every AAC segment carries encoder priming, and a stream-copy concat drops
    # it at each of the thirteen boundaries: the track ran ~450 ms ahead of the
    # picture by the outro, and syllables went missing at the joins. So the
    # narration is concatenated as PCM - sample-exact, no priming, no seams -
    # normalised once over the whole track, and encoded a single time.
    silent = os.path.join(seg_dir, "picture.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent])

    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", silent,
         "-f", "concat", "-safe", "0", "-i", alst,
         "-map", "0:v", "-map", "1:a",
         "-af", AUDIO_CHAIN,
         "-c:v", "copy",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
         "-shortest",                     # never outrun the picture
         "-movflags", "+faststart", OUT])

    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", "6", "-i", os.path.join(SP, "00_landing.mp4"),
         "-frames:v", "1",
         "-vf", "scale=1920:1080:flags=lanczos", "-q:v", "3", POSTER])

    # Captions from the same script the voice read, so they cannot drift out of
    # step with it. Long lines are split at sentence ends - a twenty-second cue
    # is unreadable.
    with io.open(VTT, "w", encoding="utf-8") as fh:
        fh.write("WEBVTT\n\n")
        for a, b, text in cues:
            parts = [p.strip() + "." for p in text.split(". ") if p.strip()]
            parts[-1] = parts[-1].rstrip(".") + "."
            step = (b - a) / len(parts)
            for j, part in enumerate(parts):
                fh.write("%s --> %s\n%s\n\n"
                         % (ts(a + j * step), ts(a + (j + 1) * step), part))
    print("  %s  %d cues" % (VTT, sum(1 for _ in io.open(VTT, encoding="utf-8")
                                      if "-->" in _)))

    print("\n  %s  %.1f MB  %.0fs" % (OUT, os.path.getsize(OUT) / 1e6, total))
    print("  %s  %.0f KB" % (POSTER, os.path.getsize(POSTER) / 1e3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
