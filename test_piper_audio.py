#!/usr/bin/env python3
"""
Simple Piper TTS test - generates audio and plays it
"""
import subprocess
import sys
import os
import sounddevice as sd
import numpy as np

# Piper model paths
piper_voice_dir = os.path.expanduser("~/.local/share/piper/en_US-lessac-medium")
piper_model_path = os.path.join(piper_voice_dir, "en_US-lessac-medium.onnx")

# Test text to synthesize
test_text = "Hello! This is Piper text to speech. It is working!"

print(f"[TEST] Synthesizing: '{test_text}'")
print(f"[TEST] Model: {piper_model_path}")

try:
    # Run Piper and capture audio output
    cmd = [sys.executable, "-m", "piper", "--model", piper_model_path, "--output-raw"]
    
    print(f"[TEST] Running: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Send text to Piper
    stdout_data, stderr_data = process.communicate(input=test_text.encode('utf-8'))
    
    if stderr_data:
        print(f"[ERROR] Piper stderr: {stderr_data.decode()}")
    
    # Check if we got audio
    audio_bytes = len(stdout_data)
    print(f"[TEST] Generated {audio_bytes} bytes of audio")
    
    if audio_bytes == 0:
        print("[ERROR] No audio generated!")
        sys.exit(1)
    
    # Convert bytes to audio samples (int16, 22050 Hz, mono)
    audio_samples = np.frombuffer(stdout_data, dtype='int16').astype('float32') / 32768.0
    
    print(f"[TEST] Audio shape: {audio_samples.shape}")
    print(f"[TEST] Sample rate: 22050 Hz")
    print(f"[TEST] Playing through Device 4 (M-Track Speakers)...")
    
    # Play the audio
    sd.play(audio_samples, samplerate=22050, device=4)
    sd.wait()
    
    print(f"[TEST] ✓ Playback complete!")
    
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
