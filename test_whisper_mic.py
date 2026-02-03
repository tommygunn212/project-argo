#!/usr/bin/env python3
"""
Test Whisper speech recognition from Device 1 (Brio 500)
"""
import sys
import pytest


def _has_cuda_whisper():
    """Check if CUDA and faster_whisper are available."""
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        from faster_whisper import WhisperModel
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_cuda_whisper(),
    reason="CUDA or faster_whisper not available"
)


def test_whisper_mic_transcription():
    """Test Whisper speech recognition from microphone (requires human speech)."""
    import sounddevice as sd
    import numpy as np
    from faster_whisper import WhisperModel

    print("[WHISPER TEST] Recording 5 seconds from Device 1 (Brio 500)...")
    print("[WHISPER TEST] SPEAK CLEARLY NOW!")

    # Record audio
    duration = 5
    sample_rate = 16000
    try:
        audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32', device=1)
        sd.wait()
    except Exception as e:
        pytest.skip(f"Audio device 1 not available: {e}")

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
        pytest.skip("No speech detected (interactive test requires human speech)")


if __name__ == "__main__":
    # Allow running directly for manual testing
    test_whisper_mic_transcription()
