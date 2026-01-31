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

# ============================================================================
# 1) IMPORTS
# ============================================================================
import os
import asyncio
import subprocess
import sys
import shutil
from abc import ABC, abstractmethod
from typing import Optional, Callable
import queue
import threading
import re
from datetime import datetime

from core.policy import TTS_TIMEOUT_SECONDS, TTS_WATCHDOG_SECONDS
from core.audio_owner import get_audio_owner
from core.watchdog import Watchdog


# ============================================================================
# 2) INSTRUMENTATION: MILLISECOND-PRECISION EVENT LOGGING
# ============================================================================

def log_event(message: str) -> None:
    """Log event with millisecond-precision timestamp (same as coordinator)."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {message}")  # Use print for immediate stderr output


# ============================================================================
# 3) CONFIGURATION FLAGS
# ============================================================================

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() == "true"
"""Enable/disable audio output entirely."""

PIPER_ENABLED = os.getenv("PIPER_ENABLED", "false").lower() == "true"
"""Enable/disable Piper TTS (requires VOICE_ENABLED=true)."""

VOICE_PROFILE = os.getenv("VOICE_PROFILE", "lessac").lower()
"""Voice profile selection (Phase 7D): 'lessac' (default) or 'allen'. Data/config only."""

PIPER_PROFILING = os.getenv("PIPER_PROFILING", "false").lower() == "true"
"""Enable timing probes for Piper audio operations (gated, non-blocking)."""

FORCE_BLOCKING_TTS = os.getenv("FORCE_BLOCKING_TTS", "false").lower() == "true"
"""Force blocking TTS (wait for all audio to play before returning). For testing only."""


# ============================================================================
# 4) OUTPUT SINK INTERFACE (PART 1)
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
        explicit_sink = os.getenv("OUTPUT_SINK", "").strip().lower()
        if not VOICE_ENABLED or not PIPER_ENABLED or explicit_sink != "piper":
            if not _audio_disabled_warning_issued:
                print("\n[WARNING] Audio output is disabled by environment flags. ARGO will respond silently.\nTo enable voice output, set VOICE_ENABLED=true and PIPER_ENABLED=true\n", file=sys.stderr)
                _audio_disabled_warning_issued = True
            _output_sink = SilentOutputSink()
        else:
            # Only initialize Piper when explicitly enabled
            try:
                _output_sink = PiperOutputSink()
            except Exception as e:
                print(f"⚠ Failed to initialize PiperOutputSink: {e}", file=sys.stderr)
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
    
    def __init__(self, piper_path: str | None = None, voice_path: str | None = None):
        """
        Initialize Piper output sink with queue and worker thread.
        
        Reads configuration from .env:
        - PIPER_PATH: path to piper executable
        - VOICE_PROFILE: voice profile selection ('lessac' or 'allen')
        - PIPER_VOICE: path to voice model file (can be overridden)
        
        Starts background worker thread to consume from queue.
        
        Raises ValueError if Piper or voice model not found.
        """
        if (not VOICE_ENABLED or not PIPER_ENABLED) and piper_path != "echo":
            raise RuntimeError("PiperOutputSink cannot be initialized: VOICE_ENABLED and PIPER_ENABLED must both be true.")
        self.piper_path = piper_path or os.getenv("PIPER_PATH", "audio/piper/piper/piper.exe")
        
        # Get voice model path based on VOICE_PROFILE
        # Priority: PIPER_VOICE env var > VOICE_PROFILE setting > default (lessac)
        if voice_path:
            self.voice_path = voice_path
        elif os.getenv("PIPER_VOICE"):
            self.voice_path = os.getenv("PIPER_VOICE")
        else:
            self.voice_path = _get_voice_model_path(VOICE_PROFILE)
        
        self._profiling_enabled = PIPER_PROFILING
        
        # Log voice selection for diagnostics
        if self._profiling_enabled:
            print(f"[DEBUG] PiperOutputSink: voice_path={self.voice_path}", file=sys.stderr)
        
        # Validate Piper binary exists
        if self.piper_path != "echo" and not os.path.exists(self.piper_path) and not shutil.which(self.piper_path):
            raise ValueError(f"Piper binary not found: {self.piper_path}")
        
        # Validate voice model exists (warning only if missing, for testing flexibility)
        if self.piper_path != "echo" and not os.path.exists(self.voice_path):
            if os.getenv("SKIP_VOICE_VALIDATION") != "true":
                raise ValueError(f"Voice model not found: {self.voice_path}")
        
        # Initialize producer-consumer queue
        self.text_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._piper_process: Optional[subprocess.Popen] = None
        self._playback_lock = threading.Lock()
        self._is_playing = False
        self._sd_stream = None
        self._on_sentence_dequeued: Optional[Callable[[], None]] = None
        self._on_idle: Optional[Callable[[], None]] = None
        self._on_playback_start: Optional[Callable[[], None]] = None
        self._on_playback_complete: Optional[Callable[[], None]] = None
        self._pending_text: str = ""
        self._playback_task = None
        
        # HARDENING STEP 2: Interaction ID for zombie callback filtering
        self._interaction_id: Optional[int] = None
        
        # Start background worker thread (daemon so it stops when main thread exits)
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        
        if self._profiling_enabled:
            print(f"[DEBUG] PiperOutputSink: Worker thread started", file=sys.stderr)

    def _safe_close_process_pipes(self, proc: subprocess.Popen) -> None:
        for pipe in (getattr(proc, "stdin", None), getattr(proc, "stdout", None), getattr(proc, "stderr", None)):
            try:
                if pipe:
                    pipe.close()
            except Exception:
                pass

    def _safe_kill_process(self, proc: subprocess.Popen) -> None:
        if not proc:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=0.1)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=0.1)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self._safe_close_process_pipes(proc)

    def _abort_audio_output(self) -> None:
        try:
            if self._sd_stream:
                try:
                    self._sd_stream.abort()
                except Exception:
                    pass
                try:
                    self._sd_stream.close()
                except Exception:
                    pass
        finally:
            self._sd_stream = None
        try:
            import sounddevice
            sounddevice.stop()
        except Exception:
            pass
    
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

                # HARDENING STEP 2: Validate interaction ID (prevent zombie callbacks)
                # If interaction_id was cleared by stop_interrupt(), skip playback
                if self._interaction_id is None:
                    continue

                # Process sentence
                self._set_playing(True)
                try:
                    # Audio ownership guard
                    audio_owner = get_audio_owner()
                    try:
                        audio_owner.acquire("TTS")
                        log_event("AUDIO_ACQUIRED owner=TTS")
                    except Exception:
                        log_event(f"AUDIO_CONTESTED owner={audio_owner.get_owner()} requested=TTS")
                        self._set_playing(False)
                        continue
                    self._play_sentence(item)
                finally:
                    try:
                        audio_owner.release("TTS")
                        log_event("AUDIO_RELEASED owner=TTS")
                    except Exception:
                        pass
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
                self._piper_process = piper_process
                
                # Send text to stdin
                try:
                    piper_process.stdin.write(sentence.encode("utf-8"))
                except (BrokenPipeError, ValueError, OSError):
                    return
                finally:
                    try:
                        piper_process.stdin.close()
                    except Exception:
                        pass
                
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
                self._safe_kill_process(piper_process)
        except Exception as e:
            print(f"[AUDIO_ERROR] Play sentence error: {type(e).__name__}: {e}", file=sys.stderr)
            if piper_process:
                self._safe_kill_process(piper_process)
        finally:
            if piper_process:
                self._safe_kill_process(piper_process)
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
                    try:
                        data = process.stdout.read(CHUNK_BYTES)
                    except (ValueError, OSError):
                        break
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
                if self._stop_event.is_set():
                    raise sounddevice.CallbackStop()
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
            ) as stream:
                self._sd_stream = stream
                while not producer_done.is_set() or not audio_queue.empty():
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.01)

            if self._profiling_enabled:
                print(f"[PIPER_PROFILING] playback_complete")

            # Hardware drain
            try:
                sounddevice.wait()
                time.sleep(0.05)
            except Exception:
                pass

            return total_frames / SAMPLE_RATE if total_frames else 0
        
        except Exception as e:
            print(f"[AUDIO_ERROR] Stream and play error: {type(e).__name__}: {e}", file=sys.stderr)
            if self._profiling_enabled:
                import traceback
                traceback.print_exc()
            return 0
        finally:
            self._sd_stream = None
    
    def _send_sync(self, text: str) -> None:
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

    async def send(self, text: str) -> bool:
        """
        Async send wrapper (non-blocking). Returns immediately.
        """
        try:
            loop = asyncio.get_running_loop()
            if self._playback_task and hasattr(self._playback_task, "cancel"):
                try:
                    self._playback_task.cancel()
                except Exception:
                    pass
            self._playback_task = loop.run_in_executor(None, self._send_sync, text)
        except RuntimeError:
            # No running loop; run sync
            self._send_sync(text)
        return True

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
    
    def speak(self, text: str, interaction_id: Optional[int] = None) -> None:
        """
        Speak text synchronously (wrapper around send).
        
        Used by Coordinator which uses sync interface.
        Queues text for background playback.
        
        When FORCE_BLOCKING_TTS=true (testing mode):
        - Waits for all sentences to be queued
        - Waits for worker thread to play all sentences
        - Returns only after audio is fully played
        
        When FORCE_BLOCKING_TTS=false (normal mode):
        - Queues sentences and returns immediately
        - Audio plays in background
        
        Args:
            text: Text to synthesize and play
            interaction_id: HARDENING STEP 2: Monotonic ID to prevent zombie callbacks
        """
        import time
        
        # HARDENING STEP 2: Store interaction ID (validates before playback)
        self._interaction_id = interaction_id
        # INSTRUMENTATION: Log TTS start
        log_event(f"TTS START (interaction_id={interaction_id})")
        self._send_sync(text)
        
        # FORCE_BLOCKING_TTS: Wait for all audio to be played (testing mode)
        if FORCE_BLOCKING_TTS:
            # Wait for queue to drain and worker thread to go idle
            timeout_seconds = 30.0  # Safety timeout
            start_time = time.time()
            
            while time.time() - start_time < timeout_seconds:
                # Check if queue is empty and worker is idle
                if self.text_queue.empty() and self.is_idle():
                    # Small sleep to ensure truly complete
                    time.sleep(0.1)
                    if self.text_queue.empty() and self.is_idle():
                        break
                
                # Yield to allow worker thread to run
                time.sleep(0.05)
            
            # If we hit timeout, log warning but don't fail
            if time.time() - start_time >= timeout_seconds:
                self.logger.warning(f"[TTS] FORCE_BLOCKING_TTS: Timeout waiting for playback to complete")

    
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
        # INSTRUMENTATION: Log TTS stop
        log_event(f"TTS STOP (interaction_id={self._interaction_id})")
        
        # HARDENING STEP 2: Invalidate interaction ID (prevents zombie callbacks)
        self._interaction_id = None
        
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
                self._safe_kill_process(self._piper_process)
            except Exception:
                pass
            finally:
                self._piper_process = None

        # Abort audio output immediately (sounddevice)
        self._abort_audio_output()
        try:
            if self._playback_task and hasattr(self._playback_task, "cancel"):
                self._playback_task.cancel()
        except Exception:
            pass
        
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
                self._safe_kill_process(self._piper_process)
            except Exception:
                pass
            finally:
                self._piper_process = None

        # Abort audio output immediately (sounddevice)
        self._abort_audio_output()
        try:
            if self._playback_task and hasattr(self._playback_task, "cancel"):
                self._playback_task.cancel()
        except Exception:
            pass
        
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

class EdgeTTSLiveKitOutputSink(SilentOutputSink):
    """Lightweight stub for LiveKit output (tests only)."""
    pass

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
            import numpy as np
            import sounddevice as sd
            import tempfile
            from pydub import AudioSegment

            # Synthesize to temp file
            with tempfile.TemporaryDirectory() as tmpdir:
                out_path = os.path.join(tmpdir, "edge_tts_output.mp3")
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=self.voice,
                    rate="+0%",
                    pitch="+0Hz",
                    volume="+0%",
                )

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(communicate.save(out_path))
                finally:
                    loop.close()

                if self._stop_requested:
                    return

                # Decode via pydub (ffmpeg) to get correct sample rate
                audio = AudioSegment.from_file(out_path)
                sample_rate = audio.frame_rate
                channels = audio.channels
                samples = np.array(audio.get_array_of_samples())
                if channels > 1:
                    samples = samples.reshape((-1, channels))
                samples = samples.astype(np.float32) / (1 << (8 * audio.sample_width - 1))

                # Normalize to prevent clipping
                peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                if peak > 0:
                    samples = samples * (0.8 / peak)

                sd.play(samples, samplerate=sample_rate, blocking=False)
                import time
                while True:
                    if self._stop_requested:
                        try:
                            sd.stop()
                        except Exception:
                            pass
                        break
                    try:
                        stream = sd.get_stream()
                        if not stream or not stream.active:
                            break
                    except Exception:
                        break
                    time.sleep(0.01)
                try:
                    sd.wait()
                except Exception:
                    pass
        except ImportError as e:
            print(f"[EdgeTTS_ERROR] Missing dependency: {e}", file=sys.stderr)
            print(f"[EdgeTTS_ERROR] Install with: pip install edge-tts pydub sounddevice numpy", file=sys.stderr)
        except Exception as e:
            print(f"[EdgeTTS_ERROR] speak() failed: {type(e).__name__}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    
    async def send(self, text: str) -> None:
        """
        Send text to output (async wrapper for interface compatibility).
        
        Calls speak() synchronously (blocking mode).
        
        Args:
            text: Text to synthesize and play
        """
        self.speak(text)
    
    def stop_sync(self) -> None:
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

    async def stop(self) -> None:
        self.stop_sync()


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