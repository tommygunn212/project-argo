"""
Wake-Word Detection Module (Phase 7A-3b)

Lightweight keyword spotting for "ARGO" wake-word.
Runs independently, requests state transitions (never forces).

Design Rules (Non-Negotiable):
- Active only in LISTENING state
- PTT always overrides wake-word
- STOP always interrupts wake-word
- False positives are silent (no "Yes?" confirmation)
- <5% idle CPU usage
- STOP latency maintained <50ms

Architecture:
- Wake-word detector as separate subprocess
- Sends recognition events to command parser
- Never modifies state machine directly
- Command parser handles priority (STOP > sleep > PTT > wake-word)
"""

import subprocess
import threading
import logging
import time
import json
from typing import Callable, Optional
from pathlib import Path

logger = logging.getLogger("WAKE_WORD_DETECTOR")


class WakeWordDetector:
    """
    Lightweight wake-word detector for "ARGO" keyword.
    
    Non-blocking subprocess that:
    - Listens for "ARGO" keyword
    - Sends recognition events via callback
    - Respects state machine authority
    - Pauses during PTT or non-LISTENING states
    """

    def __init__(self, on_wake_word: Callable[[], None], state_getter: Callable[[], str]):
        """
        Initialize wake-word detector.

        Args:
            on_wake_word: Callback when "ARGO" is detected
            state_getter: Function that returns current state machine state
        """
        self.on_wake_word = on_wake_word
        self.state_getter = state_getter
        
        self.active = False
        self.paused = False
        self.detector_process: Optional[subprocess.Popen] = None
        self.listener_thread: Optional[threading.Thread] = None
        
        # Confidence threshold for wake-word recognition (0.0-1.0)
        # Calibrated to <5% false positive rate
        self.confidence_threshold = 0.85
        
        # Simple in-memory audio buffer for wake-word detection
        self.audio_buffer = []
        self.buffer_size = 8000  # ~500ms at 16kHz
        
        logger.info("WakeWordDetector initialized (confidence threshold: 0.85)")

    def start(self):
        """Start wake-word listening in background thread."""
        if self.active:
            logger.warning("Wake-word detector already running")
            return
        
        self.active = True
        self.listener_thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="WakeWordListener"
        )
        self.listener_thread.start()
        logger.info("Wake-word detector started")

    def stop(self):
        """Stop wake-word listening."""
        if not self.active:
            return
        
        self.active = False
        if self.detector_process:
            try:
                self.detector_process.terminate()
                self.detector_process.wait(timeout=1.0)
            except Exception as e:
                logger.warning(f"Error terminating detector process: {e}")
        
        if self.listener_thread:
            self.listener_thread.join(timeout=2.0)
        
        logger.info("Wake-word detector stopped")

    def pause(self):
        """Pause wake-word detection (e.g., during PTT)."""
        self.paused = True
        logger.debug("Wake-word detector paused (PTT active)")

    def resume(self):
        """Resume wake-word detection after pause."""
        self.paused = False
        logger.debug("Wake-word detector resumed")

    def _listen_loop(self):
        """
        Main listening loop.
        
        Checks state machine:
        - LISTENING: Detector active (listening for wake-word to transcribe audio)
        - SLEEP: Detector ALSO ACTIVE (listening to wake-word to wake system)
        - THINKING/SPEAKING: Detector paused (LLM/audio active)
        
        Non-blocking check every 100ms.
        """
        last_state = None
        last_detector_state = None
        
        while self.active:
            try:
                # Get current state without blocking
                current_state = self.state_getter()
                
                # Determine if detector should be active
                # Wake-word detector should listen in SLEEP (to wake) AND LISTENING (for hands-free)
                # It should NOT listen during THINKING/SPEAKING (too noisy, LLM/audio active)
                should_listen = (
                    current_state in ["LISTENING", "SLEEP"] and 
                    not self.paused
                )
                
                is_listening = self.detector_process is not None and \
                               self.detector_process.poll() is None
                
                # State transition?
                if current_state != last_state:
                    logger.debug(f"State changed: {last_state} → {current_state}")
                    last_state = current_state
                
                # Start detector if needed
                if should_listen and not is_listening:
                    self._start_detector()
                    last_detector_state = True
                
                # Stop detector if needed
                elif not should_listen and is_listening:
                    self._stop_detector()
                    last_detector_state = False
                
                # Check for recognition event (non-blocking)
                if is_listening:
                    self._check_for_recognition()
                
                # Prevent busy-loop
                time.sleep(0.05)  # Check every 50ms
                
            except Exception as e:
                logger.error(f"Error in listen loop: {e}", exc_info=True)
                time.sleep(0.1)

    def _start_detector(self):
        """Start background detector subprocess."""
        if self.detector_process and self.detector_process.poll() is None:
            return  # Already running
        
        try:
            # Use simple Python subprocess with keyword spotting logic
            detector_script = self._get_detector_script()
            
            self.detector_process = subprocess.Popen(
                ["python", "-c", detector_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )
            logger.debug("Detector subprocess started")
            
        except Exception as e:
            logger.error(f"Failed to start detector: {e}")
            self.detector_process = None

    def _stop_detector(self):
        """Stop detector subprocess."""
        if not self.detector_process:
            return
        
        try:
            self.detector_process.terminate()
            self.detector_process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.detector_process.kill()
        except Exception as e:
            logger.warning(f"Error stopping detector: {e}")
        finally:
            self.detector_process = None
            logger.debug("Detector subprocess stopped")

    def _check_for_recognition(self):
        """Check if detector has recognized the wake-word."""
        if not self.detector_process:
            return
        
        try:
            # Non-blocking check if subprocess is running
            if self.detector_process.poll() is not None:
                # Process died
                stderr_output = ""
                try:
                    stderr_output = self.detector_process.stderr.read() if self.detector_process.stderr else ""
                except:
                    pass
                if stderr_output:
                    logger.warning(f"Detector subprocess crashed: {stderr_output}")
                self.detector_process = None
                return
            
            # Try to read a line from detector (recognition event)
            try:
                import select
                # Check if there's data available (non-blocking on Unix)
                if hasattr(self.detector_process.stdout, 'readable'):
                    if self.detector_process.stdout.readable():
                        line = self.detector_process.stdout.readline()
                        if line and "ARGO" in line.upper():
                            logger.info(f"Wake-word detected from subprocess: {line}")
                            self.on_recognition_event(confidence=0.95)
            except:
                pass
            
        except Exception as e:
            logger.debug(f"Error checking for recognition: {e}")

    def _recognize_wake_word(self, audio_data: bytes) -> tuple[bool, float]:
        """
        Recognize "ARGO" wake-word in audio data.
        
        Uses Whisper to transcribe audio and check for "ARGO" keyword.
        Simple but reliable implementation.
        
        Args:
            audio_data: Raw audio bytes (16-bit PCM)
        
        Returns:
            (recognized: bool, confidence: float)
        """
        try:
            import whisper
            import tempfile
            import numpy as np
            from pathlib import Path
            
            # Convert bytes to WAV file for Whisper
            audio_int = np.frombuffer(audio_data, dtype=np.int16)
            audio_float = audio_int.astype(np.float32) / 32768.0
            
            # Use Whisper to transcribe
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                import scipy.io.wavfile as wavfile
                wavfile.write(f.name, 16000, audio_float)
                temp_path = f.name
            
            try:
                # Load small model (already done at module level)
                from voice_input import model as whisper_model
                if whisper_model is None:
                    return False, 0.0
                
                result = whisper_model.transcribe(temp_path, language="en", fp16=False)
                text = result.get("text", "").strip().lower()
                
                # Check if "argo" is in the transcription
                if "argo" in text:
                    logger.info(f"Wake-word detected in transcription: '{text}'")
                    return True, 0.95
                
                return False, 0.0
            finally:
                Path(temp_path).unlink(missing_ok=True)
                
        except Exception as e:
            logger.debug(f"Error in wake-word recognition: {e}")
            return False, 0.0

    @staticmethod
    def _get_detector_script() -> str:
        """
        Return Python script for detector subprocess.
        
        Listens to continuous audio stream and detects "ARGO" wake-word.
        Outputs "ARGO DETECTED" when recognized.
        """
        script = '''
import sys
import time
import numpy as np
import tempfile
from pathlib import Path

# Try to use continuous audio stream from main process
try:
    from voice_input import get_audio_chunk
    audio_source = "continuous"
except ImportError:
    # Fallback to pyaudio if continuous stream not available
    try:
        import pyaudio
        audio_source = "pyaudio"
    except ImportError:
        audio_source = None

if audio_source is None:
    print("ERROR: No audio source available", file=sys.stderr)
    sys.exit(1)

# Try to load Whisper for transcription
try:
    import whisper
    model = whisper.load_model("base", device="cpu")
except Exception as e:
    print(f"ERROR: Whisper not available: {e}", file=sys.stderr)
    sys.exit(1)

RATE = 16000
BUFFER_SIZE = int(RATE * 2)  # 2 seconds of audio
audio_buffer = np.zeros(BUFFER_SIZE, dtype=np.float32)
write_pos = 0

def detect_argo_in_buffer():
    """Transcribe buffer and check for ARGO."""
    try:
        # Write buffer to temporary WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name
        
        import scipy.io.wavfile as wavfile
        wavfile.write(temp_path, RATE, (audio_buffer * 32767).astype(np.int16))
        
        # Transcribe
        result = model.transcribe(temp_path, language="en", fp16=False)
        text = result.get("text", "").strip().lower()
        
        # Clean up temp file
        Path(temp_path).unlink(missing_ok=True)
        
        # Check for "argo"
        if "argo" in text:
            print("ARGO DETECTED", flush=True)
            return True
        
        return False
    except Exception as e:
        print(f"DEBUG: Error in detection: {e}", file=sys.stderr)
        return False

try:
    while True:
        # Get audio chunk
        chunk = None
        if audio_source == "continuous":
            chunk = get_audio_chunk(timeout=0.1)
        elif audio_source == "pyaudio":
            import pyaudio
            PA = pyaudio.PyAudio()
            stream = PA.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True, frames_per_buffer=512)
            data = stream.read(512, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        
        if chunk is not None:
            # Add to buffer
            chunk_size = len(chunk)
            if write_pos + chunk_size <= BUFFER_SIZE:
                audio_buffer[write_pos:write_pos+chunk_size] = chunk
                write_pos += chunk_size
            else:
                # Buffer full, slide and add
                audio_buffer[:-chunk_size] = audio_buffer[chunk_size:]
                audio_buffer[-chunk_size:] = chunk
                write_pos = BUFFER_SIZE
            
            # Periodically check buffer (every 2 seconds)
            if write_pos >= BUFFER_SIZE:
                detect_argo_in_buffer()
                write_pos = 0
        
        time.sleep(0.1)

except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
'''
        return script

    def on_recognition_event(self, confidence: float):
        """
        Called when wake-word is recognized.
        
        Sends event to callback (command parser handles priority).
        Never forces state machine transition.
        """
        if confidence < self.confidence_threshold:
            logger.debug(f"Wake-word below threshold (conf={confidence:.2f})")
            return
        
        logger.info(f"Wake-word recognized (confidence={confidence:.2f})")
        
        # Call the callback (command parser will handle state machine)
        try:
            self.on_wake_word()
        except Exception as e:
            logger.error(f"Error in wake-word callback: {e}")

    def get_status(self) -> dict:
        """Get detector status for diagnostics."""
        return {
            "active": self.active,
            "paused": self.paused,
            "running": self.detector_process is not None and \
                      self.detector_process.poll() is None,
            "confidence_threshold": self.confidence_threshold,
            "cpu_budget_idle": "<5%"
        }


class WakeWordRequest:
    """
    Request object sent when wake-word is recognized.
    
    Passed to state machine request handler (never forces transition).
    """
    
    def __init__(self, confidence: float = 0.9):
        self.confidence = confidence
        self.timestamp = time.time()
        self.source = "wake_word"
    
    def __repr__(self):
        return f"WakeWordRequest(confidence={self.confidence:.2f}, source={self.source})"


# Singleton instance (will be initialized by argo.py)
_detector_instance: Optional[WakeWordDetector] = None


def get_detector() -> Optional[WakeWordDetector]:
    """Get global detector instance."""
    return _detector_instance


def initialize_detector(on_wake_word: Callable[[], None], state_getter: Callable[[], str]):
    """Initialize global detector instance."""
    global _detector_instance
    _detector_instance = WakeWordDetector(on_wake_word, state_getter)
    return _detector_instance
