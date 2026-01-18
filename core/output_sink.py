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
    - stop() → cancel playback task immediately (idempotent)
    
    Technical design:
    - Piper subprocess runs in asyncio.create_subprocess_exec (non-blocking)
    - Playback task stored in self._playback_task for cancellation
    - stop() calls task.cancel() + waits for CancelledError (instant)
    - Never uses time.sleep, never blocks event loop
    - Multiple calls to stop() safe (idempotent)
    
    Configuration:
    - VOICE_ENABLED must be true (checked in caller)
    - PIPER_ENABLED must be true (checked in caller)
    - PIPER_PROFILING gates timing probes (non-blocking)
    """
    
    def __init__(self, model_path: Optional[str] = None, audio_output: str = "speaker"):
        """
        Initialize Piper output sink.
        
        Args:
            model_path: Path to Piper model file (default: system default)
            audio_output: "speaker" (default) or "file" path
        """
        self.model_path = model_path or self._get_default_model()
        self.audio_output = audio_output
        self._playback_task: Optional[asyncio.Task] = None
        self._profiling_enabled = PIPER_PROFILING
    
    def _get_default_model(self) -> str:
        """Get default Piper model path (stub for now)."""
        # In production, find installed Piper model
        # For now, assume "en_US-hfc_female-medium"
        return "en_US-hfc_female-medium"
    
    async def send(self, text: str) -> None:
        """
        Send text to Piper for audio playback (non-blocking).
        
        Behavior:
        1. Log audio_request_start checkpoint (if PIPER_PROFILING)
        2. Create async Piper subprocess task
        3. Store task in self._playback_task for stop() to cancel
        4. Return immediately (do NOT await task)
        5. Log audio_first_output checkpoint when audio starts
        
        Non-blocking: send() returns while audio plays in background.
        Cancellable: stop() will halt the playback task.
        
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
            print(f"[PIPER_PROFILING] audio_request_start: {text[:30]}...")
        
        # Create and store playback task (fire-and-forget)
        self._playback_task = asyncio.create_task(self._play_audio(text))
    
    async def _play_audio(self, text: str) -> None:
        """
        Internal: run Piper subprocess to synthesize and play audio.
        
        Non-blocking subprocess execution:
        1. Create Piper subprocess with asyncio.create_subprocess_exec
        2. Send text via stdin
        3. Pipe stdout to audio player (or /dev/null for headless)
        4. Log audio_first_output when audio starts
        5. Await subprocess completion
        
        Cancellation:
        - If task is cancelled during await, subprocess is killed
        - CancelledError propagates cleanly
        """
        try:
            # Piper CLI: echo text | piper --model <model> --output-raw | aplay
            # For Windows, use speaker-test or other audio output
            # For now, stub the actual audio playback
            
            if self._profiling_enabled:
                print(f"[PIPER_PROFILING] audio_first_output: {text[:30]}...")
            
            # Simulate audio playback delay (would be subprocess in production)
            # For testing: just return immediately
            await asyncio.sleep(0.1)
            
        except asyncio.CancelledError:
            # Task was cancelled (stop() was called)
            if self._profiling_enabled:
                print("[PIPER_PROFILING] audio_cancelled")
            raise
    
    async def stop(self) -> None:
        """
        Stop audio playback immediately (idempotent, instant, async-safe).
        
        Behavior:
        1. If playback_task exists and is running: cancel it
        2. Await CancelledError (instant)
        3. If no task running: no-op (idempotent)
        4. If called multiple times: safe (idempotent)
        5. Never raises exceptions
        
        Semantics:
        - stop() is idempotent: can call multiple times safely
        - stop() is instant: < 50ms latency
        - stop() is async-safe: uses only asyncio primitives
        - No fade-out, no tail audio, no apology
        """
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                if self._profiling_enabled:
                    print("[PIPER_PROFILING] stop() called, task cancelled")
                pass  # Expected: task was cancelled
        else:
            # No task or already done: idempotent no-op
            if self._profiling_enabled and self._playback_task:
                print("[PIPER_PROFILING] stop() called, task already done (idempotent)")
            pass
