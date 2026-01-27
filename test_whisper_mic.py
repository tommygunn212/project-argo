#!/usr/bin/env python3
"""
Test Whisper speech recognition from Device 1 (Brio 500)
"""
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import sys

print("[WHISPER TEST] Recording 5 seconds from Device 1 (Brio 500)...")
print("[WHISPER TEST] SPEAK CLEARLY NOW!")

# Record audio
duration = 5
sample_rate = 16000
audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32', device=1)
sd.wait()

print(f"[WHISPER TEST] Recording complete")
print(f"[WHISPER TEST] Audio shape: {audio.shape}")
print(f"[WHISPER TEST] Peak: {np.max(np.abs(audio)):.4f}")
print(f"[WHISPER TEST] Volume: {np.linalg.norm(audio) * 10:.2f}")

# Load Whisper model
print(f"[WHISPER TEST] Loading Whisper model...")
model = WhisperModel("base.en", device="cuda", compute_type="float16")

# Squeeze audio to 1D (critical fix)
audio = np.squeeze(audio)
print(f"[WHISPER TEST] Audio after squeeze: {audio.shape}")

# Transcribe
print(f"[WHISPER TEST] Transcribing...")
segments, info = model.transcribe(audio, beam_size=5, language="en")
segments_list = list(segments)

print(f"\n[WHISPER TEST] Language: {info.language} (probability: {info.language_probability:.2f})")
print(f"[WHISPER TEST] Detected {len(segments_list)} segments:")

if segments_list:
    for i, seg in enumerate(segments_list):
        print(f"  Segment {i}: '{seg.text}' (start: {seg.start:.2f}s, end: {seg.end:.2f}s)")
    
    full_text = " ".join([s.text for s in segments_list]).strip()
    print(f"\n[WHISPER TEST] ✓ FULL TRANSCRIPTION: '{full_text}'")
else:
    print(f"  [WHISPER TEST] ✗ NO SPEECH DETECTED")
    sys.exit(1)
