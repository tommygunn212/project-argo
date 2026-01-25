"""
INPUT TRIGGER ABSTRACTION

Foundation layer for input events (TASK 6).

Core principle: Detect a condition, emit an event. Nothing else.
- No logic about what to do with the event
- No downstream orchestration
- No speech recognition
- No timers or retries

Design:
- InputTrigger: Abstract base class (on_trigger(callback) → listen)
- PorcupineWakeWordTrigger: Concrete implementation (wake word detection)
- Event: Simple notification (no payload needed, "it happened")

Each trigger is:
- Boring (no complexity beyond detection)
- Predictable (deterministic detection)
- Replaceable (can swap implementations)

Configuration:
- TRIGGER_ENABLED (env var): Enable/disable input triggers
- Other triggers can be added by implementing InputTrigger interface
"""

from abc import ABC, abstractmethod
import logging
import threading
import time
from typing import Callable, Optional
import warnings

# Suppress sounddevice Windows cffi warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="sounddevice")

# === Logging ===
logger = logging.getLogger(__name__)


# ============================================================================
# INPUT TRIGGER BASE CLASS (TASK 6: FOUNDATION LAYER)
# ============================================================================

class InputTrigger(ABC):
    """
    Abstract base class for input triggers.
    
    Responsibility: Detect a trigger condition, emit an event.
    
    This abstraction defines a boundary for input layers.
    Implementations must be:
    - Boring (no complexity beyond detection)
    - Predictable (deterministic detection)
    - Replaceable (can swap implementations)
    
    What InputTrigger is NOT:
    - Not a decision maker (no logic about what to do)
    - Not an orchestrator (no sequencing or timing)
    - Not an AI layer (no intent, entity extraction, etc.)
    - Not a validator (no checks on trigger quality)
    - Not a retry manager (no recovery logic)
    - Not a recorder (no audio capture, buffering, or storage)
    
    Interface:
    - on_trigger(callback: Callable) → start listening (blocking or async)
    - callback(event_data) → invoked when triggered
    
    Contract:
    - Call callback once per trigger (or raise exception)
    - No payload needed (callback() is enough)
    - Listen indefinitely (or until stop() called)
    """
    
    @abstractmethod
    def on_trigger(self, callback: Callable) -> None:
        """
        Listen for trigger condition and invoke callback when detected.
        
        Args:
            callback: Function to call when trigger detected.
                     Signature: callback() → None
                     No args, no return value needed.
        
        Returns:
            None (blocking call, runs until trigger detected or exception)
        
        Behavior:
        - Detect trigger condition (wake word, hotkey, network event, etc.)
        - When detected: invoke callback() once
        - Exit after callback completes
        - If multiple detections: fire callback again (or suppress repeats)
        
        Raises:
            Exception: If detection fails (caller responsibility to handle)
        
        Implementation notes:
        - This is a blocking call (waits for trigger)
        - Simple callback interface (no args, no return value)
        - Deterministic: same conditions → same detection every time
        """
        pass


# ============================================================================
# PORCUPINE WAKE WORD TRIGGER (TASK 4: PROVEN PIPELINE)
# ============================================================================

