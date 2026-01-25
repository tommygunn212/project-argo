"""
OUTPUT SINK ABSTRACTION (Phase 7A-0 PART 1)

Unified output routing for text and audio. Deterministic, non-blocking, instantly stoppable.

Core semantics:
- send(text: str) → route text to output (print, response streaming, or audio)
- stop() → halt any active audio playback (idempotent, instant, no fade)

Design principles:
- Control first (deterministic behavior)
- Responsiveness second (no blocking)
- Simplicity third (single voice, single output format)
- No personalities, emotions, or SSML

Configuration:
- VOICE_ENABLED (env var): Enable/disable audio output entirely
- PIPER_ENABLED (env var): Enable/disable Piper TTS specifically

Behavior when disabled:
- If VOICE_ENABLED=false: audio output skipped, text still sent
- If PIPER_ENABLED=false: text output only (fallback behavior)
- No silent placeholders, no UI changes, no state machine

Hard stops:
- stop() must halt audio instantly (no fade-out, no tail audio)
- stop() must be idempotent (can call multiple times safely)
- stop() must not raise exceptions even if audio not playing
- Event loop must remain responsive during and after stop
"""

# AUDIO PATH STABLE
# Verified working. Do not modify without reproduced issue + logs.

import os
import asyncio
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Optional, Callable
import queue
import threading
import re

from core.policy import TTS_TIMEOUT_SECONDS, TTS_WATCHDOG_SECONDS
from core.watchdog import Watchdog


# ============================================================================
# CONFIGURATION FLAGS
# ============================================================================

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() == "true"
"""Enable/disable audio output entirely."""

PIPER_ENABLED = os.getenv("PIPER_ENABLED", "false").lower() == "true"
"""Enable/disable Piper TTS (requires VOICE_ENABLED=true)."""

VOICE_PROFILE = os.getenv("VOICE_PROFILE", "lessac").lower()
"""Voice profile selection (Phase 7D): 'lessac' (default) or 'allen'. Data/config only."""

PIPER_PROFILING = os.getenv("PIPER_PROFILING", "false").lower() == "true"
"""Enable timing probes for Piper audio operations (gated, non-blocking)."""


# ============================================================================
# OUTPUT SINK INTERFACE (PART 1)
# ============================================================================

