#!/usr/bin/env python3
"""make_narration_neural.py - render the tour narration with a neural voice.

The voice is whatever tour_script.json's "voice" field names; "rate" is passed
straight through. Output is 48 kHz mono WAV, one file per scene, which is what
build_tour.py lays over the picture.

Two things beyond the voice itself:

  * 96 kbps from the service rather than its 48 kbps default. Same voice, same
    timing to the millisecond (checked on all thirteen lines), cleaner
    consonants.

  * the dead air goes. Each line arrives with ~0.2 s before its first word and
    ~0.9 s after its last, and the voice parks for about a second at every full
    stop. Laid end to end that was 31.6 s of silence in a 108 s tour - 24 gaps,
    every scene change a 1.5 s hole - which is what made the narration
    stop-start instead of fluent, and the word after a long hole is the one a
    listener misses. Lines are now trimmed to HEAD before the first word and
    TAIL after the last, and any pause inside a line is held to MAX_PAUSE.

Note: this sends the narration lines to Microsoft's TTS endpoint. They are the
same sentences that are published on the guide page.

usage: python make_narration_neural.py [outdir]
"""
import asyncio
import io
import json
import os
import subprocess
import sys
import wave

import aiohttp
import edge_tts
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = (r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
               r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour4k")

FORMAT = "audio-24khz-96kbitrate-mono-mp3"
SR = 48000
HEAD = 0.08          # kept before the first word
TAIL = 0.25          # kept after the last word
MAX_PAUSE = 0.55     # longest silence allowed inside a line
FRAME = 0.01         # 10 ms analysis frames
FLOOR_DB = 40        # a frame is silence when it sits this far under the peak
XFADE = 0.005        # splice crossfade, applied only inside silence


# edge-tts hard-codes the 48 kbps format in the request it sends; swap it on
# the way out. The service accepts the 96 kbps mp3 and rejects the rest.
_send_str = aiohttp.ClientWebSocketResponse.send_str


async def _send_str_96k(self, data, *a, **k):
    return await _send_str(
        self, data.replace("audio-24khz-48kbitrate-mono-mp3", FORMAT), *a, **k)


aiohttp.ClientWebSocketResponse.send_str = _send_str_96k


def decode(mp3):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp3, "-ac", "1",
                          "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def tighten(x):
    """Trim the ends of a line and hold every internal pause to MAX_PAUSE."""
    hop = int(SR * FRAME)
    n = len(x) // hop
    if n == 0:
        return x
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-12
    db = 20 * np.log10(rms)
    voiced = db > db.max() - FLOOR_DB
    idx = np.where(voiced)[0]
    if not len(idx):
        return x
    first, last = idx[0], idx[-1] + 1

    # sample ranges to keep, walking the frames between first and last word
    keep, seg_start, run_start = [], first * hop, None
    cap = int(round(MAX_PAUSE / FRAME))
    for f in range(first, last + 1):
        silent = f < last and not voiced[f]
        if silent and run_start is None:
            run_start = f
        elif not silent and run_start is not None:
            if f - run_start > cap:
                half = cap // 2
                keep.append((seg_start, (run_start + half) * hop))
                seg_start = (f - (cap - half)) * hop
            run_start = None
    keep.append((seg_start, last * hop))

    fade = int(XFADE * SR)
    pieces = []
    for i, (a, b) in enumerate(keep):
        p = x[a:b].copy()
        if i > 0 and len(p) > fade:
            p[:fade] *= np.linspace(0.0, 1.0, fade)
        if i < len(keep) - 1 and len(p) > fade:
            p[-fade:] *= np.linspace(1.0, 0.0, fade)
        pieces.append(p)
    body = np.concatenate(pieces)
    head = x[max(first * hop - int(HEAD * SR), 0):first * hop]
    tail = x[last * hop:min(last * hop + int(TAIL * SR), len(x))]
    return np.concatenate([head, body, tail])


def write_wav(path, x):
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)


async def say(text, voice, rate, out_wav):
    mp3 = out_wav[:-4] + ".mp3"
    await edge_tts.Communicate(text, voice, rate=rate).save(mp3)
    raw = decode(mp3)
    os.remove(mp3)
    tight = tighten(raw)
    write_wav(out_wav, tight)
    return len(raw) / SR, len(tight) / SR


async def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    os.makedirs(outdir, exist_ok=True)
    script = json.load(io.open(os.path.join(HERE, "tour_script.json"),
                               encoding="utf-8"))
    voice = script.get("voice", "en-US-AriaNeural")
    rate = script.get("rate", "-4%")
    if not isinstance(rate, str):
        rate = "+0%"
    print("voice: %s   rate: %s   format: %s" % (voice, rate, FORMAT))

    before = after = 0.0
    for sc in script["scenes"]:
        p = os.path.join(outdir, sc["id"] + ".wav")
        b, a = await say(sc["say"], voice, rate, p)
        before += b
        after += a
        print("  %-14s %5.2fs -> %5.2fs" % (sc["id"], b, a))
    print("\n  narration total: %.1fs -> %.1fs" % (before, after))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
