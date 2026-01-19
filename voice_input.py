#!/usr/bin/env python3
"""
Voice Input Module: Continuous Audio Stream + PTT + Wake-word Support

Handles:
- Continuous audio stream (feeds wake-word detector while idle)
- Push-to-Talk recording (spacebar override)
- Whisper transcription
"""

import sounddevice as sd
import numpy as np
import whisper
import sys
import threading
import logging
from pathlib import Path
import tempfile
from typing import Optional, Callable

logger = logging.getLogger("VOICE_INPUT")

# Load Whisper model once
try:
    model = whisper.load_model("small", device="cpu")
    WHISPER_READY = True
except Exception as e:
    print(f"❌ Whisper failed to load: {e}", file=sys.stderr)
    WHISPER_READY = False

SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1

# Global continuous audio stream (for wake-word detection)
_audio_stream: Optional[sd.InputStream] = None
_audio_buffer: list = []
_audio_lock = threading.Lock()

def start_continuous_audio_stream():
    """
    Start continuous audio stream for wake-word detection.
    
    Runs in background, feeds audio to wake-word detector while in SLEEP state.
    Called at startup to activate microphone.
    """
    global _audio_stream
    
    if _audio_stream is not None:
        logger.debug("Continuous audio stream already running")
        return True
    
    try:
        _audio_stream = sd.InputStream(
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=int(SAMPLE_RATE * 0.1),  # 100ms chunks
            latency="low"
        )
        _audio_stream.start()
        logger.info("Continuous audio stream started for wake-word detection")
        return True
    except Exception as e:
        logger.error(f"Failed to start audio stream: {e}")
        return False


def stop_continuous_audio_stream():
    """Stop the continuous audio stream."""
    global _audio_stream
    
    if _audio_stream is not None:
        try:
            _audio_stream.stop()
            _audio_stream.close()
            _audio_stream = None
            logger.info("Continuous audio stream stopped")
        except Exception as e:
            logger.error(f"Error stopping audio stream: {e}")


def record_audio_on_wake_word() -> Optional[np.ndarray]:
    """
    Record audio after wake-word detected.
    
    Captures ~3 seconds of audio from continuous stream.
    Used to capture the spoken question after "Argo" wakes system.
    
    Returns:
        Audio array ready for Whisper transcription
    """
    if _audio_stream is None:
        logger.error("Audio stream not available for wake-word recording")
        return None
    
    try:
        logger.info("Recording audio after wake-word detection...")
        recording = []
        duration_seconds = 3.0
        chunks_needed = int(duration_seconds / 0.1)  # 100ms per chunk
        
        for _ in range(chunks_needed):
            try:
                data, _ = _audio_stream.read(int(SAMPLE_RATE * 0.1))
                recording.append(data)
            except Exception as e:
                logger.debug(f"Error reading chunk: {e}")
                break
        
        if recording:
            audio = np.concatenate(recording)
            logger.info(f"Recorded {len(audio)/SAMPLE_RATE:.2f}s of audio")
            return audio
        else:
            logger.warning("No audio recorded after wake-word")
            return None
            
    except Exception as e:
        logger.error(f"Error recording audio on wake-word: {e}")
        return None

def record_audio_with_spacebar():
    """
    Records audio while user holds spacebar.
    Returns numpy array of audio data, or None if cancelled.
    """
    try:
        import keyboard
    except ImportError:
        print("❌ keyboard module not installed (required for PTT). Install with: pip install keyboard", file=sys.stderr)
        return None
    
    print("\n🎤 PTT Ready - Hold SPACEBAR to record (release to stop)", file=sys.stderr)
    
    # Wait for spacebar press
    keyboard.wait('space')
    
    print("🔴 Recording...", file=sys.stderr, end='', flush=True)
    
    # Start recording
    recording = []
    stream = sd.InputStream(
        channels=CHANNELS,
        samplerate=SAMPLE_RATE,
        blocksize=int(SAMPLE_RATE * 0.1)  # 100ms chunks
    )
    
    with stream:
        while keyboard.is_pressed('space'):
            data, _ = stream.read(int(SAMPLE_RATE * 0.1))
            recording.append(data)
            print(".", file=sys.stderr, end='', flush=True)
    
    print("\n✅ Recording complete", file=sys.stderr)
    
    if not recording:
        print("❌ No audio recorded", file=sys.stderr)
        return None
    
    audio_data = np.concatenate(recording)
    return audio_data

def transcribe_audio(audio_data):
    """
    Transcribes audio data using Whisper.
    Returns transcription string, or None on error.
    """
    if not WHISPER_READY:
        print("❌ Whisper not available", file=sys.stderr)
        return None
    
    print("🔄 Transcribing...", file=sys.stderr)
    
    try:
        # Create temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            import soundfile as sf
            sf.write(tmp.name, audio_data, SAMPLE_RATE)
            tmp_path = tmp.name
        
        # Transcribe
        result = model.transcribe(tmp_path, language="en")
        
        # Clean up
        Path(tmp_path).unlink()
        
        text = result.get("text", "").strip()
        if text:
            print(f"📝 Transcribed: \"{text}\"", file=sys.stderr)
            return text
        else:
            print("⚠️  No speech detected", file=sys.stderr)
            return None
            
    except Exception as e:
        print(f"❌ Transcription error: {e}", file=sys.stderr)
        return None

def get_voice_input_ptt():
    """
    Gets voice input via push-to-talk spacebar.
    
    Returns: transcribed text, or empty string if cancelled
    """
    try:
        audio = record_audio_with_spacebar()
        if audio is None:
            return ""
        
        text = transcribe_audio(audio)
        return text if text else ""
        
    except KeyboardInterrupt:
        print("\n❌ Cancelled", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"❌ Voice input error: {e}", file=sys.stderr)
        return ""

if __name__ == "__main__":
    result = get_voice_input_ptt()
    if result:
        print(f"User said: {result}")
    else:
        print("No input")
