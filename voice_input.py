#!/usr/bin/env python3
"""
Push-to-Talk (PTT) Voice Input via Microphone
Records audio when spacebar is held, transcribes with Whisper
"""

import sounddevice as sd
import numpy as np
import whisper
import sys
from pathlib import Path
import tempfile

# Load Whisper model once
try:
    model = whisper.load_model("small", device="cpu")
    WHISPER_READY = True
except Exception as e:
    print(f"❌ Whisper failed to load: {e}", file=sys.stderr)
    WHISPER_READY = False

SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1

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
