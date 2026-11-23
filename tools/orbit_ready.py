"""Persist Orbit completion in ARGO reminders and play an original musical alarm."""
from __future__ import annotations
import argparse
import math
import struct
import sys
import wave
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MESSAGE = "Tommy, Orbit is ready. Open the Orbit demo or select Orbit in ARGO."

def create_alarm(path):
    rate = 22050
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        for frequency in (261.63, 329.63, 392, 523.25, 392, 329.63, 293.66, 392, 493.88, 587.33, 523.25, 392):
            samples = []
            for n in range(int(rate * .28)):
                t = n / rate
                envelope = min(1, t / .015) * max(0, 1 - t / .28)
                samples.append(struct.pack("<h", int(6000 * envelope * math.sin(2 * math.pi * frequency * t))))
            wav.writeframes(b"".join(samples))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-play", action="store_true", help="Save reminder and WAV without playing")
    args = parser.parse_args()
    from tools import reminders
    pending = next((r for r in reminders.list_reminders() if r["message"] == MESSAGE), None)
    saved = pending or reminders.add_reminder(MESSAGE, datetime.now())
    print(f"Orbit completion reminder persisted: id={saved['id']}")
    folder = ROOT / "runtime" / "orbit"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "orbit-ready.wav"
    create_alarm(path)
    if not args.no_play:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        print("Music playback call completed; speaker audibility requires Tommy's confirmation.")
    print(MESSAGE)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
