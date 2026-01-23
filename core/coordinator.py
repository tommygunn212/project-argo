"""
COORDINATOR v4: INTERACTION LOOP + SESSION MEMORY (BOUNDED & CONTROLLED)

Orchestration layer that loops for multiple interactions with short-term working memory.

Pipeline (repeats per iteration):
1. InputTrigger: Wait for wake word
2. Audio Capture: Record user speech
3. SpeechToText: Transcribe to text
4. IntentParser: Classify text to intent
5. ResponseGenerator: Generate response via LLM (with optional memory reference)
6. OutputSink: Speak response
7. SessionMemory: Store interaction (utterance, intent, response)
8. Check stop condition (user said "stop" OR max interactions reached)

Loop continues UNTIL:
- User says a stop command ("stop", "goodbye", etc.)
- OR max interactions reached (hardcoded: e.g., 3)
- Then exit cleanly

This is pure orchestration. Coordinator does NOT know or care that ResponseGenerator uses an LLM.

Core concept:
- InputTrigger: Detects wake word, fires callback
- SpeechToText: Transcribes audio to text
- IntentParser: Classifies text into intent
- ResponseGenerator: Generates response text (LLM-based, isolated)
- OutputSink: Generates audio from text, publishes it
- SessionMemory: Stores recent interactions (bounded ring buffer)
- Coordinator: Orchestrates them in correct order, loops until stop condition

SessionMemory:
- Stores last N interactions (default 3)
- Cleared on program exit (not persistent)
- Read-only for ResponseGenerator (can reference but not modify)
- Automatically evicts oldest when full
- NOT learning, NOT embeddings, NOT personality

Changes from v3:
- Add SessionMemory instantiation at startup
- Append to memory after each iteration
- Pass SessionMemory to ResponseGenerator (read-only)
- Clear memory on exit
- Everything else identical to v3

What Coordinator is NOT:
- Not a brain (no logic beyond routing)
- Not intelligent (purely orchestration)
- Not knowledgeable (ResponseGenerator is isolated)
- Not configurable (hardcoded everything)
- Not persistent (SessionMemory cleared on exit)
- Not fault-tolerant (no retries)
- Not a full chatbot (short-term working memory only, not personality)

This is controlled, bounded orchestration with short-term scratchpad memory.
"""

import logging
import threading
import time
import re
from typing import Optional
from datetime import datetime
import sounddevice as sd
import numpy as np
import warnings

# Suppress sounddevice Windows cffi warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="sounddevice")

from core.intent_parser import Intent, IntentType
from core.session_memory import SessionMemory
from core.latency_probe import LatencyProbe, LatencyStats
from core.policy import (
    LLM_WATCHDOG_SECONDS,
    TTS_WATCHDOG_SECONDS,
    RESPONSE_WATCHDOG_SECONDS,
    WATCHDOG_FALLBACK_RESPONSE,
)
from core.watchdog import Watchdog
from core.state_machine import StateMachine, State
from core.actuators.python_builder import PythonBuilder

# === Logging ===
logger = logging.getLogger(__name__)


