#!/usr/bin/env python
"""Test Whisper STT - Record audio from Device 36 and transcribe"""
import pytest


def _has_whisper():
    """Check if faster_whisper is available."""
    try:
        from faster_whisper import WhisperModel
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_whisper(),
    reason="faster_whisper not available"
)


def test_whisper_transcription():
    """Test Whisper STT - Record audio and transcribe (requires microphone)."""
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
    try:
        audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=DEVICE)
        sd.wait()
    except Exception as e:
        pytest.skip(f"Audio device {DEVICE} not available: {e}")

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
        pytest.skip("No speech detected (interactive test requires human speech)")


if __name__ == "__main__":
    # Allow running directly for manual testing
    test_whisper_transcription()
    print("  - Check audio levels")

print()
print("=" * 60)
