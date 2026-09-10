#!/usr/bin/env python3
"""make_narration_neural.py - render the tour narration with a neural voice.

The Windows SAPI voices installed on this machine are David, Mark and Zira -
2013-era concatenative synths, and they sound it. edge-tts reaches Microsoft's
neural read-aloud voices, which is the difference between "a computer read my
script" and a narrator.

The voice is whatever tour_script.json's "voice" field names; "rate" is passed
straight through. Output is 48 kHz mono WAV, which is what build_tour.py feeds
into each segment.

Note: this sends the narration lines to Microsoft's TTS endpoint. They are the
same sentences that are published on the guide page.

usage: python make_narration_neural.py [outdir]
       python make_narration_neural.py --samples      (one line, every candidate)
"""
import asyncio
import io
import json
import os
import subprocess
import sys

import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = (r"C:\Users\mutxr\AppData\Local\Temp\claude\D--mutxri-terminal"
               r"\1c144fad-89e4-4b04-baf0-4f3e45e10bc6\scratchpad\tour4k")

# Shortlisted for a calm, factual read. Personalities are Microsoft's own tags.
CANDIDATES = [
    ("en-GB-RyanNeural", "British male, measured - the documentary register"),
    ("en-US-AndrewNeural", "US male, warm and confident"),
    ("en-US-ChristopherNeural", "US male, authority"),
    ("en-GB-SoniaNeural", "British female, calm"),
    ("en-US-AriaNeural", "US female, confident"),
]
SAMPLE_LINE = ("This is the board. One thousand and twenty five listed companies "
               "across Johannesburg, Lagos, Nairobi and Cairo, priced at the last close.")


def to_wav(mp3, wav):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", mp3, "-ar", "48000", "-ac", "1", wav], check=True)
    os.remove(mp3)


def dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


async def say(text, voice, rate, out_wav):
    mp3 = out_wav[:-4] + ".mp3"
    await edge_tts.Communicate(text, voice, rate=rate).save(mp3)
    to_wav(mp3, out_wav)


async def samples(outdir):
    os.makedirs(outdir, exist_ok=True)
    for voice, note in CANDIDATES:
        p = os.path.join(outdir, "sample_%s.wav" % voice)
        await say(SAMPLE_LINE, voice, "-4%", p)
        print("  %-26s %5.1fs  %s" % (voice, dur(p), note))


async def main():
    if "--samples" in sys.argv:
        outdir = os.path.join(DEFAULT_OUT, "voice_samples")
        await samples(outdir)
        print("\n  samples in", outdir)
        return 0

    outdir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    os.makedirs(outdir, exist_ok=True)
    script = json.load(io.open(os.path.join(HERE, "tour_script.json"),
                               encoding="utf-8"))
    voice = script.get("voice", "en-GB-RyanNeural")
    rate = script.get("rate", "-4%")
    if not isinstance(rate, str):
        rate = "+0%"
    print("voice: %s   rate: %s" % (voice, rate))

    total = 0.0
    for sc in script["scenes"]:
        p = os.path.join(outdir, sc["id"] + ".wav")
        await say(sc["say"], voice, rate, p)
        d = dur(p)
        total += d
        print("  %-14s %5.1fs" % (sc["id"], d))
    print("\n  narration total: %.1fs" % total)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