class PorcupineWakeWordTrigger(InputTrigger):
    """
    Reference implementation: Porcupine wake word detection.
    
    Uses Porcupine locally to detect wake words:
    1. Initialize Porcupine with access key
    2. Capture audio continuously
    3. Feed frames to Porcupine
    4. When wake word detected: invoke callback
    5. Exit (or loop for multiple detections)
    
    Configuration (hardcoded for predictability):
    - Access Key: Obtained from PORCUPINE_ACCESS_KEY env var
    - Wake Word: "picovoice" (default Porcupine wake word)
    - Audio device: Default system microphone
    - Frame rate: 16kHz mono (Porcupine standard)
    
    This implementation is blocking - on_trigger(callback) runs
    until wake word is detected.
    
    Responsibility: Detect wake word and emit event. That's it.
    No logic about what to do with the detection.
    """
    
    def __init__(self, access_key: Optional[str] = None):
        """
        Initialize PorcupineWakeWordTrigger.
        
        Args:
            access_key: Porcupine access key (default: from env var)
        
        Raises:
            ValueError: If Porcupine not available or access key missing
        """
        import os
        
        self.logger = logger
        self.access_key = access_key or os.getenv("PORCUPINE_ACCESS_KEY")
        
        if not self.access_key:
            raise ValueError(
                "Porcupine access key not provided. "
                "Set PORCUPINE_ACCESS_KEY env var or pass to __init__."
            )
        
        # Pre-roll buffer for capturing speech onset (200-400ms before wake word)
        self.preroll_buffer = []
        self.preroll_capacity = 4  # ~400ms at 100ms chunks
        self.preroll_enabled = True
        
        # Cached interrupt detector (reuse to avoid re-initialization)
        self._porcupine_interrupt_detector = None
        self._paused = threading.Event()
        self._hard_stop = threading.Event()
        self._active_stream = None
        self._is_listening = threading.Event()
        
        self.logger.info("[InputTrigger.Porcupine] Initialized")
        self.logger.debug(f"  Access key: {self.access_key[:10]}...")
        self.logger.debug(f"  Pre-roll buffer capacity: {self.preroll_capacity} frames (~400ms)")
    
    def on_trigger(self, callback: Callable) -> None:
        """
        Listen for Porcupine wake word and invoke callback when detected.
        
        Implementation:
        1. Initialize Porcupine
        2. Start audio capture (default microphone)
        3. Feed frames to Porcupine continuously
        4. When wake word detected: invoke callback()
        5. Exit (blocking call returns)
        
        Args:
            callback: Function to call when wake word detected.
                     Signature: callback() → None
        
        Raises:
            ImportError: If Porcupine not installed
            Exception: If audio capture or Porcupine fails
        """
        try:
            import pvporcupine
            import sounddevice
        except ImportError as e:
            raise ImportError(
                f"Required package missing: {e}. "
                "Install with: pip install porcupine sounddevice"
            )
        
        if self._hard_stop.is_set():
            self.logger.info("[on_trigger] Hard stop active; skipping wake-word listen")
            return

        self.logger.info("[on_trigger] Initializing Porcupine...")
        self.preroll_buffer.clear()  # Clear pre-roll buffer on each trigger listen
        
        try:
            # Initialize Porcupine (wake word detection) with custom model
            porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=["porcupine"],  # Using built-in keyword as fallback
                keyword_paths=["porcupine_key/hey-argo_en_windows_v4_0_0.ppn"]  # Custom "argo" model
            )
            
            self.logger.info(f"[Porcupine] Initialized with custom wake word model: 'argo'")
            self.logger.info(f"[Porcupine] Frame length: {porcupine.frame_length}")
            self.logger.info(f"[Porcupine] Sample rate: {porcupine.sample_rate} Hz")
            
            # Start audio capture
            self.logger.info("[Audio] Starting capture from default microphone...")
            
            stream = None
            try:
                stream = sounddevice.InputStream(
                    samplerate=porcupine.sample_rate,
                    channels=1,
                    blocksize=porcupine.frame_length,
                    dtype='int16'
                )
                self._active_stream = stream
                stream.start()
                self.logger.info("[Audio] Listening for wake word 'picovoice'...")
                self._is_listening.set()
                
                # Listen until wake word detected
                while True:
                    if self._hard_stop.is_set():
                        self.logger.info("[InputTrigger.Porcupine] Hard stop requested; exiting listen loop")
                        break
                    if self._paused.is_set():
                        # Pause capture while TTS is speaking to avoid audio device contention
                        if stream.active:
                            try:
                                stream.stop()
                            except Exception:
                                pass
                        time.sleep(0.05)
                        continue
                    else:
                        if not stream.active:
                            try:
                                stream.start()
                            except Exception:
                                pass
                    frame, _ = stream.read(porcupine.frame_length)
                    
                    # Maintain pre-roll buffer (circular buffer of recent frames)
                    if self.preroll_enabled:
                        self.preroll_buffer.append(frame.copy())
                        if len(self.preroll_buffer) > self.preroll_capacity:
                            self.preroll_buffer.pop(0)  # Remove oldest frame
                    
                    # Process frame
                    keyword_index = porcupine.process(frame.squeeze())
                    
                    # Check if wake word detected
                    if keyword_index >= 0:
                        self.logger.info(f"[Wake Word] Detected! (keyword_index={keyword_index})")
                        
                        # Fire callback
                        self.logger.info("[Event] Invoking callback...")
                        callback()
                        self.logger.info("[Event] Callback complete")
                        
                        # Exit (blocking call returns)
                        break
            finally:
                # Ensure stream is properly closed
                if stream is not None:
                    try:
                        stream.stop()
                        stream.close()
                        self.logger.info("[Audio] Stream closed successfully")
                    except Exception as e:
                        self.logger.warning(f"[Audio] Error closing stream: {e}")
                self._active_stream = None
                self._is_listening.clear()
                
                # CRITICAL: Delete Porcupine instance to release audio device
                # Without this, the audio device remains locked for subsequent on_trigger() calls
                try:
                    porcupine.delete()
                    self.logger.debug("[Porcupine] Deleted successfully")
                except Exception as e:
                    self.logger.warning(f"[Porcupine] Error deleting: {e}")
        
        except Exception as e:
            self.logger.error(f"[on_trigger] Failed: {e}")
            raise

    def pause(self) -> None:
        """Pause wake-word detection (hard half-duplex gate)."""
        self._paused.set()
        self.logger.debug("[InputTrigger.Porcupine] Paused")

    def resume(self) -> None:
        """Resume wake-word detection."""
        self._paused.clear()
        self.logger.debug("[InputTrigger.Porcupine] Resumed")

    def hard_stop(self) -> None:
        """Hard-stop wake-word detection and close input stream."""
        self._hard_stop.set()
        self._paused.set()
        if self._active_stream is not None:
            try:
                if hasattr(self._active_stream, "abort"):
                    self._active_stream.abort()
                if self._active_stream.active:
                    self._active_stream.stop()
            except Exception:
                pass
            try:
                self._active_stream.close()
            except Exception:
                pass
        self.logger.info("[InputTrigger.Porcupine] Hard stop")

    def hard_resume(self) -> None:
        """Clear hard-stop and allow wake-word detection again."""
        self._hard_stop.clear()
        self._paused.clear()
        self.logger.info("[InputTrigger.Porcupine] Hard resume")

    def is_listening(self) -> bool:
        """Return True if wake-word loop is active."""
        return self._is_listening.is_set()

    def is_stream_active(self) -> bool:
        """Return True if the input stream is active."""
        return self._active_stream is not None and self._active_stream.active
    
    def get_preroll_buffer(self):
        """
        Get and clear the pre-roll buffer (speech onset audio before wake word).
        
        Returns:
            List of audio frames captured before wake word (empty if disabled/empty)
        """
        buffer = self.preroll_buffer.copy()
        self.preroll_buffer.clear()
        return buffer
    
    def _check_for_interrupt(self) -> bool:
        """
        Quick non-blocking check for interrupt (voice activity or wake word).
        
        Used by Coordinator during TTS playback to detect user interruption.
        Performs a single frame check without blocking.
        
        IMPORTANT: Reuses cached Porcupine instance (no new initialization per call).
        
        Returns:
            True if voice activity detected (interrupt), False otherwise
        """
        if self._hard_stop.is_set() or self._paused.is_set():
            return False
        import os
        import sounddevice as sd
        import numpy as np
        
        try:
            import pvporcupine
            
            # Initialize Porcupine once and cache it (reuse to avoid re-initialization overhead)
            access_key = os.getenv("PORCUPINE_ACCESS_KEY")
            if not access_key:
                return False
            
            # Cache Porcupine instance to avoid repeated initialization
            if self._porcupine_interrupt_detector is None:
                self._porcupine_interrupt_detector = pvporcupine.create(
                    access_key=access_key,
                    keywords=['picovoice']
                )
            
            porcupine = self._porcupine_interrupt_detector
            
            # Read one frame from microphone
            frame = sd.rec(
                porcupine.frame_length,
                samplerate=16000,
                channels=1,
                dtype='int16',
                blocking=True
            )
            
            # Check if this frame has significant audio (voice activity detection)
            # Simple RMS-based voice activity detection
            rms = np.sqrt(np.mean(frame.astype(float) ** 2))
            
            # If audio level above threshold, consider it an interrupt
            if rms > 200:  # Voice activity threshold
                self.logger.debug("[Interrupt] Voice activity detected")
                return True
            
            # Also check for wake word
            keyword_index = porcupine.process(frame.squeeze())
            if keyword_index >= 0:
                self.logger.info("[Interrupt] Wake word detected during playback!")
                return True
            
            porcupine.delete()
            return False
        
        except Exception as e:
            # Silently return False on error (don't interrupt on detection failure)
            return False