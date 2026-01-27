#!/usr/bin/env python
"""Generate test audio and transcribe with Whisper"""
import numpy as np
from faster_whisper import WhisperModel
import soundfile as sf

print("=" * 60)
print("WHISPER SYNTHETIC AUDIO TEST")
print("=" * 60)
print()

# Generate synthetic speech-like audio (white noise for now)
SAMPLE_RATE = 16000
DURATION = 2

print(f"Generating synthetic audio ({DURATION}s)...")
# Generate audio with speech-like pattern
t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), dtype=np.float32)
# Create audio with frequency variations (simulating speech)
audio = (0.1 * np.sin(2 * np.pi * 200 * t) +  # Low frequency
         0.1 * np.sin(2 * np.pi * 500 * t) +  # Mid frequency
         0.05 * np.sin(2 * np.pi * 1000 * t))  # High frequency

volume = np.linalg.norm(audio) * 10
peak = np.max(np.abs(audio))
print(f"✓ Generated synthetic audio")
print(f"  - Shape: {audio.shape}")
print(f"  - Volume: {volume:.2f}")
print(f"  - Peak: {peak:.4f}")
print()

# Save it
print("Saving to test_synthetic.wav...")
sf.write("i:/argo/test_synthetic.wav", audio, SAMPLE_RATE)
print("✓ Saved")
print()

# Load Whisper model
print("Loading Whisper model...")
model = WhisperModel("base.en", device="cpu", compute_type="int8")
print("✓ Model loaded")
print()

# Transcribe
print("Transcribing synthetic audio...")
segments, info = model.transcribe("i:/argo/test_synthetic.wav", language="en")
segments_list = list(segments)

print(f"✓ Transcription complete")
print(f"  - Segments detected: {len(segments_list)}")
print()

if segments_list:
    print("RESULTS:")
    for seg in segments_list:
        print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")
else:
    print("❌ NO SPEECH DETECTED IN SYNTHETIC AUDIO")
    print()
    print("This suggests Whisper model might not be working properly")
    print("Or we need to use a different audio format/approach")

print()
print("=" * 60)
