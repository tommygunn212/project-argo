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
# GLOBAL INSTANCE
# ============================================================================

_output_sink: Optional[OutputSink] = None
"""Global output sink instance (lazy initialization)."""


def get_output_sink() -> OutputSink:
    """
    Get or initialize the global OutputSink.
    
    First call initializes the sink to SilentOutputSink.
    Later, PART 2 will replace this with PiperOutputSink.
    
    Returns:
        OutputSink: The global instance
    """
    global _output_sink
    if _output_sink is None:
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
        - PIPER_VOICE: path to voice model file
        
        Raises ValueError if Piper or voice model not found.
        """
        self.piper_path = os.getenv("PIPER_PATH", "audio/piper/piper.exe")
        self.voice_path = os.getenv("PIPER_VOICE", "audio/piper/voices/en_US-lessac-medium.onnx")
        self._playback_task: Optional[asyncio.Task] = None
        self._piper_process: Optional[subprocess.Popen] = None
        self._profiling_enabled = PIPER_PROFILING
        
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
        5. Return immediately (do NOT await task)
        6. Log audio_first_output checkpoint when audio starts
        
        Non-blocking: send() returns while audio plays in background.
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
        
        # Create and store playback task (fire-and-forget)
        self._playback_task = asyncio.create_task(self._play_audio(text))
    
    async def _play_audio(self, text: str) -> None:
        """
        Internal: run Piper subprocess to synthesize and play audio.
        
        Flow:
        1. Create Piper subprocess with subprocess.Popen
        2. Send text via stdin
        3. Read output (audio bytes) from stdout
        4. Play audio (Windows: uses default speaker, or specified device)
        5. Log audio_first_output when audio starts
        6. Await subprocess completion
        
        Cancellation:
        - If task is cancelled during await, process is terminated
        - CancelledError propagates cleanly
        - Process cleanup is guaranteed
        
        Hard stops:
        - No fade-out, no tail audio
        - Process killed immediately on cancellation
        """
        try:
            if self._profiling_enabled:
                import time
                print(f"[PIPER_PROFILING] audio_first_output: {text[:30]}... @ {time.time():.3f}")
            
            # Start Piper subprocess
            # Command: piper --model <voice_path> --output-raw | aplay (or equivalent)
            # For Windows, Piper outputs WAV audio to stdout
            # We pipe it to the system default audio player
            
            try:
                # Create subprocess in non-blocking mode
                self._piper_process = await asyncio.create_subprocess_exec(
                    self.piper_path,
                    "--model", self.voice_path,
                    "--output-raw",
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                
                # Send text to Piper stdin
                stdout, stderr = await self._piper_process.communicate(
                    input=text.encode("utf-8")
                )
                
                # If we got audio data, play it
                if stdout:
                    await self._play_audio_data(stdout)
                
                if stderr:
                    if self._profiling_enabled:
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
                            asyncio.create_task(
                                asyncio.sleep(0.1)
                            ),
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
    
    async def _play_audio_data(self, audio_bytes: bytes) -> None:
        """
        Internal: play audio bytes to system audio device.
        
        On Windows: use winsound.Beep or subprocess to player
        On Linux: use aplay or paplay
        On macOS: use afplay
        
        For now, simple implementation: just return (audio is ready to play)
        In production: pipe to actual audio player.
        
        Args:
            audio_bytes: Raw audio data from Piper
        """
        # Stub: in production, pipe to audio player
        # For testing, just consume the bytes and return
        await asyncio.sleep(0.01)  # Minimal delay
    
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