class Coordinator:
    """
    End-to-end orchestration with bounded interaction loop + session memory.
    
    Loop behavior (v4 — differs from v3):
    - Repeats until STOP condition
    - Each iteration is independent (no learning, no personality)
    - Short-term working memory stores recent interactions
    - SessionMemory passed to ResponseGenerator (read-only)
    - Exits cleanly after stop or max iterations
    
    Stop conditions:
    1. User says a stop command (detected in response text)
    2. Max interactions reached (hardcoded)
    
    SessionMemory:
    - Bounded ring buffer (default capacity 3)
    - Stores: utterance, intent, response per interaction
    - Read-only for ResponseGenerator (can reference recent context)
    - Cleared automatically on exit (not persistent)
    - NOT embeddings, NOT learning, NOT personality
    
    Each iteration:
    1. Wait for wake word (InputTrigger)
    2. Record audio during trigger callback
    3. Transcribe audio (SpeechToText)
    4. Classify intent (IntentParser)
    5. Generate response (ResponseGenerator, with SessionMemory available)
    6. Speak response (OutputSink)
    7. Store in SessionMemory (utterance, intent, response)
    8. Check stop condition
    9. If no stop → loop back to step 1
    10. If stop → clear memory and exit cleanly
    
    What Coordinator does:
    - Loop until stop condition
    - Orchestrate all layers in correct order per iteration
    - Record audio window during callback
    - Route text through SpeechToText → IntentParser
    - Pass intent + SessionMemory to ResponseGenerator for response
    - Call OutputSink to speak
    - Append interaction to SessionMemory
    - Track interaction count
    - Detect stop keywords in response
    - Clear memory on exit
    - Exit cleanly when done
    
    What Coordinator does NOT:
    - Inspect or modify generated response text (except for stop detection)
    - Know that ResponseGenerator uses an LLM
    - Modify SessionMemory (append-only, read-only for generator)
    - Make responses learn or adapt (each response independent)
    - Retry on failure (single attempt per turn)
    - Make any decisions beyond routing
    
    v4 Changes from v3:
    - Add SessionMemory instantiation at startup
    - Append to memory after each iteration
    - Pass SessionMemory to ResponseGenerator
    - Clear memory on exit
    - Everything else identical to v3
    
    Multi-turn with working memory but stateless personality:
    wake → listen → respond → [store in memory] → [check stop] → [loop] → exit
    
    Usage:
    ```python
    coordinator = Coordinator(
        input_trigger=trigger,
        speech_to_text=stt,
        intent_parser=parser,
        response_generator=generator,
        output_sink=sink
    )
    coordinator.run()  # Loops until stop condition or max interactions
    ```
    """
    
    # Audio recording parameters
    AUDIO_SAMPLE_RATE = 16000  # Hz
    MAX_RECORDING_DURATION = 15.0  # seconds max (safety net) — Extended for longer LED explanation
    MIN_RECORDING_DURATION = 0.9  # Minimum record duration (prevents truncation)
    SILENCE_DURATION = 0.7  # Seconds of silence to stop recording — TUNED for fast response
    MINIMUM_RECORD_DURATION = 0.9  # Minimum record duration (prevents truncation) - CANONICAL NAME
    SILENCE_TIMEOUT_SECONDS = 5.0  # Seconds of silence to stop recording — Increased for detailed explanations
    SILENCE_THRESHOLD = 1800  # Audio level below this = silence (RMS absolute) — Tuned for room hum
    RMS_SPEECH_THRESHOLD = 0.015  # RMS normalized level (0-1) to START silence timer — Reduced sensitivity
    PRE_ROLL_BUFFER_MS_MIN = 1000  # Min milliseconds of pre-speech audio to capture — 1 second pre-wake context
    PRE_ROLL_BUFFER_MS_MAX = 1200  # Max milliseconds to keep in rolling buffer — 1.2 second look-back
    
    # Debug/profiling flags
    RECORD_DEBUG = False  # Set to True for detailed recording metrics (or via env var)
    
    # Loop control (hardcoded)
    MAX_INTERACTIONS = 10  # Max interactions per session — Increased for longer testing
    STOP_KEYWORDS = ["stop", "goodbye", "quit", "exit"]  # Stop command keywords
    IDLE_SLEEP_SECONDS = 45.0  # Sleep after N seconds of inactivity
    SPEECH_START_POLL_SECONDS = 0.5  # Poll interval while waiting for speech
    WAKE_ACK_ENABLED = True  # Short wake acknowledgment
    WAKE_ACK_HZ = 880
    WAKE_ACK_DURATION_MS = 120
    
    def __init__(self, input_trigger, speech_to_text, intent_parser, response_generator, output_sink):
        """
        Initialize Coordinator with all pipeline layers + SessionMemory.
        
        Args:
            input_trigger: InputTrigger instance (detects wake word)
            speech_to_text: SpeechToText instance (transcribes audio)
            intent_parser: IntentParser instance (classifies text)
            response_generator: ResponseGenerator instance (generates response)
            output_sink: OutputSink instance (speaks response)
        """
        import os
        from core.command_executor import CommandExecutor
        
        self.trigger = input_trigger
        self.stt = speech_to_text
        self.parser = intent_parser
        self.generator = response_generator
        self.sink = output_sink
        self.logger = logger
        
        # CommandExecutor for procedural commands (count to N, etc.)
        self.executor = CommandExecutor(audio_sink=output_sink)
        
        # Enable debug metrics via env var or class flag
        self.record_debug = os.getenv("ARGO_RECORD_DEBUG", "0").lower() in ("1", "true")
        
        # Audio buffer for recording
        self.recorded_audio = None
        
        # Session memory (v4) — short-term working memory for this session only
        self.memory = SessionMemory(capacity=5)
        
        # TASK 15: Latency instrumentation
        self.latency_stats = LatencyStats()
        self.current_probe: Optional[LatencyProbe] = None
        
        # PHASE 16: Observer snapshot state (for read-only observation)
        self._last_wake_timestamp = None
        self._last_transcript = None
        self._last_intent = None
        self._last_response = None
        
        # TASK 17: Half-duplex audio gate (prevent simultaneous listen/speak)
        # Use threading.Event for thread-safe atomic state (not boolean)
        self._is_speaking = threading.Event()
        self._is_speaking.clear()  # Initially not speaking
        self._is_processing = threading.Event()
        self._is_processing.clear()
        
        # Debug/profiling flag from environment (can override class default)
        self.record_debug = os.getenv("RECORD_DEBUG", "").lower() == "true" or self.RECORD_DEBUG
        
        # GUI Callbacks (optional, can be set by external GUI)
        self.on_recording_start = None
        self.on_recording_stop = None
        self.on_status_update = None
        
        # Loop state (v3)
        self.interaction_count = 0
        self.stop_requested = False

        # Python builder actuator (sandbox tools)
        self.builder = PythonBuilder()
        self._last_built_script: Optional[str] = None
        self.last_response_text: Optional[str] = None

        # State machine (sleep/listening lifecycle)
        self.state_machine = StateMachine(on_state_change=self._on_state_change)

        # Idle/sleep tracking
        self.idle_sleep_seconds = float(
            os.getenv("ARGO_IDLE_SLEEP_SECONDS", str(self.IDLE_SLEEP_SECONDS))
        )
        self._last_utterance_time = None
        
        # Dynamic timeout for next recording (starts at default, updates after each transcription)
        self.dynamic_silence_timeout = self.SILENCE_TIMEOUT_SECONDS
        
        self.logger.info("[Coordinator v4] Initialized (with interaction loop + session memory)")
        self.logger.debug(f"  InputTrigger: {type(self.trigger).__name__}")
        self.logger.debug(f"  SpeechToText: {type(self.stt).__name__}")
        self.logger.debug(f"  IntentParser: {type(self.parser).__name__}")
        self.logger.debug(f"  ResponseGenerator: {type(self.generator).__name__}")
        self.logger.debug(f"  OutputSink: {type(self.sink).__name__}")
        self.logger.debug(f"  SessionMemory: capacity={self.memory.capacity}")
        self.logger.debug(f"  Max interactions: {self.MAX_INTERACTIONS}")
        self.logger.debug(f"  Stop keywords: {self.STOP_KEYWORDS}")
    
    def get_dynamic_timeout(self, transcribed_text: str) -> float:
        """
        Smart Timing Logic: Adjust silence timeout based on query type.
        
        Quick queries (factual questions) → snappy 1.0s timeout
        Stories/explanations (detailed questions) → patient 5.0s timeout
        
        Args:
            transcribed_text: The transcribed user input
            
        Returns:
            Timeout in seconds (1.0 or 5.0)
        """
        quick_triggers = ["what is", "who is", "time", "stop", "next", "status"]
        
        text_lower = transcribed_text.lower()
        
        # If it's a simple, short query, be snappy
        if any(trigger in text_lower for trigger in quick_triggers):
            self.logger.info(f"[SmartTiming] Quick query detected: '{transcribed_text[:50]}' → 1.0s timeout")
            return 1.0
        
        # If it's a story or explanation, be patient
        self.logger.info(f"[SmartTiming] Detailed query detected: '{transcribed_text[:50]}' → 5.0s timeout")
        return 5.0

    def _on_state_change(self, old_state: State, new_state: State) -> None:
        """Handle state changes (optional GUI updates)."""
        self.logger.info(f"[State] {old_state.value} -> {new_state.value}")
        if self.on_status_update:
            try:
                self.on_status_update(new_state.value)
            except Exception as e:
                self.logger.debug(f"[Coordinator] on_status_update error: {e}")

    def _play_wake_ack(self) -> None:
        """Play a short wake acknowledgment (non-blocking fallback)."""
        if not self.WAKE_ACK_ENABLED:
            return
        try:
            import winsound
            winsound.Beep(self.WAKE_ACK_HZ, self.WAKE_ACK_DURATION_MS)
        except Exception:
            # Best-effort; fail silently to avoid blocking wake flow
            pass

    def _wait_for_speech_start(self, max_wait_seconds: float) -> Optional[list]:
        """
        Wait for speech onset using RMS threshold and return pre-roll frames.

        Returns:
            List of pre-roll frames if speech detected, or None on timeout.
        """
        import numpy as np

        chunk_samples = int(self.AUDIO_SAMPLE_RATE * 0.1)
        preroll_capacity = max(1, int(self.PRE_ROLL_BUFFER_MS_MAX / 100))
        preroll_frames = []

        start_time = time.time()
        stream = None
        try:
            stream = sd.InputStream(
                channels=1,
                samplerate=self.AUDIO_SAMPLE_RATE,
                dtype=np.int16,
            )
            stream.start()

            while True:
                if max_wait_seconds is not None and (time.time() - start_time) >= max_wait_seconds:
                    return None

                frame, _ = stream.read(chunk_samples)
                if frame.size == 0:
                    continue

                preroll_frames.append(frame.copy())
                if len(preroll_frames) > preroll_capacity:
                    preroll_frames.pop(0)

                rms = np.sqrt(np.mean(frame.astype(float) ** 2)) / 32768.0
                if rms > self.RMS_SPEECH_THRESHOLD:
                    return preroll_frames
        except Exception as e:
            self.logger.debug(f"[Listen] Speech-start detection failed: {e}")
            return None
        finally:
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    self.logger.debug(f"[Listen] Error closing stream: {e}")

    def _handle_interaction(self, initial_frames: Optional[list] = None, mark_wake: bool = False) -> bool:
        """
        Process a single interaction from audio capture through response.

        Returns:
            True if an interaction was processed, False if skipped.
        """
        is_music_iteration = False
        self.interaction_count += 1
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"[Loop] Iteration {self.interaction_count}/{self.MAX_INTERACTIONS}")
        self.logger.info(f"[Loop] Memory: {self.memory}")
        self.logger.info(f"{'='*60}")

        try:
            # Half-duplex: abort if speaking
            if self._is_speaking.is_set():
                self.logger.info("[Iteration] Skipping interaction: currently speaking")
                self.interaction_count -= 1
                return False
            self._is_processing.set()
            # TASK 15: Initialize latency probe for this interaction
            self.current_probe = LatencyProbe(self.interaction_count)
            if mark_wake:
                self.current_probe.mark("wake_detected")

            # 1. Record audio with dynamic silence detection
            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Recording (max {self.MAX_RECORDING_DURATION}s, stops on {self.SILENCE_DURATION}s silence)..."
            )

            # TASK 15: Mark recording start
            self.current_probe.mark("recording_start")

            # GUI Callback: Recording started
            if self.on_recording_start:
                try:
                    self.on_recording_start()
                except Exception as e:
                    self.logger.debug(f"[Coordinator] on_recording_start callback error: {e}")

            # Record audio dynamically with silence detection
            audio = self._record_with_silence_detection(initial_frames=initial_frames)

            # TASK 15: Mark recording end
            self.current_probe.mark("recording_end")

            # GUI Callback: Recording stopped
            if self.on_recording_stop:
                try:
                    self.on_recording_stop()
                except Exception as e:
                    self.logger.debug(f"[Coordinator] on_recording_stop callback error: {e}")

            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Recorded {len(audio)} samples ({len(audio)/self.AUDIO_SAMPLE_RATE:.2f}s)"
            )

            # Convert to WAV bytes
            from scipy.io import wavfile
            import io

            audio_buffer = io.BytesIO()
            wavfile.write(audio_buffer, self.AUDIO_SAMPLE_RATE, audio)
            audio_bytes = audio_buffer.getvalue()
            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Audio buffer: {len(audio_bytes)} bytes"
            )

            # 2. Transcribe audio
            self.logger.info(
                f"[Iteration {self.interaction_count}] Transcribing audio..."
            )

            # TASK 15: Mark STT start
            self.current_probe.mark("stt_start")

            text = self.stt.transcribe(audio_bytes, self.AUDIO_SAMPLE_RATE)

            # TASK 15: Mark STT end
            self.current_probe.mark("stt_end")

            # PHASE 16: Capture for observer snapshot
            self._last_wake_timestamp = datetime.now()
            self._last_transcript = text

            # SmartTiming: Set dynamic timeout for next recording based on query type
            self.dynamic_silence_timeout = self.get_dynamic_timeout(text)

            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Transcribed: '{text}'"
            )

            # Self-echo filter: drop transcripts too similar to last response
            if self.last_response_text:
                similarity = self._similarity_ratio(text, self.last_response_text)
                if similarity >= 0.80:
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] "
                        f"Self-echo detected (similarity={similarity:.2f}); discarding transcript"
                    )
                    self.interaction_count -= 1
                    return False

            # Feedback loop: run/test last built script
            run_triggers = {"run it", "test it", "run", "test"}
            if self._last_built_script and text.lower().strip() in run_triggers:
                self.logger.info(
                    f"[Iteration {self.interaction_count}] Running sandbox script: {self._last_built_script}"
                )
                output = self.builder.test_run(self._last_built_script)
                analysis_intent = Intent(
                    intent_type=IntentType.DEVELOP,
                    confidence=1.0,
                    raw_text=(
                        f"The script '{self._last_built_script}' was executed. "
                        f"Output:\n{output}\n" 
                        f"Summarize the result and suggest next steps."
                    ),
                )
                response_text = self.generator.generate(analysis_intent, self.memory)
                self._last_response = response_text
                self.last_response_text = response_text
                self.sink.speak(response_text)
                self.memory.append(
                    user_utterance=text,
                    parsed_intent=analysis_intent.intent_type.value,
                    generated_response=response_text,
                )
                self._last_utterance_time = time.time()
                return True

            # Skip if transcription is empty (just silence/noise)
            if not text or not text.strip():
                self.logger.info(
                    f"[Iteration {self.interaction_count}] "
                    f"Empty transcription (silence only), skipping..."
                )
                self.interaction_count -= 1
                return False

            # 3. Parse intent
            self.logger.info(
                f"[Iteration {self.interaction_count}] Parsing intent..."
            )

            # TASK 15: Mark parsing start
            self.current_probe.mark("parsing_start")

            intent = self.parser.parse(text)

            # TASK 15: Mark parsing end
            self.current_probe.mark("parsing_end")

            # PHASE 16: Capture for observer snapshot
            self._last_intent = intent

            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Intent: {intent.intent_type.value} "
                f"(confidence={intent.confidence:.2f})"
            )

            # Ignore low-confidence noise
            if intent.intent_type == IntentType.UNKNOWN and intent.confidence < 0.5:
                self.logger.info(
                    f"[Iteration {self.interaction_count}] "
                    f"Low-confidence unknown intent, ignoring."
                )
                self.interaction_count -= 1
                return False

            # 4. Fast-path deterministic commands (before LLM generation)
            # Procedural and deterministic commands must execute immediately without LLM latency

            response_watchdog = Watchdog("RESPONSE", RESPONSE_WATCHDOG_SECONDS)
            response_watchdog.__enter__()
            output_produced = False
            response_watchdog_finalized = False

            def _finalize_response_watchdog():
                nonlocal output_produced, response_watchdog_finalized
                if response_watchdog_finalized:
                    return
                response_watchdog.__exit__(None, None, None)
                response_watchdog_finalized = True
                if response_watchdog.triggered and not output_produced:
                    self.logger.warning(
                        "[WATCHDOG] NO_OUTPUT_DETECTED: elapsed=%.2fs",
                        response_watchdog.elapsed_seconds,
                    )
                    if WATCHDOG_FALLBACK_RESPONSE:
                        try:
                            self.sink.speak(WATCHDOG_FALLBACK_RESPONSE)
                            output_produced = True
                        except Exception:
                            pass
                    # Reset to safe idle state
                    self.stop_requested = False
                    self._is_speaking.clear()

            if intent.intent_type == IntentType.SLEEP:
                self.logger.info(f"[Iteration {self.interaction_count}] Sleep command detected")
                try:
                    self.sink.speak("Going quiet.")
                    output_produced = True
                except Exception:
                    pass
                self.state_machine.sleep()
                self._last_utterance_time = time.time()
                self.current_probe.mark("llm_end")
                self.current_probe.mark("tts_start")
                self.current_probe.mark("tts_end")
                self.current_probe.log_summary()
                self.latency_stats.add_probe(self.current_probe)
                _finalize_response_watchdog()
                return True

            if self.executor.can_execute(text):
                self.logger.info(f"[Iteration {self.interaction_count}] Procedural command detected: '{text}'")
                # TASK 15: Mark LLM start (skip for procedural commands)
                self.current_probe.mark("llm_start")
                try:
                    # Execute command directly (bypasses LLM)
                    self.executor.execute(text)
                    response_text = ""  # No LLM response for procedural commands
                    output_produced = True
                    self.current_probe.mark("llm_end")
                    # Exit callback - procedural command complete, skip LLM
                    self.logger.info(f"[Iteration {self.interaction_count}] Procedural command complete")
                    _finalize_response_watchdog()
                    self._last_utterance_time = time.time()
                    return True
                except Exception as e:
                    self.logger.error(f"[Iteration {self.interaction_count}] Procedural command failed: {e}")
                    response_text = "Command failed."
                    self.current_probe.mark("llm_end")
                    _finalize_response_watchdog()
                    self._last_utterance_time = time.time()
                    return True

            # Generate response (LLM, with SessionMemory available)
            self.logger.info(
                f"[Iteration {self.interaction_count}] Generating response..."
            )

            # TASK 15: Mark LLM start
            self.current_probe.mark("llm_start")

            # Deterministic commands: STOP/PAUSE (music), NEXT, STATUS
            # These routes bypass LLM entirely and execute directly.
            # Check if this is a STOP command (highest priority - short-circuit)
            if intent.intent_type == IntentType.MUSIC_STOP:
                self.logger.info(f"[Iteration {self.interaction_count}] STOP command: Stopping music")
                from core.music_player import get_music_player
                music_player = get_music_player()
                music_player.stop()

                # Optional brief response
                self.sink.speak("Stopped.")
                output_produced = True
                response_text = ""
                self.current_probe.mark("llm_end")
                # Exit callback - continue to next iteration (outer loop)
                _finalize_response_watchdog()
                self._last_utterance_time = time.time()
                return True

            # Check if this is a NEXT command (highest priority - short-circuit)
            if intent.intent_type == IntentType.MUSIC_NEXT:
                self.logger.info(f"[Iteration {self.interaction_count}] NEXT command: Playing next track")
                from core.music_player import get_music_player
                music_player = get_music_player()

                playback_started = music_player.play_next(self.sink)
                if not playback_started:
                    self.sink.speak("No music playing.")
                    self.logger.warning(f"[Iteration {self.interaction_count}] NEXT failed: no playback mode")
                    output_produced = True
                else:
                    self.logger.info(f"[Iteration {self.interaction_count}] NEXT: Started playback")
                    # Monitor for interrupt during music playback
                    self._monitor_music_interrupt(music_player)
                    output_produced = True

                response_text = ""
                self.current_probe.mark("llm_end")
                # Exit callback - continue to next iteration (outer loop)
                _finalize_response_watchdog()
                self._last_utterance_time = time.time()
                return True

            # Check if this is a STATUS query (read-only - no side effects)
            if intent.intent_type == IntentType.MUSIC_STATUS:
                self.logger.info(f"[Iteration {self.interaction_count}] STATUS query: What's playing")
                from core.music_status import query_music_status

                status = query_music_status()
                self.sink.speak(status)
                self.logger.info(f"[Iteration {self.interaction_count}] STATUS response: {status}")
                output_produced = True

                response_text = ""
                self.current_probe.mark("llm_end")
                # Exit callback - continue to next iteration (outer loop)
                _finalize_response_watchdog()
                self._last_utterance_time = time.time()
                return True

            # Check if this is a music command (before LLM processing)
            if intent.intent_type == IntentType.MUSIC:
                # Music playback with STRICT priority routing
                # IMPORTANT: Music commands don't count as conversational turns
                is_music_iteration = True
                self.logger.info(f"[Iteration {self.interaction_count}] Music command - not counting as interaction turn")

                from core.music_player import get_music_player
                music_player = get_music_player()

                playback_started = False
                error_message = ""

                if intent.keyword:
                    keyword = intent.keyword
                    self.logger.info(f"[Iteration {self.interaction_count}] Music keyword: '{keyword}'")

                    # PRIORITY ORDER (FIXED):
                    # 1. Exact artist match
                    if not playback_started:
                        playback_started = music_player.play_by_artist(keyword, None)  # No sink here
                        if playback_started:
                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: ARTIST match")

                    # 2. Exact song match
                    if not playback_started:
                        playback_started = music_player.play_by_song(keyword, None)  # No sink here
                        if playback_started:
                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: SONG match")

                    # 3. Genre match (with adjacent fallback)
                    if not playback_started:
                        playback_started = music_player.play_by_genre(keyword, None)  # No sink here
                        if playback_started:
                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: GENRE match")

                    # 4. Keyword token match
                    if not playback_started:
                        playback_started = music_player.play_by_keyword(keyword, None)  # No sink here
                        if playback_started:
                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: KEYWORD match")

                    # If still no playback, consolidate error into single message
                    if not playback_started:
                        error_message = f"No music found for '{keyword}'."
                        self.logger.warning(f"[Iteration {self.interaction_count}] Music failed: {error_message}")
                else:
                    # No keyword: random track
                    self.logger.info(f"[Iteration {self.interaction_count}] Music route: RANDOM (no keyword)")
                    playback_started = music_player.play_random(None)  # No sink here
                    if not playback_started:
                        error_message = "No music available."
                        self.logger.warning(f"[Iteration {self.interaction_count}] Music failed: {error_message}")

                response_text = ""  # No LLM response for music

                # Speak error message only once (if no playback started)
                if error_message and not playback_started:
                    self.sink.speak(error_message)
                    output_produced = True

                # Monitor for interrupt during music playback
                if playback_started:
                    self.logger.info(f"[Iteration {self.interaction_count}] Monitoring for interrupt during music...")
                    self._monitor_music_interrupt(music_player)
                    output_produced = True

                self.current_probe.mark("llm_end")
            else:
                # Normal LLM response (watchdog-protected)
                with Watchdog("LLM", LLM_WATCHDOG_SECONDS) as llm_wd:
                    response_text = self.generator.generate(intent, self.memory)
                if llm_wd.triggered:
                    self.logger.warning("[WATCHDOG] LLM exceeded watchdog; using fallback response")
                    response_text = WATCHDOG_FALLBACK_RESPONSE
                self.current_probe.mark("llm_end")

            # PHASE 16: Capture for observer snapshot
            self._last_response = response_text

            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Response: '{response_text}'"
            )
            self.last_response_text = response_text

            # If DEVELOP intent produced code, write/open in sandbox
            if intent.intent_type == IntentType.DEVELOP:
                code_block = self._extract_code_block(response_text)
                if code_block:
                    filename = self._infer_sandbox_filename(text, response_text)
                    self.builder.write_script(filename, code_block)
                    self.builder.open_in_vscode(filename)
                    self._last_built_script = filename
                    response_text = self._strip_code_blocks(response_text)

            # 5. Speak response (with interrupt-on-voice support)
            self.logger.info(
                f"[Iteration {self.interaction_count}] Speaking response..."
            )

            # TASK 15: Mark TTS start
            self.current_probe.mark("tts_start")

            # Only speak if response is not empty (music playback has empty response)
            if response_text and response_text.strip():
                streamed_output = bool(getattr(self.generator, "_streamed_output", False))
                if streamed_output:
                    self.logger.debug("[TTS] Streaming enabled; skipping duplicate speak")
                    output_produced = True
                else:
                    # TASK 17: Set speaking flag (half-duplex audio gate)
                    self._is_speaking.set()
                    try:
                        # Speak and monitor for user interrupt (voice input during playback)
                        with Watchdog("TTS", TTS_WATCHDOG_SECONDS) as tts_wd:
                            self._speak_with_interrupt_detection(response_text)
                        if tts_wd.triggered:
                            self.logger.warning("[WATCHDOG] TTS exceeded watchdog threshold")
                        output_produced = True
                    finally:
                        self._is_speaking.clear()
            else:
                self.logger.info(
                    f"[Iteration {self.interaction_count}] "
                    f"Response is empty, skipping TTS"
                )

            # TASK 15: Mark TTS end
            self.current_probe.mark("tts_end")

            self.logger.info(
                f"[Iteration {self.interaction_count}] Response spoken"
            )

            # 6. Store in SessionMemory (v4)
            self.logger.info(
                f"[Iteration {self.interaction_count}] Storing in memory..."
            )
            self.memory.append(
                user_utterance=text,
                parsed_intent=intent.intent_type.value,
                generated_response=response_text
            )
            self.logger.info(
                f"[Iteration {self.interaction_count}] "
                f"Memory updated: {self.memory}"
            )

            # 7. Check for stop keyword in response
            response_lower = response_text.lower()
            for keyword in self.STOP_KEYWORDS:
                if keyword in response_lower:
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] "
                        f"Stop keyword detected: '{keyword}'"
                    )
                    self.stop_requested = True
                    break

            # TASK 15: Log interaction latency and add to stats
            self.current_probe.log_summary()
            self.latency_stats.add_probe(self.current_probe)

            _finalize_response_watchdog()

            if is_music_iteration:
                self.interaction_count -= 1
                self.logger.info(
                    f"[Iteration] Music iteration complete - decremented counter to {self.interaction_count}"
                )

            self._last_utterance_time = time.time()
            return True

        except Exception as e:
            self.logger.error(
                f"[Iteration {self.interaction_count}] Failed: {e}"
            )
            raise
        finally:
            self._is_processing.clear()
    
    def run(self) -> None:
        """
        Run bounded interaction loop with session memory.
        
        Behavior (v4 — differs from v3):
        - Loop until stop condition or max interactions
        - Each iteration: wake → record → transcribe → parse → generate → speak → store
        - After each iteration: check for stop keyword or max reached
        - SessionMemory passed to ResponseGenerator (read-only)
        - SessionMemory cleared on exit
        - If no stop → loop back to waiting for wake word
        - If stop → exit cleanly
        
        Stop conditions:
        1. Response text contains stop keyword ("stop", "goodbye", "quit", "exit")
        2. Max interactions reached (hardcoded: MAX_INTERACTIONS)
        
        Each iteration:
        1. Wait for wake word (blocking)
        2. Record audio (3-5 seconds)
        3. Transcribe to text (Whisper)
        4. Parse to intent (rules-based)
        5. Generate response (LLM, with SessionMemory available)
        6. Speak response (TTS)
        7. Store in SessionMemory (utterance, intent, response)
        8. Check stop condition
        9. If no stop → continue loop
        10. If stop → break loop
        
        SessionMemory behavior:
        - Append each interaction (utterance, intent, response)
        - Only recent N interactions stored (default 3)
        - Oldest entries automatically evicted when full
        - Cleared on exit (not persistent)
        - ResponseGenerator can read but not modify
        
        This is a blocking call. It loops until stop condition, then returns.
        """
        self.logger.info("[run] Starting Coordinator v4 (interaction loop + session memory)...")
        self.logger.info(f"[run] Max interactions: {self.MAX_INTERACTIONS}")
        self.logger.info(f"[run] Stop keywords: {self.STOP_KEYWORDS}")
        self.logger.info(f"[run] SessionMemory capacity: {self.memory.capacity}")
        
        try:
            # Loop until stop condition
            while not self.stop_requested:
                if self.state_machine.is_asleep:
                    # TASK 17: Skip listening if currently speaking (half-duplex audio gate)
                    if self._is_speaking.is_set():
                        self.logger.info("[Loop] Sleeping but currently speaking; waiting...")
                        time.sleep(0.1)
                        continue

                    def on_trigger_detected():
                        if self._is_processing.is_set():
                            self.logger.info("[Iteration] Trigger ignored: already processing")
                            return
                        self.logger.info("[Wake] Wake word detected")
                        self.state_machine.wake()
                        self._last_utterance_time = time.time()
                        self._play_wake_ack()
                        # Process first interaction immediately using wake pre-roll
                        self._handle_interaction(mark_wake=True)

                    self.logger.info("[Loop] Sleeping - listening for wake word...")
                    self.trigger.on_trigger(on_trigger_detected)
                    if self.stop_requested:
                        break
                    continue

                # Awake state: continuous listening
                if self._last_utterance_time is not None:
                    idle_elapsed = time.time() - self._last_utterance_time
                    if idle_elapsed >= self.idle_sleep_seconds:
                        self.logger.info(
                            f"[Idle] No activity for {idle_elapsed:.1f}s; entering sleep"
                        )
                        self.state_machine.sleep()
                        continue

                # Don't listen while speaking
                if self._is_speaking.is_set():
                    time.sleep(0.05)
                    continue

                # Don't listen while processing a turn
                if self._is_processing.is_set():
                    time.sleep(0.05)
                    continue

                preroll_frames = self._wait_for_speech_start(self.SPEECH_START_POLL_SECONDS)
                if preroll_frames is None:
                    continue

                processed = self._handle_interaction(initial_frames=preroll_frames)
                if not processed:
                    continue

                if self.stop_requested:
                    self.logger.info(f"[Loop] Stop requested by user")
                    break

                # Check if max interactions reached
                if self.interaction_count >= self.MAX_INTERACTIONS:
                    # CRITICAL: Don't exit while music is playing
                    # Music lifecycle must outlive coordinator loop
                    try:
                        from core.music_player import get_music_player
                        music_player = get_music_player()
                        if music_player.is_playing:
                            self.logger.info(
                                f"[Loop] Max interactions reached, but music is playing - continuing loop"
                            )
                            self.logger.info(
                                f"[Loop] Waiting for next command or music to finish..."
                            )
                        else:
                            self.logger.info(
                                f"[Loop] Max interactions ({self.MAX_INTERACTIONS}) reached"
                            )
                            break
                    except Exception as e:
                        self.logger.warning(f"[Loop] Could not check music status: {e} - exiting")
                        break
                else:
                    self.logger.info(
                        f"[Loop] Continuing... "
                        f"({self.MAX_INTERACTIONS - self.interaction_count} "
                        f"interactions remaining)"
                    )
            
            # Loop exited (either stop keyword or max interactions)
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"[Loop] Exiting after {self.interaction_count} interaction(s)")
            if self.stop_requested:
                self.logger.info(f"[Loop] Reason: User requested stop")
            else:
                self.logger.info(f"[Loop] Reason: Max interactions reached")
            
            # Clear memory on exit (v4)
            self.logger.info(f"[Loop] Clearing SessionMemory...")
            self.memory.clear()
            self.logger.info(f"[Loop] SessionMemory cleared: {self.memory}")
            
            # TASK 15: Log aggregated latency report
            self.logger.info(f"{'='*60}")
            self.latency_stats.log_report()
            self.logger.info(f"{'='*60}\n")
            
            self.logger.info("[run] Coordinator v4 complete")
        
        except Exception as e:
            self.logger.error(f"[run] Failed: {e}")
            # Clear memory even on error
            self.memory.clear()
            raise
    
    def stop(self) -> None:
        """Stop the coordinator loop gracefully."""
        self.logger.info("[stop] Stop requested via stop() method")
        self.stop_requested = True
    
    def _record_with_silence_detection(self, initial_frames: Optional[list] = None) -> np.ndarray:
        """
        Record audio with dynamic silence detection and pre-roll buffer.
        
        Enhanced recording logic:
        1. Prepend pre-roll buffer (speech onset captured before wake word)
        2. Enforce minimum record duration (0.9s)
        3. Start silence timer only after speech energy detected (RMS > threshold)
        4. Stop on silence (2.2s) or max duration (15s)
        5. Emit debug metrics (gated by RECORD_DEBUG flag)
        
        Returns:
            numpy array of int16 audio samples at AUDIO_SAMPLE_RATE Hz
        """
        import numpy as np
        import time
        
        # Chunk size for processing (100ms)
        chunk_samples = int(self.AUDIO_SAMPLE_RATE * 0.1)
        min_samples = int(self.AUDIO_SAMPLE_RATE * self.MINIMUM_RECORD_DURATION)
        # Use dynamic silence timeout (updated after each transcription based on query type)
        silence_samples_threshold = int(self.AUDIO_SAMPLE_RATE * self.dynamic_silence_timeout)
        max_samples = int(self.AUDIO_SAMPLE_RATE * self.MAX_RECORDING_DURATION)
        
        audio_buffer = []
        consecutive_silence_samples = 0
        total_samples = 0
        speech_detected = False
        speech_detected_at = None
        silence_started_at = None
        stop_reason = None
        rms_samples = []  # For calculating average RMS (debug metric)
        
        # Get pre-roll buffer (speech onset before wake word) or use provided frames
        preroll_frames = []
        if initial_frames is not None:
            preroll_frames = initial_frames
        else:
            try:
                preroll_frames = self.trigger.get_preroll_buffer()
            except Exception as e:
                self.logger.debug(f"[Record] Could not retrieve pre-roll buffer: {e}")
        
        # Prepend pre-roll buffer to audio
        if preroll_frames:
            for frame in preroll_frames:
                audio_buffer.append(frame)
                total_samples += frame.shape[0]
            if self.record_debug:
                self.logger.info(f"[Record] Pre-roll: {len(preroll_frames)} frames ({total_samples/self.AUDIO_SAMPLE_RATE:.2f}s)")
        
        recording_start_time = time.time()
        stream = None
        try:
            stream = sd.InputStream(
                channels=1,
                samplerate=self.AUDIO_SAMPLE_RATE,
                dtype=np.int16,
            )
            stream.start()
            
            rms = 0.0  # Initialize before loop (defensive: prevents UnboundLocalError in logging)
            
            while total_samples < max_samples:
                if self._is_speaking.is_set():
                    stop_reason = "speaking_gate"
                    if self.record_debug:
                        self.logger.info("[Record] Aborting: speaking gate active")
                    break
                # Read one chunk
                chunk, _ = stream.read(chunk_samples)
                if chunk.size == 0:
                    break
                
                audio_buffer.append(chunk)
                total_samples += chunk.shape[0]
                elapsed_time = time.time() - recording_start_time
                
                # Calculate RMS for this chunk (normalized 0-1)
                rms = np.sqrt(np.mean(chunk.astype(float) ** 2)) / 32768.0  # Normalize int16 range
                rms_samples.append(rms)
                
                # Detect speech (RMS > threshold) — only start silence timer after speech detected
                if not speech_detected and rms > self.RMS_SPEECH_THRESHOLD:
                    speech_detected = True
                    speech_detected_at = elapsed_time
                    if self.record_debug:
                        rms_str = f"{rms:.4f}" if rms is not None else "N/A"
                        self.logger.info(f"[Record] Speech detected at {elapsed_time:.3f}s (RMS={rms_str})")
                
                # Track silence only after speech has been detected
                if speech_detected:
                    if rms < self.SILENCE_THRESHOLD:
                        if silence_started_at is None:
                            silence_started_at = elapsed_time
                        consecutive_silence_samples += chunk.shape[0]
                    else:
                        # Audio detected, reset silence counter
                        consecutive_silence_samples = 0
                        silence_started_at = None
                    
                    # Stop if enough silence detected AND minimum duration reached
                    if (consecutive_silence_samples >= silence_samples_threshold and
                        total_samples >= min_samples):
                        stop_reason = "silence"
                        if self.record_debug:
                            silence_duration = elapsed_time - silence_started_at if silence_started_at else 0
                            self.logger.info(
                                f"[Record] Silence detected ({silence_duration:.2f}s >= {self.SILENCE_TIMEOUT_SECONDS}s), "
                                f"stopping recording ({total_samples/self.AUDIO_SAMPLE_RATE:.2f}s recorded)"
                            )
                        break
                
                # Also stop if max duration reached
                if total_samples >= max_samples:
                    stop_reason = "max_duration"
                    # Guard formatting (belt + suspenders: logging must never crash)
                    avg_rms = np.mean(rms_samples) if rms_samples else 0.0
                    avg_rms_str = f"{avg_rms:.2f}" if avg_rms is not None else "N/A"
                    self.logger.warning(
                        f"[Record] MAX DURATION REACHED (15.0s) - stopping recording | "
                        f"total_samples={total_samples}, avg_rms={avg_rms_str}"
                    )
                    break
        
        except Exception as e:
            self.logger.error(f"[Record] Error during audio recording: {e}")
            raise
        
        finally:
            # Guarantee stream cleanup even on exception or cancellation
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    self.logger.warning(f"[Record] Error closing stream: {e}")
        
        # Emit debug metrics (gated by RECORD_DEBUG flag)
        if self.record_debug and rms_samples:
            avg_rms = np.mean(rms_samples)
            avg_rms_str = f"{avg_rms:.4f}" if avg_rms is not None else "N/A"
            self.logger.info(f"[Record] Recording Summary:")
            self.logger.info(f"  Duration: {total_samples/self.AUDIO_SAMPLE_RATE:.2f}s (minimum: {self.MINIMUM_RECORD_DURATION}s)")
            self.logger.info(f"  RMS average: {avg_rms_str} (normalized 0-1, threshold: {self.RMS_SPEECH_THRESHOLD})")
            self.logger.info(f"  Speech detected at: {speech_detected_at:.3f}s" if speech_detected_at else "  Speech: NOT detected")
            self.logger.info(f"  Stop reason: {stop_reason}")
            self.logger.info(f"  Silence threshold: {self.SILENCE_THRESHOLD} (absolute RMS)")
            self.logger.info(f"  Silence timeout: {self.SILENCE_TIMEOUT_SECONDS}s")
            if self._last_transcript:
                self.logger.info(f"  Transcript: '{self._last_transcript}'")
        
        # Concatenate all chunks
        if audio_buffer:
            return np.concatenate(audio_buffer, axis=0)
        else:
            return np.array([], dtype=np.int16)
    
    def _monitor_music_interrupt(self, music_player) -> None:
        """
        Monitor for user interrupt during music playback.
        
        If user speaks/wakes word detected, stop music immediately.
        
        IMPORTANT: Reuses existing trigger instance (self.trigger) instead of
        creating a new PorcupineWakeWordTrigger to avoid re-initialization overhead.
        
        Args:
            music_player: MusicPlayer instance to stop on interrupt
        """
        import time
        
        try:
            self.logger.info("[Music] Monitoring for interrupt...")
            
            # Poll while music is playing
            while music_player.is_playing:
                try:
                    # Reuse existing trigger instance to check for interrupt
                    if self.trigger._check_for_interrupt():
                        self.logger.warning("[Music] User interrupted! Stopping music...")
                        music_player.stop()
                        break
                except Exception as e:
                    self.logger.debug(f"[Music] Interrupt check failed: {e}")
                
                time.sleep(0.2)  # Check every 200ms
        
        except Exception as e:
            self.logger.error(f"[Music] Monitor error: {e}")

    def _extract_code_block(self, text: str) -> Optional[str]:
        """Extract the first fenced code block from text."""
        if not text:
            return None
        match = re.search(r"```(?:python)?\n([\s\S]*?)```", text, flags=re.IGNORECASE)
        if not match:
            return None
        code = match.group(1).strip("\n")
        return code or None

    def _strip_code_blocks(self, text: str) -> str:
        """Remove fenced code blocks from text for speech output."""
        if not text:
            return text
        stripped = re.sub(r"```[\s\S]*?```", "", text).strip()
        return stripped

    def _infer_sandbox_filename(self, user_text: str, response_text: str) -> str:
        """Infer a sandbox filename from user request or response."""
        match = re.search(r"([a-zA-Z0-9_\-]+\.py)", response_text)
        if match:
            return match.group(1)
        match = re.search(r"([a-zA-Z0-9_\-]+\.py)", user_text)
        if match:
            return match.group(1)

        lowered = user_text.lower()
        if "storage" in lowered or "disk" in lowered or "space" in lowered:
            return "storage_check.py"
        if "cpu" in lowered or "monitor" in lowered:
            return "cpu_monitor.py"
        return "sandbox_tool.py"

    def _similarity_ratio(self, a: str, b: str) -> float:
        """Compute similarity ratio using Levenshtein distance."""
        if not a or not b:
            return 0.0
        a_norm = a.strip().lower()
        b_norm = b.strip().lower()
        if a_norm == b_norm:
            return 1.0
        dist = self._levenshtein_distance(a_norm, b_norm)
        max_len = max(len(a_norm), len(b_norm))
        if max_len == 0:
            return 0.0
        return 1.0 - (dist / max_len)

    @staticmethod
    def _levenshtein_distance(a: str, b: str) -> int:
        """Compute Levenshtein distance between two strings."""
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev_row = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            curr_row = [i]
            for j, cb in enumerate(b, start=1):
                insert_cost = curr_row[j - 1] + 1
                delete_cost = prev_row[j] + 1
                replace_cost = prev_row[j - 1] + (0 if ca == cb else 1)
                curr_row.append(min(insert_cost, delete_cost, replace_cost))
            prev_row = curr_row
        return prev_row[-1]

    
    def _speak_with_interrupt_detection(self, response_text: str) -> None:
        """
        Speak response WITHOUT interrupt detection (Option A: simplest).
        
        Argo should NOT interrupt itself during TTS playback.
        This matches standard assistant behavior (Alexa, Siri, Google Assistant).
        
        Runs TTS in main thread (blocking).
        Disables interrupt monitoring during playback to prevent Argo self-interruption.
        Re-enables after playback finishes.
        
        Args:
            response_text: Text to speak
        """
        try:
            self.logger.info("[TTS] Speaking response (interrupts disabled during playback)...")
            
            # Speak in main thread (blocking, event loop-safe)
            # IMPORTANT: Do NOT monitor for interrupts while Argo is speaking
            # This prevents Argo from interrupting itself with its own audio
            self.sink.speak(response_text)
            
            self.logger.info("[TTS] Response finished")
        
        except Exception as e:
            self.logger.error(f"[TTS] Error during speech: {e}")
        
        finally:
            # Ensure speaking flag is cleared even if exception occurred
            self._is_speaking.clear()
