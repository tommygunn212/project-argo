"""
TASK 8 Test: Speech-to-Text (Isolated)

Minimal proof:
1. Record audio from microphone (5 seconds)
2. Transcribe using Whisper
3. Print result
4. Exit

No wake word logic.
No intent parsing.
No Coordinator wiring.
Just transcription.
"""

import sys
import time
import numpy as np
import sounddevice as sd

# Fix encoding for Windows console
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

from core.speech_to_text import WhisperSTT


def record_audio(duration=5, sample_rate=16000):
    """Record audio from microphone (blocking)."""
    print(f"[*] Recording for {duration} seconds...")
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype=np.int16,
    )
    sd.wait()  # Block until recording complete
    print(f"[OK] Recorded {len(audio)} samples")
    return audio, sample_rate


def save_as_wav(audio, sample_rate):
    """Convert audio to WAV format (bytes)."""
    from scipy.io import wavfile
    import io

    buffer = io.BytesIO()
    wavfile.write(buffer, sample_rate, audio)
    return buffer.getvalue()


def main():
    print("=" * 60)
    print("TASK 8: Speech-to-Text (Isolated)")
    print("=" * 60)

    try:
        # Initialize STT engine
        print("\n[*] Initializing Whisper STT...")
        stt = WhisperSTT()
        print("[OK] Whisper loaded (base model)")

        # Record audio
        print("\n[*] Listening for speech...")
        audio, sample_rate = record_audio(duration=5)

        # Convert to WAV bytes
        audio_wav = save_as_wav(audio, sample_rate)
        print(f"[OK] Converted to WAV: {len(audio_wav)} bytes")

        # Transcribe
        print("\n[*] Transcribing...")
        text = stt.transcribe(audio_wav, sample_rate)
        print("[OK] Transcription complete")

        # Print result
        print("\n" + "=" * 60)
        print("TRANSCRIBED TEXT:")
        print("=" * 60)
        print(f'"{text}"')
        print("=" * 60)

        print("\n[OK] SUCCESS")
        print("Speech-to-text works (once, no retries, no streaming)")
        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
