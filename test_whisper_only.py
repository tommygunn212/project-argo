#!/usr/bin/env python
"""Test Whisper STT - Record audio from Device 36 and transcribe"""
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

DEVICE = 36  # Brio 500
SAMPLE_RATE = 16000
DURATION = 3  # Record for 3 seconds

print("=" * 60)
print("WHISPER STT TEST")
print("=" * 60)
print(f"Recording for {DURATION} seconds from Device {DEVICE}...")
print("SPEAK NOW!")
print()

# Record audio
audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=DEVICE)
sd.wait()

# Check volume
volume = np.linalg.norm(audio) * 10
print(f"✓ Recorded audio")
print(f"  - Shape: {audio.shape}")
print(f"  - Volume: {volume:.2f}")
print(f"  - Duration: {audio.shape[0] / SAMPLE_RATE:.2f}s")
print()

# Load Whisper model
print("Loading Whisper model...")
model = WhisperModel("base.en", device="cpu", compute_type="int8")
print("✓ Model loaded")
print()

# Transcribe
print("Transcribing...")
segments, info = model.transcribe(audio, language="en")
segments_list = list(segments)

print(f"✓ Transcription complete")
print(f"  - Language: {info.language} (prob: {info.language_probability:.2f})")
print(f"  - Segments detected: {len(segments_list)}")
print()

if segments_list:
    print("TRANSCRIPTION RESULTS:")
    print("-" * 60)
    for seg in segments_list:
        print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")
    
    full_text = " ".join([seg.text for seg in segments_list])
    print()
    print(f"FULL TEXT: {full_text}")
else:
    print("❌ NO SPEECH DETECTED")
    print()
    print("Troubleshooting:")
    print("  - Check if Device 36 is the right microphone")
    print("  - Try speaking louder")
    print("  - Check audio levels")

print()
print("=" * 60)
