#!/usr/bin/env python
"""Test Whisper STT with Device 1"""
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

DEVICE = 1  # Speakerphone (Brio 500) - alternate index
SAMPLE_RATE = 16000
DURATION = 3

print("=" * 60)
print("WHISPER STT TEST - Device 1")
print("=" * 60)
print(f"Recording for {DURATION} seconds from Device {DEVICE}...")
print("SPEAK NOW!")
print()

# Record audio
audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=DEVICE)
sd.wait()

# Check volume
volume = np.linalg.norm(audio) * 10
peak = np.max(np.abs(audio))
print(f"✓ Recorded audio")
print(f"  - Shape: {audio.shape}")
print(f"  - Volume: {volume:.2f}")
print(f"  - Peak: {peak:.4f}")
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
print("=" * 60)
