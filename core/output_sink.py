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

import os
import asyncio
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Optional, Callable


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
    
    This is the default until Piper is integrated (PART 2).
    Text output is handled separately in argo.py and app.py.
    """
    
    async def send(self, text: str) -> None:
        """Send text → no-op in stub."""
        pass
    
    async def stop(self) -> None:
        """Stop → no-op in stub."""
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
"""Global output sink instance (lazy initialization)."""


def get_output_sink() -> OutputSink:
    """
    Get or initialize the global OutputSink.
    
    If VOICE_ENABLED and PIPER_ENABLED: use PiperOutputSink
    Otherwise: use SilentOutputSink
    
    Returns:
        OutputSink: The global instance
    """
    global _output_sink
    if _output_sink is None:
        # Check if Piper should be enabled
        if VOICE_ENABLED and PIPER_ENABLED:
            try:
                _output_sink = PiperOutputSink()
            except Exception as e:
                print(f"⚠ Failed to initialize PiperOutputSink: {e}", file=sys.stderr)
                _output_sink = SilentOutputSink()
        else:
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
    Piper TTS integration: deterministic, non-blocking, instantly stoppable.
    
    Core behavior:
    - send(text) → start async Piper subprocess task (non-blocking return)
    - stop() → terminate process immediately (idempotent)
    
    Technical design:
    - Piper subprocess runs via subprocess.Popen (controlled process)
    - Process handle stored in self._piper_process for kill()
    - Playback task stored in self._playback_task for cancellation
    - stop() calls process.terminate() immediately (hard stop)
    - Never uses time.sleep, never blocks event loop
    - Multiple calls to stop() safe (idempotent)
    
    Configuration:
    - VOICE_ENABLED must be true (checked in caller)
    - PIPER_ENABLED must be true (checked in caller)
    - PIPER_PATH: path to piper.exe (from .env)
    - PIPER_VOICE: path to voice model (from .env)
    - PIPER_PROFILING gates timing probes (non-blocking)
    """
    
    def __init__(self):
        """
        Initialize Piper output sink.
        
        Reads configuration from .env:
        - PIPER_PATH: path to piper executable
        - VOICE_PROFILE: voice profile selection ('lessac' or 'allen')
        - PIPER_VOICE: path to voice model file (can be overridden)
        
        Raises ValueError if Piper or voice model not found.
        
        Phase 7D: Voice profile support (data/config only, no logic changes)
        """
        self.piper_path = os.getenv("PIPER_PATH", "audio/piper/piper/piper.exe")
        
        # Get voice model path based on VOICE_PROFILE
        # Priority: PIPER_VOICE env var > VOICE_PROFILE setting > default (lessac)
        # Note: Allen voice disabled - produces zero bytes with current Piper build
        if os.getenv("PIPER_VOICE"):
            self.voice_path = os.getenv("PIPER_VOICE")
        else:
            self.voice_path = _get_voice_model_path(VOICE_PROFILE)
        
        self._playback_task: Optional[asyncio.Task] = None
        self._piper_process: Optional[subprocess.Popen] = None
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
            # For testing: allow missing voice model if explicitly skipped
    
    async def send(self, text: str) -> None:
        """
        Send text to Piper for audio playback (non-blocking).
        
        Behavior:
        1. Cancel any existing playback task
        2. Log audio_request_start checkpoint (if PIPER_PROFILING)
        3. Create async Piper subprocess task
        4. Store task in self._playback_task for stop() to cancel
        5. Await task completion (blocking mode for CLI)
        6. Log audio_first_output checkpoint when audio starts
        
        Blocking: send() waits for audio to complete before returning.
        Cancellable: stop() will halt the playback task and process.
        
        Args:
            text: Text to synthesize and play
        """
        # Cancel any existing playback task
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
        
        # Log timing probe: audio_request_start
        if self._profiling_enabled:
            import time
            print(f"[PIPER_PROFILING] audio_request_start: {text[:30]}... @ {time.time():.3f}")
        
        # Create playback task and await it (blocking until audio completes)
        self._playback_task = asyncio.create_task(self._play_audio(text))
        try:
            await self._playback_task
        except asyncio.CancelledError:
            pass  # Task was cancelled by stop()
    
    async def _play_audio(self, text: str) -> None:
        """
        Internal: run Piper subprocess to synthesize and play audio (with streaming).
        
        Streaming Flow (PHASE 7A-2):
        1. Create Piper subprocess with subprocess.Popen
        2. Send text via stdin, close stdin immediately
        3. Read audio frames incrementally from stdout (non-blocking)
        4. Start playback as soon as first frames are available (time-to-first-audio)
        5. Continue reading/playing until synthesis complete
        6. Log timing checkpoints for profiling
        
        Key behaviors:
        - Playback begins immediately (not waiting for full synthesis)
        - Reduces time-to-first-audio significantly
        - STOP authority preserved: subprocess killed immediately on cancellation
        - State machine authority preserved: no new states
        - Profiling enabled: measure time-to-first-audio, duration, STOP latency
        
        Cancellation:
        - If task is cancelled during await, process is terminated
        - CancelledError propagates cleanly
        - Process cleanup is guaranteed
        
        Hard stops:
        - No fade-out, no tail audio
        - Process killed immediately on cancellation
        """
        try:
            time_module = None
            if self._profiling_enabled:
                import time as time_module
                time_start = time_module.time()
                print(f"[PIPER_PROFILING] audio_first_output: {text[:30]}... @ {time_start:.3f}")
            
            # Start Piper subprocess
            # Command: piper --model <voice_path> --output-raw to get raw PCM output
            # PCM is more reliable than WAV for concatenated synthesis
            
            try:
                # Create subprocess in non-blocking mode
                # Use --output-raw to get raw PCM audio to stdout (not WAV which can have header issues)
                self._piper_process = await asyncio.create_subprocess_exec(
                    self.piper_path,
                    "--model", self.voice_path,
                    "--output-raw",
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] piper process started, sending text...")
                
                # Send text to Piper stdin (non-blocking)
                # Close stdin immediately after sending text to signal end of input
                self._piper_process.stdin.write(text.encode("utf-8"))
                await self._piper_process.stdin.drain()
                self._piper_process.stdin.close()
                
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] text sent to piper stdin, starting streaming read...")
                
                # Stream audio data incrementally (PHASE 7A-2 UPGRADE)
                # Read frames as they arrive, start playback immediately
                await self._stream_audio_data(self._piper_process, text, time_module if self._profiling_enabled else None, time_start if self._profiling_enabled else None)
                
                # Wait for process to complete
                await self._piper_process.wait()
                
                if self._profiling_enabled:
                    stderr = await self._piper_process.stderr.read()
                    if stderr:
                        print(f"[PIPER_PROFILING] piper stderr: {stderr.decode('utf-8', errors='replace')}")
                
            finally:
                self._piper_process = None
        
        except asyncio.CancelledError:
            # Task was cancelled (stop() was called)
            # Kill the Piper process immediately
            if self._piper_process and self._piper_process.returncode is None:
                try:
                    self._piper_process.terminate()
                    # Give it a moment to terminate gracefully
                    try:
                        await asyncio.wait_for(
                            asyncio.sleep(0.1),
                            timeout=0.1
                        )
                    except asyncio.TimeoutError:
                        pass
                    
                    # If still alive, kill it hard
                    if self._piper_process.returncode is None:
                        self._piper_process.kill()
                except Exception:
                    pass  # Process already terminated
                
                self._piper_process = None
            
            if self._profiling_enabled:
                import time
                print(f"[PIPER_PROFILING] audio_cancelled @ {time.time():.3f}")
            
            raise
    
    async def _stream_audio_data(self, process, text: str, time_module=None, time_start=None) -> None:
        """
        Internal: stream audio frames from Piper subprocess and play incrementally.
        
        Implements PHASE 7A-2 streaming:
        - Reads raw PCM frames from subprocess stdout (don't block on full completion)
        - Buffers frames incrementally
        - Once buffer reaches threshold, starts playback while continuing to read
        - Continues reading any additional frames after playback starts
        - Reduces time-to-first-audio (TTFA) significantly
        
        Key metrics (from profiling):
        - time-to-first-audio: time from request to first frame available
        - playback_start: time when we have enough buffered to begin playback
        - streaming_complete: time when all frames read and audio fully synthesized
        
        Args:
            process: asyncio subprocess with stdout=PIPE
            text: Original query text (for profiling)
            time_module: time module for profiling (if enabled)
            time_start: Start time for profiling (if enabled)
        """
        try:
            import numpy as np
            
            # Read audio in chunks (frame size for streaming)
            # Piper outputs raw PCM int16 @ 22050 Hz mono
            # Frame size: 22050 / 10 = 2205 samples = 4410 bytes per 100ms chunk
            FRAME_SIZE_BYTES = 4410  # ~100ms of audio at 22050 Hz
            SAMPLE_RATE = 22050
            BUFFER_THRESHOLD = 2  # Need at least 200ms buffered before playback
            
            audio_frames = []
            bytes_received = 0
            first_frame_received = False
            playback_task = None
            
            # Read all frames from Piper (non-blocking to event loop)
            while True:
                try:
                    # Read one frame (non-blocking to event loop)
                    frame = await process.stdout.readexactly(FRAME_SIZE_BYTES)
                    bytes_received += len(frame)
                    audio_frames.append(frame)
                    
                    if not first_frame_received:
                        first_frame_received = True
                        if self._profiling_enabled and time_module:
                            time_first_frame = time_module.time()
                            latency = (time_first_frame - time_start) * 1000
                            print(f"[PIPER_PROFILING] first_audio_frame_received: {bytes_received} bytes @ {latency:.1f}ms latency")
                    
                    # Once we have enough frames, start playback (don't wait for full synthesis)
                    if playback_task is None and len(audio_frames) >= BUFFER_THRESHOLD:
                        if self._profiling_enabled and time_module:
                            time_playback_start = time_module.time()
                            latency = (time_playback_start - time_start) * 1000
                            buffered_bytes = len(audio_frames) * FRAME_SIZE_BYTES
                            print(f"[PIPER_PROFILING] playback_started: {buffered_bytes} bytes buffered @ {latency:.1f}ms latency")
                        
                        # Start playback in background (don't block frame reading)
                        playback_task = asyncio.create_task(
                            self._stream_to_speaker(audio_frames, SAMPLE_RATE)
                        )
                
                except asyncio.IncompleteReadError as e:
                    # EOF reached (partial frame or end of stream)
                    if e.partial:
                        audio_frames.append(e.partial)
                        bytes_received += len(e.partial)
                    break
                except asyncio.LimitOverrunError:
                    # Buffer limit, read what we can
                    frame = await process.stdout.read(FRAME_SIZE_BYTES)
                    if not frame:
                        break
                    audio_frames.append(frame)
                    bytes_received += len(frame)
            
            # If playback never started (response too short), play now
            if playback_task is None and audio_frames:
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] playback_deferred: response too short, starting now with {len(audio_frames) * FRAME_SIZE_BYTES} bytes")
                await self._stream_to_speaker(audio_frames, SAMPLE_RATE)
            elif playback_task is not None:
                # Playback already started, wait for it to complete
                try:
                    await playback_task
                except asyncio.CancelledError:
                    playback_task.cancel()
                    raise
            
            if self._profiling_enabled and time_module:
                time_end = time_module.time()
                total_duration = (time_end - time_start) * 1000
                print(f"[PIPER_PROFILING] streaming_complete: {bytes_received} bytes total, {total_duration:.1f}ms duration")
        
        except asyncio.CancelledError:
            if self._profiling_enabled:
                import time
                print(f"[PIPER_PROFILING] stream_audio_data cancelled @ {time.time():.3f}")
            raise
        except Exception as e:
            print(f"[AUDIO_ERROR] Stream error: {type(e).__name__}: {e}", file=sys.stderr)
            raise
    
    async def _stream_to_speaker(self, audio_frames: list, sample_rate: int) -> None:
        """
        Internal: stream audio frames to speaker device using sounddevice.
        
        Plays audio chunks as they're received, enabling incremental playback.
        """
        try:
            import sounddevice
        except ImportError:
            if self._profiling_enabled:
                print("[DEBUG] sounddevice not installed; audio playback disabled", file=sys.stderr)
            return
        
        try:
            import numpy as np
            
            # Convert all collected frames to numpy array
            audio_bytes = b''.join(audio_frames)
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            if self._profiling_enabled:
                print(f"[PIPER_PROFILING] audio_data_size: {len(audio_bytes)} bytes ({len(audio_data)} samples)")
                print(f"[PIPER_PROFILING] audio_range: [{audio_data.min():.4f}, {audio_data.max():.4f}]")
            
            # Normalize if needed
            max_abs = np.abs(audio_data).max()
            if max_abs > 1.0:
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] normalizing audio (max was {max_abs:.4f})")
                audio_data = audio_data / max_abs
            
            # Play to default speaker in thread pool
            loop = asyncio.get_event_loop()
            
            def play_sync():
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] playing_audio_to_speaker")
                sounddevice.play(audio_data, samplerate=sample_rate, blocking=True)
                if self._profiling_enabled:
                    print(f"[PIPER_PROFILING] playback_complete")
            
            await loop.run_in_executor(None, play_sync)
        
        except Exception as e:
            print(f"[AUDIO_ERROR] Speaker stream error: {type(e).__name__}: {e}", file=sys.stderr)
            if self._profiling_enabled:
                import traceback
                traceback.print_exc()
    
    async def stop(self) -> None:
        """
        Stop audio playback immediately (idempotent, instant, async-safe).
        
        Behavior:
        1. If playback_task exists and is running: cancel it
        2. If piper_process exists: terminate it immediately
        3. Await CancelledError from task (instant)
        4. If no task running: no-op (idempotent)
        5. If called multiple times: safe (idempotent)
        6. Never raises exceptions
        
        Semantics:
        - stop() is idempotent: can call multiple times safely
        - stop() is instant: < 50ms latency
        - stop() is async-safe: uses only asyncio primitives
        - Hard termination: no fade-out, no tail audio, no apology
        """
        # Terminate Piper process immediately (hard stop)
        if self._piper_process and self._piper_process.returncode is None:
            try:
                self._piper_process.terminate()
                # Give it a moment
                try:
                    await asyncio.wait_for(
                        asyncio.sleep(0.05),
                        timeout=0.05
                    )
                except asyncio.TimeoutError:
                    pass
                
                # If still alive, kill hard
                if self._piper_process.returncode is None:
                    self._piper_process.kill()
            except Exception:
                pass  # Already terminated
            finally:
                self._piper_process = None
        
        # Cancel playback task
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                if self._profiling_enabled:
                    import time
                    print(f"[PIPER_PROFILING] stop() called, task cancelled @ {time.time():.3f}")
                pass  # Expected: task was cancelled
        else:
            # No task or already done: idempotent no-op
            if self._profiling_enabled and self._playback_task:
                import time
                print(f"[PIPER_PROFILING] stop() called, task already done (idempotent) @ {time.time():.3f}")
            pass

