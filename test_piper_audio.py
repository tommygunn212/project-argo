#!/usr/bin/env python3
"""
Simple Piper TTS test - generates audio and plays it
"""
import subprocess
import sys
import os
import shutil
import pytest


def _piper_module_available():
    """Check if piper can be run as a Python module."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "piper", "--help"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


# Skip if piper binary not available
pytestmark = pytest.mark.skipif(
    shutil.which("piper") is None and not _piper_module_available(),
    reason="Piper binary/module not available"
)


def test_piper_audio_basic():
    """Test Piper TTS audio generation and playback."""
    import sounddevice as sd
    import numpy as np

    # Piper model paths
    piper_voice_dir = os.path.expanduser("~/.local/share/piper/en_US-lessac-medium")
    piper_model_path = os.path.join(piper_voice_dir, "en_US-lessac-medium.onnx")

    if not os.path.exists(piper_model_path):
        pytest.skip(f"Piper model not found: {piper_model_path}")

    # Test text to synthesize
    test_text = "Hello! This is Argo text to speech. It is working!"

    print(f"[TEST] Synthesizing: '{test_text}'")
    print(f"[TEST] Model: {piper_model_path}")

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
        pytest.skip("No audio generated (piper module may not be installed)")

    # Convert bytes to audio samples (int16, 22050 Hz, mono)
    audio_samples = np.frombuffer(stdout_data, dtype='int16').astype('float32') / 32768.0

    print(f"[TEST] Audio shape: {audio_samples.shape}")
    print(f"[TEST] Sample rate: 22050 Hz")
    print(f"[TEST] Playing through Device 4 (M-Track Speakers)...")

    # Play the audio
    sd.play(audio_samples, samplerate=22050, device=4)
    sd.wait()

    print(f"[TEST] ✓ Playback complete!")


if __name__ == "__main__":
    # Allow running directly for manual testing
    test_piper_audio_basic()