class OutputSink(ABC):
    """
    Abstract base class for output routing.
    
    Implementations must provide:
    - send(text: str) → route text to output
    - stop() → halt any active output (idempotent, instant)
    
    Implementations should be:
    - Non-blocking (use async/await, not time.sleep)
    - Event loop safe (no competing event loops)
    - Cancellation-safe (handle asyncio.CancelledError gracefully)
    """
    
    @abstractmethod
    async def send(self, text: str) -> None:
        """
        Send text to output.
        
        Routing decision:
        - If VOICE_ENABLED=true and PIPER_ENABLED=true: text → audio
        - Otherwise: text → print/response streaming (default)
        
        Non-blocking: must use asyncio.sleep only, never time.sleep.
        
        Args:
            text: Text content to send
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """
        Stop any active audio playback (idempotent, instant).
        
        Behavior:
        - If audio playing: halt immediately (no fade, no tail)
        - If audio not playing: no-op (idempotent)
        - If called multiple times: safe to call repeatedly
        - Never raises exceptions
        
        Must be instant (< 50ms) and async-safe.
        """
        pass


# ============================================================================
# DEFAULT IMPLEMENTATION: SILENT SINK (PART 1 STUB)
# ============================================================================

class SilentOutputSink(OutputSink):
    """
    Default stub implementation.
    
    - send(text) → no-op (text discarded)
    - stop() → no-op
    - speak(text) → no-op (intentionally silent)
    
    This is the default until Piper is integrated (PART 2).
    Text output is handled separately in argo.py and app.py.
    """
    
    async def send(self, text: str) -> None:
        """Send text → no-op in stub."""
        pass
    
    async def stop(self) -> None:
        """Stop → no-op in stub."""
        pass
    
    def speak(self, text: str) -> None:
        """Speak text → no-op (intentionally silent)."""
        pass


# ============================================================================
# VOICE PROFILE MAPPING (Phase 7D)
# ============================================================================

def _get_voice_model_path(profile: str = None) -> str:
    """
    Map voice profile to voice model ONNX file path.
    
    Args:
        profile: Voice profile name ('lessac'). Defaults to VOICE_PROFILE env var.
        
    Returns:
        Full path to voice model ONNX file. Currently only Lessac is supported.
        
    Voice Profile Mapping:
        - 'lessac' (default): en_US-lessac-medium.onnx (American male, stable, working)
        - Note: en_GB-alan-medium.onnx produces zero bytes (incompatible with current Piper build)
    
    Note: This is data/config only. No logic changes to OutputSink.
    """
    if profile is None:
        profile = VOICE_PROFILE
    
    profile = profile.lower().strip()
    
    # Voice profile → ONNX file mapping
    # Only Lessac is currently working; Allen disabled due to zero-byte output
    voice_models = {
        "lessac": "audio/piper/voices/en_US-lessac-medium.onnx",
    }
    
    # Fallback to Lessac for any unknown profile (including 'allen')
    if profile not in voice_models:
        if PIPER_PROFILING:
            print(f"[DEBUG] Voice profile '{profile}' not available, falling back to 'lessac'", file=sys.stderr)
        return voice_models["lessac"]
    
    return voice_models[profile]


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_output_sink: Optional[OutputSink] = None
_audio_disabled_warning_issued = False
"""Global output sink instance (lazy initialization)."""

def get_output_sink() -> OutputSink:
    global _output_sink, _audio_disabled_warning_issued
    if _output_sink is None:
        if VOICE_ENABLED and PIPER_ENABLED:
            try:
                _output_sink = PiperOutputSink()
            except Exception as e:
                print(f"⚠ Failed to initialize PiperOutputSink: {e}", file=sys.stderr)
                _output_sink = SilentOutputSink()
        else:
            if not _audio_disabled_warning_issued:
                print("\n[WARNING] Audio output is disabled by environment flags. ARGO will respond silently.\nTo enable voice output, set VOICE_ENABLED=true and PIPER_ENABLED=true\n", file=sys.stderr)
                _audio_disabled_warning_issued = True
            _output_sink = SilentOutputSink()
    return _output_sink

def set_output_sink(sink: OutputSink) -> None:
    """
    Replace the global OutputSink (used in PART 2).
    
    Args:
        sink: New OutputSink implementation
    """
    global _output_sink
    _output_sink = sink


# ============================================================================
# PIPER IMPLEMENTATION (PART 2: INTEGRATED)
# ============================================================================

class PiperOutputSink(OutputSink):
    """
    Piper TTS integration using producer-consumer queue pattern.
    
    Fixes asyncio RuntimeError by using threading instead of asyncio.
    - Producer (main/LLM thread): Generates sentences, queues them
    - Consumer (worker thread): Pulls from queue, runs Piper subprocess
    - Decoupled: LLM doesn't wait for TTS, TTS doesn't block LLM
    
    Behavior:
    - send(text) → queue sentence immediately (non-blocking)
    - speak(text) → same as send() (sync interface)
    - stop() → graceful shutdown with poison pill
    
    Configuration:
    - VOICE_ENABLED must be true (checked in caller)
    - PIPER_ENABLED must be true (checked in caller)
    - PIPER_PATH: path to piper.exe (from .env)
    - PIPER_VOICE: path to voice model (from .env)
    """
    
    def __init__(self):
        """
        Initialize Piper output sink with queue and worker thread.
        
        Reads configuration from .env:
        - PIPER_PATH: path to piper executable
        - VOICE_PROFILE: voice profile selection ('lessac' or 'allen')
        - PIPER_VOICE: path to voice model file (can be overridden)
        
        Starts background worker thread to consume from queue.
        
        Raises ValueError if Piper or voice model not found.
        """
        if not VOICE_ENABLED or not PIPER_ENABLED:
            raise RuntimeError("PiperOutputSink cannot be initialized: VOICE_ENABLED and PIPER_ENABLED must both be true.")
        self.piper_path = os.getenv("PIPER_PATH", "audio/piper/piper/piper.exe")
        
        # Get voice model path based on VOICE_PROFILE
        # Priority: PIPER_VOICE env var > VOICE_PROFILE setting > default (lessac)
        if os.getenv("PIPER_VOICE"):
            self.voice_path = os.getenv("PIPER_VOICE")
        else:
            self.voice_path = _get_voice_model_path(VOICE_PROFILE)
        
        self._profiling_enabled = PIPER_PROFILING
        
        # Log voice selection for diagnostics
        if self._profiling_enabled:
            print(f"[DEBUG] PiperOutputSink: voice_path={self.voice_path}", file=sys.stderr)
        
        # Validate Piper binary exists
        if not os.path.exists(self.piper_path):
            raise ValueError(f"Piper binary not found: {self.piper_path}")
        
        # Validate voice model exists (warning only if missing, for testing flexibility)
        if not os.path.exists(self.voice_path):
            if os.getenv("SKIP_VOICE_VALIDATION") != "true":
                raise ValueError(f"Voice model not found: {self.voice_path}")
        
        # Initialize producer-consumer queue
        self.text_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._piper_process: Optional[subprocess.Popen] = None
        self._playback_lock = threading.Lock()
        self._is_playing = False
        self._on_sentence_dequeued: Optional[Callable[[], None]] = None
        self._on_idle: Optional[Callable[[], None]] = None
        self._on_playback_start: Optional[Callable[[], None]] = None
        self._on_playback_complete: Optional[Callable[[], None]] = None
        self._pending_text: str = ""
        
        # Start background worker thread (daemon so it stops when main thread exits)
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        
        if self._profiling_enabled:
            print(f"[DEBUG] PiperOutputSink: Worker thread started", file=sys.stderr)
    
    def _worker(self):
        """
        Background worker thread: consume sentences from queue and play via Piper.
        
        Runs in dedicated thread (not main, not event loop).
        Loops until poison pill (None) received in queue.
        """
        import time

        while True:
            try:
                # Get next item from queue (blocking)
                import time
                item = self.text_queue.get(timeout=0.5)
                
                # Poison pill: stop signal
                if item is None:
                    if self._profiling_enabled:
                        print(f"[DEBUG] PiperOutputSink: Worker thread received poison pill, exiting", file=sys.stderr)
                    break
                
                # Notify dequeue (hard half-duplex gate)
                if self._on_sentence_dequeued:
                    try:
                        self._on_sentence_dequeued()
                    except Exception:
                        pass

                # Process sentence
                self._set_playing(True)
                try:
                    self._play_sentence(item)
                finally:
                    self._set_playing(False)

                # Resume trigger only when queue empty and playback idle
                if self.text_queue.empty() and self.is_idle():
                    if self._on_playback_complete:
                        try:
                            self._on_playback_complete()
                        except Exception:
                            pass
                    if self._on_idle:
                        try:
                            self._on_idle()
                        except Exception:
                            pass
                
            except queue.Empty:
                # Timeout on get() - check if we should stop
                if self._stop_event.is_set():
                    break
                continue
            except Exception as e:
                print(f"[AUDIO_ERROR] Worker thread error: {type(e).__name__}: {e}", file=sys.stderr)
                if self._profiling_enabled:
                    import traceback
                    traceback.print_exc()
    
    def _play_sentence(self, sentence: str) -> None:
        """Play a sentence via Piper subprocess with adaptive pacing."""
        import time
        
        if not sentence or not sentence.strip():
            return
        
        time_start = time.time()
        piper_process = None
        audio_duration = 0
        
        try:
            if self._profiling_enabled:
                print(f"[PIPER_PROFILING] play_sentence_start: {sentence[:50]}...")
            
            # Start Piper subprocess
            with Watchdog("TTS", TTS_WATCHDOG_SECONDS) as wd:
                piper_process = subprocess.Popen(
                    [
                        self.piper_path,
                        "--model",
                        self.voice_path,
                        "--output-raw",
                        "--length_scale",
                        "0.85",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                
                # Send text to stdin
                piper_process.stdin.write(sentence.encode("utf-8"))
                piper_process.stdin.close()
                
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] piper process started, text sent")
                
                # Read audio and play (BLOCKING)
                audio_duration = self._stream_and_play(piper_process)
                
                # Wait for process to finish
                piper_process.wait(timeout=TTS_TIMEOUT_SECONDS)
                
                if wd.triggered:
                    print(f"[WATCHDOG] TTS exceeded watchdog threshold", file=sys.stderr)
        
        except subprocess.TimeoutExpired:
            print(f"[AUDIO_ERROR] Piper subprocess timeout", file=sys.stderr)
            if piper_process:
                piper_process.kill()
        except Exception as e:
            print(f"[AUDIO_ERROR] Play sentence error: {type(e).__name__}: {e}", file=sys.stderr)
            if piper_process:
                try:
                    piper_process.terminate()
                except:
                    pass
        finally:
            if piper_process:
                try:
                    piper_process.terminate()
                except Exception:
                    pass
            self._piper_process = None
            
            # Log total duration
            if self._profiling_enabled:
                time_end = time.time()
                duration_ms = (time_end - time_start) * 1000
                print(f"[PIPER_PROFILING] play_sentence_complete: {duration_ms:.1f}ms")
            
            # Adaptive pacing: minimal gap between sentences (max 50ms)
            if audio_duration:
                delay = min(audio_duration * 0.01, 0.05)
                time.sleep(delay)
    
    def _stream_and_play(self, process: subprocess.Popen):
        """
        Stream audio from Piper subprocess and play via sounddevice.
        
        Reads raw PCM (int16, 22050 Hz mono) from Piper stdout.
        Plays audio in real-time as data arrives.
        
        Args:
            process: Piper subprocess with stdout=PIPE
        """
        try:
            import sounddevice
            import numpy as np
            import time
            import threading
            import queue
        except ImportError:
            if self._profiling_enabled:
                print("[DEBUG] sounddevice/numpy not installed; audio playback disabled", file=sys.stderr)
            return 0
        
        try:
            SAMPLE_RATE = 22050
            SAMPLE_WIDTH = 2  # int16 = 2 bytes
            BLOCK_FRAMES = 2048
            CHUNK_BYTES = BLOCK_FRAMES * SAMPLE_WIDTH
            MIN_PREROLL_FRAMES = int(SAMPLE_RATE * 0.1)  # 100ms

            audio_queue = queue.Queue(maxsize=50)
            eof = object()
            producer_done = threading.Event()
            queued_frames = 0
            queued_lock = threading.Lock()
            total_frames = 0

            def producer():
                nonlocal queued_frames, total_frames
                while True:
                    data = process.stdout.read(CHUNK_BYTES)
                    if not data:
                        break
                    audio_queue.put(data)
                    frames = len(data) // SAMPLE_WIDTH
                    total_frames += frames
                    with queued_lock:
                        queued_frames += frames
                producer_done.set()
                audio_queue.put(eof)

            def callback(outdata, frames, time_info, status):
                nonlocal queued_frames
                if status and self._profiling_enabled:
                    print(f"[AUDIO_STATUS] {status}", file=sys.stderr)
                out = np.zeros(frames, dtype=np.float32)
                filled = 0
                while filled < frames:
                    try:
                        item = audio_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is eof:
                        raise sounddevice.CallbackStop()
                    data = np.frombuffer(item, dtype=np.int16).astype(np.float32) / 32768.0
                    take = min(frames - filled, len(data))
                    out[filled:filled+take] = data[:take]
                    filled += take
                    remaining = data[take:]
                    if remaining.size > 0:
                        # Put remainder back to front by re-queueing
                        audio_queue.queue.appendleft(remaining.tobytes())
                    with queued_lock:
                        queued_frames -= take
                outdata[:] = out.reshape(-1, 1)

            # Explicit device handshake before playback
            sounddevice.stop()
            time.sleep(0.05)

            producer_thread = threading.Thread(target=producer, daemon=True)
            producer_thread.start()

            # Pre-roll: wait until buffered frames reach threshold or producer finishes
            while True:
                with queued_lock:
                    if queued_frames >= MIN_PREROLL_FRAMES:
                        break
                if producer_done.is_set():
                    break
                time.sleep(0.01)

            if self._profiling_enabled and total_frames > 0:
                duration_seconds = total_frames / SAMPLE_RATE
                print(f"[PIPER_PROFILING] playback_start: {duration_seconds:.2f}s")

            if self._on_playback_start:
                try:
                    self._on_playback_start()
                except Exception:
                    pass

            with sounddevice.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='float32',
                blocksize=BLOCK_FRAMES,
                callback=callback,
            ):
                while not producer_done.is_set() or not audio_queue.empty():
                    time.sleep(0.01)

            if self._profiling_enabled:
                print(f"[PIPER_PROFILING] playback_complete")

            # Hardware drain
            sounddevice.wait()
            time.sleep(0.5)

            return total_frames / SAMPLE_RATE if total_frames else 0
        
        except Exception as e:
            print(f"[AUDIO_ERROR] Stream and play error: {type(e).__name__}: {e}", file=sys.stderr)
            if self._profiling_enabled:
                import traceback
                traceback.print_exc()
            return 0
    
    def send(self, text: str) -> None:
        """
        Send text for audio playback (non-blocking, queue-based).
        
        Splits text into sentences and queues them.
        Worker thread consumes and plays sentences.
        
        Args:
            text: Text to synthesize and play
        """
        if not text or not text.strip():
            return
        
        # CRITICAL: Remove newlines before splitting
        text = text.replace('\n', ' ')
        text = text.replace('\r', ' ')
        text = text.replace('  ', ' ')  # Remove double spaces
        
        # Split text into sentences using regex
        # Split on . ! ? followed by space or end-of-string
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                # Queue for worker thread (non-blocking)
                self.text_queue.put(sentence)
                if self._profiling_enabled:
                    print(f"[DEBUG] Queued sentence: {sentence[:50]}...", file=sys.stderr)

    def set_playback_hooks(
        self,
        on_sentence_dequeued: Optional[Callable[[], None]] = None,
        on_idle: Optional[Callable[[], None]] = None,
        on_playback_start: Optional[Callable[[], None]] = None,
        on_playback_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        """Set playback hooks for strict half-duplex gating."""
        self._on_sentence_dequeued = on_sentence_dequeued
        self._on_idle = on_idle
        self._on_playback_start = on_playback_start
        self._on_playback_complete = on_playback_complete

    def _set_playing(self, is_playing: bool) -> None:
        with self._playback_lock:
            self._is_playing = is_playing

    def is_idle(self) -> bool:
        """Return True if playback thread is idle (no active Piper/sounddevice work)."""
        with self._playback_lock:
            return not self._is_playing
    
    def speak(self, text: str) -> None:
        """
        Speak text synchronously (wrapper around send).
        
        Used by Coordinator which uses sync interface.
        Queues text for background playback.
        
        Args:
            text: Text to synthesize and play
        """
        self.send(text)
    
    def stop_interrupt(self) -> None:
        """
        Stop TTS immediately (synchronous barge-in interrupt).
        
        Used by Coordinator when user says wake word during TTS.
        This is the SYNCHRONOUS version for coordinator thread.
        
        Strategy (brutal but effective):
        - Clear all pending sentences from queue
        - Kill Piper subprocess immediately
        - Return instantly (no waiting)
        """
        self._stop_event.set()
        
        # Clear queue (discard pending sentences)
        try:
            while True:
                self.text_queue.get_nowait()
        except:
            pass
        
        # Kill Piper immediately
        if self._piper_process:
            try:
                self._piper_process.kill()
            except:
                pass
            finally:
                self._piper_process = None
        
        # Signal not playing
        self._is_playing = False
    
    async def stop(self) -> None:
        """
        Stop audio playback IMMEDIATELY (hard interrupt, no grace period).
        
        Used for barge-in interrupt: user says wake word while Argo is speaking.
        
        Strategy:
        1. Signal stop event to worker thread
        2. Clear text queue (discard pending sentences)
        3. Kill Piper process immediately (brutal but effective)
        4. Wait briefly for worker to notice
        
        This is NOT a graceful shutdown - it's an interrupt.
        """
        self._stop_event.set()
        
        # CRITICAL: Clear all pending sentences from queue
        # This prevents worker from queuing more playback
        try:
            while True:
                self.text_queue.get_nowait()
        except:
            pass  # Queue is empty
        
        # BRUTAL: Kill Piper process immediately (no timeout, no mercy)
        if self._piper_process:
            try:
                # First try terminate
                self._piper_process.terminate()
                try:
                    self._piper_process.wait(timeout=0.1)  # Very short grace period
                except:
                    # Force kill if terminate didn't work
                    self._piper_process.kill()
                    self._piper_process.wait(timeout=0.1)
            except:
                pass  # Already dead
            finally:
                self._piper_process = None
        
        # Stop music if playing
        try:
            from core.music_player import get_music_player
            music_player = get_music_player()
            music_player.stop()
        except Exception:
            pass
        
        # Signal coordinator that we're no longer speaking
        self._is_playing = False


# ============================================================================
# EDGE-TTS IMPLEMENTATION (TASK 18: CLOUD TTS)
# ============================================================================

class EdgeTTSOutputSink(OutputSink):
    """
    Edge-TTS output sink: cloud text-to-speech with blocking playback.
    
    Uses Microsoft Edge-TTS API (via edge-tts package).
    Synthesizes speech and plays to default speaker.
    All operations block until complete (no async, no background threads).
    
    Suitable for half-duplex operation (blocks until audio playback finishes).
    
    Args:
        voice: Microsoft neural voice name (default: "en-US-AriaNeural")
        rate: Speech rate adjustment -50 to +50 (default: 0)
        pitch: Pitch adjustment -50 to +50 (default: 0)
    """
    
    # Hard-coded audio parameters (no auto-detect)
    SAMPLE_RATE = 48000  # Hz
    CHANNELS = 2  # Stereo
    
    # Step 1: Lock audio backend to WASAPI (shared mode, stable for M-Audio)
    @staticmethod
    def _init_wasapi():
        """Initialize WASAPI backend for stable M-Audio playback."""
        try:
            import sounddevice as sd
            # Try to set WASAPI as backend
            try:
                sd.default.hostapi = 'Windows WASAPI'
                print(f"[Audio] WASAPI backend initialized", file=sys.stderr)
            except (AttributeError, TypeError):
                # Fallback: enumerate hostapis and use WASAPI if available
                hostapis = sd.query_hostapis()
                for api in hostapis:
                    if 'WASAPI' in api.get('name', ''):
                        sd.default.hostapi = api['index']
                        print(f"[Audio] WASAPI backend set (index {api['index']})", file=sys.stderr)
                        return
                print(f"[Audio] WASAPI not available, using default backend", file=sys.stderr)
        except Exception as e:
            print(f"[Audio] Warning: Backend initialization: {e}", file=sys.stderr)
    
    def __init__(self, voice: str = "en-US-AriaNeural", rate: int = 0, pitch: int = 0):
        """
        Initialize Edge-TTS output sink.
        
        Args:
            voice: Microsoft neural voice (e.g., "en-US-AriaNeural")
            rate: Speech rate (-50 to +50)
            pitch: Pitch (-50 to +50)
        """
        self.voice = voice
        # CRITICAL: Edge-TTS requires rate/pitch/volume as strings with units (%-% or Hz)
        # Hard-coded for now to bypass Edge-TTS parameter validator bug
        self.rate = "+0%"      # MUST be string ending in %
        self.pitch = "+0Hz"    # MUST be string ending in Hz
        self.volume = "+0%"    # MUST be string ending in %
        self._stop_requested = False
        self._audio_device = None
        self._device_sample_rate = 48000  # Will be detected at init
        
        # Initialize WASAPI backend
        self._init_wasapi()
        
        # Initialize audio device at startup
        self._init_audio_device()
    
    def _init_audio_device(self) -> None:
        """
        Use system default audio output device.
        
        Detects device sample rate and stores it for resampling.
        """
        try:
            import sounddevice as sd
            
            # Use None to let sounddevice pick the system default
            self._audio_device = None
            
            # Step 2: Detect the actual output device sample rate
            device_info = sd.query_devices(self._audio_device, 'output')
            self._device_sample_rate = int(device_info['default_samplerate'])
            
            print(f"[Audio] Output device: {device_info['name']} @ {self._device_sample_rate}Hz", file=sys.stderr)
            
        except Exception as e:
            print(f"[Audio] Device detection failed: {e}", file=sys.stderr)
            self._audio_device = None
            self._device_sample_rate = 48000  # Fallback
    
    def speak(self, text: str) -> None:
        """
        Speak text synchronously (blocking until playback complete).
        
        1. Synthesize audio using Edge-TTS (cloud API)
        2. Save WAV file to audio/debug/ for verification
        3. Play to locked output device at 48kHz
        4. Block until playback finishes
        
        Args:
            text: Text to synthesize and play
        """
        if not text or not text.strip():
            return
        
        self._stop_requested = False
        
        try:
            import edge_tts
            import sounddevice
            import numpy as np
            import wave
            import os
            
            # Step 1: Synthesize audio from text
            # CRITICAL: rate/pitch/volume MUST be strings with unit suffixes (% or Hz)
            # This bypasses known Edge-TTS parameter validator bug that corrupts audio
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate="+0%",     # MUST be string ending in %
                pitch="+0Hz",   # MUST be string ending in Hz
                volume="+0%"    # MUST be string ending in %
            )
            
            # Collect audio chunks
            audio_chunks = []
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def collect_audio():
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_chunks.append(chunk["data"])
                    if self._stop_requested:
                        break
            
            try:
                loop.run_until_complete(collect_audio())
            finally:
                loop.close()
            
            if not audio_chunks or self._stop_requested:
                return
            
            # Combine audio chunks
            audio_data = b''.join(audio_chunks)
            
            # Step 2: Save WAV file to debug directory
            debug_dir = "audio/debug"
            os.makedirs(debug_dir, exist_ok=True)
            debug_file = os.path.join(debug_dir, "edge_tts_test.wav")
            
            try:
                with wave.open(debug_file, 'wb') as wav_file:
                    # Edge-TTS outputs 48kHz 16-bit mono audio
                    wav_file.setnchannels(1)  # Mono from Edge-TTS
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.SAMPLE_RATE)
                    wav_file.writeframes(audio_data)
                print(f"[Audio] Debug WAV saved: {debug_file}", file=sys.stderr)
            except Exception as e:
                print(f"[Audio] Failed to save debug WAV: {e}", file=sys.stderr)
            
            # Step 2b: Read WAV header to get actual sample rate (fix playback clock)
            # Edge-TTS might output at different rate than expected
            actual_sample_rate = self.SAMPLE_RATE
            try:
                with wave.open(debug_file, 'rb') as wav_file:
                    actual_sample_rate = wav_file.getframerate()
                    actual_channels = wav_file.getnchannels()
                    actual_width = wav_file.getsampwidth()
                    actual_frames = wav_file.getnframes()
                    print(f"[Audio] WAV Header: {actual_sample_rate}Hz, {actual_channels}ch, {actual_width}bytes/sample, {actual_frames} frames", file=sys.stderr)
            except Exception as e:
                print(f"[Audio] Failed to read WAV header: {e}", file=sys.stderr)
            
            # Step 3: Convert audio to numpy array for playback
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            duration = len(audio_array) / actual_sample_rate
            
            # Step 3b: Add diagnostic logging for audio array quality
            print(f"[Audio] Array range: [{audio_array.min():.4f}, {audio_array.max():.4f}]", file=sys.stderr)
            print(f"[Audio] Array shape: {audio_array.shape}, dtype: {audio_array.dtype}", file=sys.stderr)
            print(f"[Audio] Non-zero samples: {np.count_nonzero(audio_array)}/{len(audio_array)}", file=sys.stderr)
            
            # Normalize and apply gain reduction to prevent clipping
            audio_max = np.max(np.abs(audio_array))
            if audio_max > 0:
                # Apply 0.8 gain to prevent clipping in int16 conversion
                audio_array = audio_array * (0.8 / audio_max)
                print(f"[Audio] Applied gain: 0.8x (normalized from peak {audio_max:.4f})", file=sys.stderr)
            
            # Step 3: Resample Edge-TTS audio to device clock
            # For simpleaudio, try native 48kHz first (let Windows handle it)
            print(f"[Audio] Native TTS rate: {actual_sample_rate}Hz, Device rate: {self._device_sample_rate}Hz", file=sys.stderr)
            
            # Try playing at native 48kHz - Windows may handle resampling in background
            # Only resample if vastly different (e.g., 16kHz, 22kHz, 96kHz)
            if actual_sample_rate < 40000 or actual_sample_rate > 50000:
                try:
                    from scipy.signal import resample
                    original_len = len(audio_array)
                    print(f"[Audio] Resampling {actual_sample_rate}Hz → {self._device_sample_rate}Hz", file=sys.stderr)
                    num_samples = int(len(audio_array) * self._device_sample_rate / actual_sample_rate)
                    audio_array = resample(audio_array, num_samples)
                    resampled_len = len(audio_array)
                    print(f"[Audio] Resampled: {original_len} frames → {resampled_len} frames", file=sys.stderr)
                    actual_sample_rate = self._device_sample_rate
                except Exception as e:
                    print(f"[Audio] Resampling failed: {e}, using native rate", file=sys.stderr)
            else:
                print(f"[Audio] Rate difference < 5%, playing at native {actual_sample_rate}Hz", file=sys.stderr)
            
            # Step 4: Log and play to locked output device (blocking)
            # Use actual sample rate from WAV header, not hard-coded constant
            print(f"[Audio] Playing Edge-TTS audio: duration={duration:.2f}s, samplerate={actual_sample_rate}", file=sys.stderr)
            
            # Pre-buffer audio to prevent underrun (minimal buffer)
            import time
            time.sleep(0.05)  # Minimal buffer for audio device
            
            # Step 4: Force correct playback parameters
            # Try using simpleaudio instead of sounddevice to avoid driver issues
            try:
                import simpleaudio as sa
                # Convert to int16 PCM for simpleaudio
                audio_int16 = (np.clip(audio_array, -1.0, 1.0) * 32767).astype(np.int16)
                
                print(f"[Audio] Playing with simpleaudio: {len(audio_int16)} samples @ {int(actual_sample_rate)}Hz, int16 codec", file=sys.stderr)
                
                # Play using simpleaudio (direct Windows audio, no resampling)
                playback = sa.play_buffer(
                    audio_int16,
                    num_channels=1,
                    bytes_per_sample=2,
                    sample_rate=int(actual_sample_rate)
                )
                playback.wait_done()
                print(f"[Audio] Playback complete (simpleaudio)", file=sys.stderr)
            except ImportError:
                # Fallback to sounddevice if simpleaudio not available
                print(f"[Audio] simpleaudio not available, using sounddevice", file=sys.stderr)
                import sounddevice as sd
                sd.play(
                    audio_array.astype(np.float32),
                    samplerate=int(actual_sample_rate),
                    device=self._audio_device,
                    blocking=True,
                    blocksize=2048
                )
                sd.wait()
                print(f"[Audio] Playback complete (sounddevice)", file=sys.stderr)
            except Exception as e:
                print(f"[Audio] Playback failed: {e}", file=sys.stderr)
            
            # Step 5: Ensure playback clock finishes before returning
            import time
            time.sleep(0.05)  # Minimal buffer for device
            print(f"[Audio] Playback complete", file=sys.stderr)
            
        except ImportError as e:
            print(f"[EdgeTTS_ERROR] Missing dependency: {e}", file=sys.stderr)
            print(f"[EdgeTTS_ERROR] Install with: pip install edge-tts sounddevice numpy", file=sys.stderr)
        except Exception as e:
            print(f"[EdgeTTS_ERROR] speak() failed: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
        
        # Minimal buffer: ensure playback finishes before process swaps to listening
        import time
        time.sleep(0.05)
    
    async def send(self, text: str) -> None:
        """
        Send text to output (async wrapper for interface compatibility).
        
        Calls speak() synchronously (blocking mode).
        
        Args:
            text: Text to synthesize and play
        """
        self.speak(text)
    
    async def stop(self) -> None:
        """
        Stop audio playback immediately (idempotent, instant).
        Also stops music playback if active.
        
        Behavior:
        - If playback running: halt immediately
        - If playback not running: no-op (idempotent)
        - Multiple calls: safe (idempotent)
        - Never raises exceptions
        """
        self._stop_requested = True
        try:
            import sounddevice
            sounddevice.stop()
        except Exception:
            pass  # Already stopped or not playing
        
        # Also stop music playback if active
        try:
            from core.music_player import get_music_player
            music_player = get_music_player()
            music_player.stop()
        except Exception:
            pass  # Music not playing or not enabled


def play_startup_announcement():
    """Play startup chime + voice announcement on successful initialization."""
    import random
    import numpy as np
    import sounddevice
    
    try:
        # === CHIME (200-300ms at 1000Hz) ===
        sample_rate = 22050
        duration = 0.25  # 250ms
        t = np.linspace(0, duration, int(sample_rate * duration))
        frequency = 1000  # Hz
        chime = 0.3 * np.sin(2 * np.pi * frequency * t)
        
        # Fade out at the end to avoid clicks
        fade_samples = int(0.05 * sample_rate)
        chime[-fade_samples:] *= np.linspace(1, 0, fade_samples)
        
        sounddevice.play(chime, samplerate=sample_rate)
        sounddevice.wait()
        
        # === VOICE ANNOUNCEMENT ===
        phrases = ["Ready.", "Voice system online."]
        phrase = random.choice(phrases)
        
        # Use the default output sink to speak (use speak() for sync)
        sink = get_output_sink()
        sink.speak(phrase)        
    except Exception as e:
        # Silently fail on startup announcement (don't crash the system)
        pass