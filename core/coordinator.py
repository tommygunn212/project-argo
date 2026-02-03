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

# ============================================================================
# 1) IMPORTS
# ============================================================================
import logging
import threading
import queue
import time
import re
from typing import Optional
from datetime import datetime
import sounddevice as sd
import numpy as np
import warnings

# Suppress sounddevice Windows cffi warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="sounddevice")

from core.intent_parser import Intent, IntentType, normalize_system_text, is_system_keyword
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
from core.audio_owner import get_audio_owner
from core.config import get_config, get_runtime_overrides, set_runtime_override, clear_runtime_overrides
from system_health import (
    get_system_health,
    get_memory_info,
    get_temperatures,
    get_temperature_health,
    get_disk_info,
    get_system_full_report,
)
from system_profile import get_system_profile, get_gpu_profile

# === INSTRUMENTATION: Defensive import wrapper ===
try:
    from core.instrumentation import log_event as log_event_impl, log_latency
except Exception as e:
    # Telemetry can NEVER crash ARGO. Graceful degradation to stdout.
    logger_fallback = logging.getLogger(__name__)
    logger_fallback.warning(f"[Instrumentation] Failed to import: {e}. Degrading to stdout.")
    
    def log_event_impl(message: str) -> None:
        """Fallback: print to stdout instead of telemetry."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] {message}")
    
    def log_latency(stage: str, duration: Optional[float] = None) -> None:
        """Fallback: no-op for latency logging."""
        pass

# === Logging ===
logger = logging.getLogger(__name__)


# === INSTRUMENTATION: Use imported or fallback log_event ===
log_event = log_event_impl


# ============================================================================
# 2) COORDINATOR
# ============================================================================
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

    AUDIO_STATE_IDLE = "IDLE"
    AUDIO_STATE_LISTENING = "LISTENING"
    AUDIO_STATE_SPEAKING = "SPEAKING"

    ALLOWED_TRANSITIONS = {
        "SLEEP": {"LISTENING"},
        "LISTENING": {"THINKING"},
        "THINKING": {"SPEAKING"},
        "SPEAKING": {"LISTENING"},
    }
    
    # Audio recording parameters
    AUDIO_SAMPLE_RATE = 16000  # Hz
    MAX_RECORDING_DURATION = 15.0  # seconds max
    MIN_RECORDING_DURATION = 0.9  # Minimum record duration
    SILENCE_DURATION = 2.2  # Seconds of silence to stop recording
    MINIMUM_RECORD_DURATION = 0.9  # Minimum record duration
    SILENCE_TIMEOUT_SECONDS = 2.2  # Seconds of silence to stop recording
    SILENCE_THRESHOLD = 250  # Audio level below this = silence (RMS absolute)
    RMS_SPEECH_THRESHOLD = 0.0005  # RMS normalized level (0-1) to START silence timer — LOWERED to 0.0005 for weak Brio signal
    PRE_ROLL_BUFFER_MS_MIN = 1000  # Min milliseconds of pre-speech audio to capture — 1 second pre-wake context
    PRE_ROLL_BUFFER_MS_MAX = 1200  # Max milliseconds to keep in rolling buffer — 1.2 second look-back
    
    # Debug/profiling flags
    RECORD_DEBUG = True  # Set to True for detailed recording metrics (or via env var)
    
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
        self._low_conf_notice_given = False

        # Runtime overrides (non-persistent)
        self.runtime_overrides = get_runtime_overrides()
        self.next_interaction_overrides = {}

        # Illegal transition callback (optional UI hook)
        self.on_illegal_transition = None

        # Audio ownership (single authority)
        self.audio_owner = get_audio_owner()
        self._audio_owner_lock = threading.Lock()
        
        # Load config and lock microphone device
        config = get_config()
        self.input_device_index = config.get("audio.input_device_index", None)
        self.logger.info(f"[Init] Audio input device locked to index: {self.input_device_index} (M-Track)")
        # Ensure global output sink uses this instance (streaming uses get_output_sink)
        try:
            from core.output_sink import set_output_sink
            set_output_sink(self.sink)
        except Exception:
            pass
        
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
        self._tts_gate_active = threading.Event()
        self._tts_gate_active.clear()
        
        # Debug/profiling flag from environment (can override class default)
        self.record_debug = os.getenv("RECORD_DEBUG", "").lower() == "true" or self.RECORD_DEBUG
        
        # GUI Callbacks (optional, can be set by external GUI)
        self.on_recording_start = None
        self.on_recording_stop = None
        self.on_status_update = None
        
        # Loop state (v3)
        self.interaction_count = 0
        self.stop_requested = False

        # Wake event queue (Porcupine callback enqueues, main loop handles)
        self._wake_event_queue = queue.SimpleQueue()
        self._wake_listener_thread = None

        # HARDENING STEP 1: Monotonic interaction ID (prevents zombie callbacks)
        self.interaction_id = 0
        self._last_mic_open_interaction_id = None

        # Python builder actuator (sandbox tools)
        self.builder = PythonBuilder()
        self._last_built_script: Optional[str] = None
        self.last_response_text: Optional[str] = None
        self._response_committed = False
        self._response_interaction_id: Optional[int] = None

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

        # Audio state machine (strict half-duplex)
        self._audio_state = self.AUDIO_STATE_LISTENING
        self._audio_state_lock = threading.Lock()
        self._input_stream = None
        self._input_stream_active = False
        self._input_stop_event = threading.Event()

        # Hard half-duplex gate via output sink (pause/resume wake word)
        if hasattr(self.sink, "set_playback_hooks"):
            try:
                self.sink.set_playback_hooks(
                    on_playback_start=self._pause_trigger_for_tts,
                    on_playback_complete=self._resume_trigger_after_tts,
                )
            except Exception as e:
                self.logger.debug(f"[Coordinator] Failed to set playback hooks: {e}")

        self._set_audio_state(self.AUDIO_STATE_LISTENING)
    
    def _next_interaction_id(self) -> int:
        """
        DEPRECATED: This method violates the contract.
        
        CONTRACT: interaction_id increments ONLY in wake handler.
        Any other increment is a fatal violation.
        
        Calling this method is forbidden. Use self.interaction_id directly.
        """
        raise RuntimeError(
            "FATAL: _next_interaction_id() called. Contract violation: "
            "interaction_id increments ONLY in wake handler (_handle_wake_event). "
            "Any other increment is fatal."
        )

    def set_next_override(self, key: str, value) -> None:
        self.next_interaction_overrides[key] = value
        log_event(f"NEXT_OVERRIDE_SET {key}={value}")

    def clear_next_overrides(self) -> None:
        self.next_interaction_overrides.clear()
        log_event("NEXT_OVERRIDE_CLEARED")
    
    def _assert_no_id_reuse(self, new_id: int) -> None:
        """
        FIX 1: Assertion - fatal if interaction_id reuses or decreases.
        Every MIC OPEN must have a new, strictly increasing ID.
        
        Args:
            new_id: The interaction_id for the upcoming MIC OPEN
            
        Raises:
            RuntimeError: If ID reuse or decrease detected
        """
        if new_id <= self._last_mic_open_id:
            error_msg = f"FATAL: Interaction ID violation - new_id={new_id}, last_mic_open_id={self._last_mic_open_id} (must strictly increase)"
            self.logger.error(f"[Assert] {error_msg}")
            raise RuntimeError(error_msg)
        
        # Update last seen ID
        self._last_mic_open_id = new_id
        self.logger.debug(f"[Assert] Interaction ID verified: {new_id} > {self._last_mic_open_id - 1}")

    def _assert_no_interaction_id_reuse(self):
        if not hasattr(self, "_last_mic_open_interaction_id"):
            self._last_mic_open_interaction_id = None

        current_id = self.interaction_id

        if self._last_mic_open_interaction_id is not None:
            if current_id <= self._last_mic_open_interaction_id:
                raise RuntimeError(
                    f"FATAL: interaction_id reuse detected "
                    f"(current={current_id}, last={self._last_mic_open_interaction_id})"
                )

        self._last_mic_open_interaction_id = current_id
    
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
            self.logger.info(f"[SmartTiming] Quick query detected: '{transcribed_text[:50]}' -> 1.0s timeout")
            return 1.0
        
        # If it's a story or explanation, be patient
        self.logger.info(f"[SmartTiming] Detailed query detected: '{transcribed_text[:50]}' -> 5.0s timeout")
        return 5.0

    def _on_state_change(self, old_state: State, new_state: State) -> None:
        """Handle state changes (optional GUI updates)."""
        self.logger.info(f"[State] {old_state.value} -> {new_state.value}")
        
        # INSTRUMENTATION: Log state transition
        log_event(f"STATE_CHANGE {old_state.value} -> {new_state.value}")
        
        # HARDENING STEP 6: Assert trigger state matches state machine
        try:
            self._assert_trigger_state(new_state)
        except AssertionError as e:
            self.logger.error(f"[State] ASSERTION FAILED: {e}")
            self.stop_requested = True
        except Exception as e:
            self.logger.warning(f"[State] Error validating trigger state: {e}")
        
        if self.on_status_update:
            try:
                self.on_status_update(new_state.value)
            except Exception as e:
                self.logger.debug(f"[Coordinator] on_status_update error: {e}")

    def _safe_transition(self, action, next_state: State, source: str, interaction_id: str = "") -> bool:
        prev_state = self.state_machine.current_state
        try:
            return action()
        except RuntimeError:
            payload = {
                "from": prev_state.value,
                "to": next_state.value,
                "allowed": list(self.ALLOWED_TRANSITIONS.get(prev_state.value, set())),
                "source": source,
                "interaction_id": interaction_id,
            }
            log_event(
                f"ILLEGAL_TRANSITION {prev_state.value}->{next_state.value} source={source}",
                stage="state",
                interaction_id=interaction_id,
            )
            if self.on_illegal_transition:
                try:
                    self.on_illegal_transition(payload)
                except Exception:
                    pass
            self.stop_requested = True
            return False

    def _assert_trigger_state(self, state: State) -> None:
        """
        HARDENING STEP 6: Assert that InputTrigger state matches StateMachine state.
        
        Contract enforcement:
        - When LISTENING: Trigger must be ACTIVE (listening for wake word)
        - When not LISTENING: Trigger must be PAUSED (not consuming CPU/audio)
        
        If assertion fails, raises AssertionError (fatal).
        
        Args:
            state: Current state from state machine
            
        Raises:
            AssertionError: If trigger state doesn't match expected state
        """
        try:
            # Check if trigger has state methods
            if not hasattr(self.trigger, 'is_active') or not hasattr(self.trigger, 'is_paused'):
                self.logger.debug("[Assert] Trigger doesn't support state checks, skipping")
                return
            
            if state == State.LISTENING:
                # In LISTENING state: trigger should be ACTIVE
                assert self.trigger.is_active(), \
                    f"LISTENING but trigger.is_active()={self.trigger.is_active()} (expected True)"
                self.logger.debug("[Assert] LISTENING: trigger is ACTIVE ✓")
            else:
                # In other states: trigger should be PAUSED
                assert self.trigger.is_paused(), \
                    f"{state.value} but trigger.is_paused()={self.trigger.is_paused()} (expected True)"
                self.logger.debug(f"[Assert] {state.value}: trigger is PAUSED ✓")
        except AssertionError as e:
            self.logger.error(f"[Assert] FATAL: Trigger state contract violated: {e}")
            raise

    def _pause_trigger_for_tts(self) -> None:
        """
        Pause recording during TTS (but keep wake word detector active for barge-in).
        
        IMPORTANT: Wake word detector remains running so user can interrupt with wake word.
        Only the recorder/microphone input is gated off.
        This enables hard barge-in interrupt.
        """
        self._set_audio_state(self.AUDIO_STATE_SPEAKING)
        # DO NOT call _stop_input_audio() - keep trigger listening for barge-in!
        # Only pause/gate the recorder, not the wake-word detector
        if hasattr(self.trigger, 'pause'):
            try:
                self.trigger.pause()
            except Exception:
                pass
        self._is_speaking.set()
        self._tts_gate_active.set()

    def _resume_trigger_after_tts(self) -> None:
        """Resume wake-word detection when audio queue drains and playback is idle."""
        if self.stop_requested:
            return
        self._resume_input_audio("tts_playback_complete")
        self._set_audio_state(self.AUDIO_STATE_LISTENING)
        self._is_speaking.clear()
        self._tts_gate_active.clear()

    def _set_audio_state(self, new_state: str) -> None:
        with self._audio_state_lock:
            old_state = self._audio_state
            if old_state == new_state:
                return
            self._audio_state = new_state
        self.logger.info(f"[AudioState] {old_state} -> {new_state}")

    def acquire_audio(self, owner: str) -> None:
        with self._audio_owner_lock:
            current_owner = self.audio_owner.get_owner()
            if current_owner and current_owner != owner:
                log_event(f"AUDIO_CONTESTED owner={current_owner} requested={owner}")
                raise RuntimeError("Audio already owned")
            self.audio_owner.acquire(owner)
            log_event(f"AUDIO_ACQUIRED owner={owner}")

    def release_audio(self, owner: str) -> None:
        with self._audio_owner_lock:
            if self.audio_owner.get_owner() == owner:
                self.audio_owner.release(owner)
                log_event(f"AUDIO_RELEASED owner={owner}")

    def force_release_audio(self, reason: str = "") -> None:
        with self._audio_owner_lock:
            prior = self.audio_owner.get_owner()
            if prior:
                self.audio_owner.force_release(reason)
                log_event(f"AUDIO_FORCED_RELEASE prior={prior} reason={reason}")

    def enqueue_wake_event(self) -> None:
        """Enqueue a wake event from the Porcupine callback (thread-safe)."""
        self._wake_event_queue.put(time.time())

    def _start_wake_listener(self) -> None:
        """Start the Porcupine listener thread (runs continuously)."""
        if self._wake_listener_thread and self._wake_listener_thread.is_alive():
            return

        def on_trigger_detected() -> None:
            try:
                self.enqueue_wake_event()
            except Exception as e:
                self.logger.error(f"[Wake] Failed to enqueue wake event: {e}")

        listener_thread = threading.Thread(
            target=self.trigger.on_trigger,
            args=(on_trigger_detected,),
            daemon=True,
            name="PorcupineWakeListener",
        )
        listener_thread.start()
        self._wake_listener_thread = listener_thread

    def _handle_wake_event(self) -> None:
        """
        Handle a queued wake event on the main coordinator thread.
        Owns state transitions, interaction ID increment, and recording start.
        """
        # INSTRUMENTATION: Log wake word detection
        log_event(f"WAKE_WORD detected (state={self.state_machine.current_state.value})")

        if self._is_processing.is_set():
            self.logger.info("[Wake] Already processing, ignoring wake event")
            return

        if self._is_speaking.is_set():
            self.logger.info("[Wake] BARGE-IN: Wake word detected while speaking")
            log_event("BARGE_IN start")

            try:
                self.force_release_audio("BARGE_IN")
                log_event("AUDIO KILLED")
                self.logger.info("[Wake] Audio authority hard-killed output")
            except Exception as e:
                self.logger.warning(f"[Wake] Error hard-killing output: {e}")

            try:
                self.sink.stop_interrupt()
                self.logger.info("[Wake] TTS stopped synchronously")
            except Exception as e:
                self.logger.warning(f"[Wake] Error stopping TTS: {e}")

            self._is_speaking.clear()

            try:
                self._safe_transition(
                    self.state_machine.listening,
                    State.LISTENING,
                    source="audio",
                    interaction_id=str(self.interaction_id),
                )
                log_event("STATE_CHANGE SPEAKING -> LISTENING (barge-in)")
                self.logger.info("[State] SPEAKING -> LISTENING (barge-in)")
            except RuntimeError as e:
                self.logger.error(f"[Wake] FATAL: Invalid state transition: {e}")
                self.stop_requested = True
                return
            except Exception as e:
                self.logger.warning(f"[Wake] Error setting LISTENING state: {e}")
        else:
            # Normal wake when not speaking
            try:
                if self.state_machine.is_asleep:
                    self._safe_transition(
                        self.state_machine.wake,
                        State.LISTENING,
                        source="audio",
                        interaction_id=str(self.interaction_id),
                    )
            except RuntimeError as e:
                self.logger.error(f"[Wake] FATAL: Invalid state transition: {e}")
                self.stop_requested = True
                return
            except Exception as e:
                self.logger.warning(f"[Wake] Error waking from sleep: {e}")
                return

        # LISTENING entry: increment interaction ID and validate
        self.interaction_id += 1
        self._assert_no_interaction_id_reuse()

        self._last_utterance_time = time.time()
        self._play_wake_ack()
        # Process first interaction immediately using wake pre-roll
        self._handle_interaction(mark_wake=True)

    def _is_input_active(self) -> bool:
        if self._input_stream_active:
            return True
        if hasattr(self.trigger, "is_listening") and self.trigger.is_listening():
            return True
        if hasattr(self.trigger, "is_stream_active") and self.trigger.is_stream_active():
            return True
        return False

    def _stop_input_audio(self, reason: str) -> None:
        self._input_stop_event.set()
        if self._input_stream is not None:
            try:
                if hasattr(self._input_stream, "abort"):
                    self._input_stream.abort()
                if self._input_stream.active:
                    self._input_stream.stop()
            except Exception:
                pass
            try:
                self._input_stream.close()
            except Exception:
                pass
            self._input_stream = None
            self._input_stream_active = False
        try:
            from voice_input import stop_continuous_audio_stream
            stop_continuous_audio_stream()
        except Exception:
            pass
        if hasattr(self.trigger, "hard_stop"):
            try:
                self.trigger.hard_stop()
            except Exception:
                pass
        self.logger.info(f"[AudioState] Input stopped ({reason})")

    def _resume_input_audio(self, reason: str) -> None:
        self._input_stop_event.clear()
        if hasattr(self.trigger, "hard_resume"):
            try:
                self.trigger.hard_resume()
            except Exception:
                pass
        try:
            from voice_input import start_continuous_audio_stream
            start_continuous_audio_stream()
        except Exception:
            pass
        self.logger.info(f"[AudioState] Input resumed ({reason})")

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

    def _barge_in(self) -> None:
        """
        DEPRECATED: Use _handle_wake_event() on the main coordinator thread.
        """
        self._handle_wake_event()

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
            if self._audio_state == self.AUDIO_STATE_SPEAKING:
                return None
            stream = sd.InputStream(
                channels=1,
                samplerate=self.AUDIO_SAMPLE_RATE,
                dtype=np.int16,
                device=self.input_device_index,
            )
            self._input_stream = stream
            self._input_stream_active = True
            stream.start()

            while True:
                if self._input_stop_event.is_set() or self._audio_state == self.AUDIO_STATE_SPEAKING:
                    return None
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
            self._input_stream = None
            self._input_stream_active = False

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

        overrides = dict(self.next_interaction_overrides)
        if overrides:
            log_event(f"NEXT_INTERACTION_OVERRIDES_APPLIED {overrides}")
        self.next_interaction_overrides.clear()

        try:
            # Half-duplex: abort if speaking
            if self._is_speaking.is_set():
                self.logger.info("[Iteration] Skipping interaction: currently speaking")
                self.interaction_count -= 1
                return False
            self._is_processing.set()
            current_owner = self.audio_owner.get_owner()
            if current_owner and not overrides.get("force_passive_listening"):
                log_event(f"STT_BLOCKED_AUDIO_OWNER owner={current_owner}")
                self.interaction_count -= 1
                return False
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

            # PHASE 2A: TRANSCRIPT TRUTH - Log EXACT raw Whisper output
            # No lowercasing, no cleanup, no token filtering
            # This is the unmodified truth from Whisper
            self.logger.info(f"[STT RAW] '{text}'")

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

            if overrides.get("force_passive_listening"):
                self.logger.info(
                    f"[Iteration {self.interaction_count}] Passive listening override active; skipping intent/command"
                )
                return False

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
                # HARDENING STEP 2: Pass interaction_id to prevent zombie callbacks
                self._safe_speak(response_text, interaction_id=self.interaction_id)
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

            # Early STT quality guard (quality-of-life)
            stt_metrics = None
            try:
                stt_metrics = self.stt.get_last_metrics()
            except Exception:
                stt_metrics = None
            stt_conf = 0.0
            if stt_metrics:
                try:
                    stt_conf = float(stt_metrics.get("confidence", 0.0))
                except Exception:
                    stt_conf = 0.0
            normalized_text = normalize_system_text(text)
            if normalized_text != text:
                text = normalized_text
            if stt_conf < 0.35 or not text.strip():
                if is_system_keyword(text):
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] Low STT confidence ({stt_conf:.2f}) but whitelisted system intent: {text}"
                    )
                elif re.search(r"\bcount\b", text, flags=re.IGNORECASE):
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] Low STT confidence ({stt_conf:.2f}) but count detected; continuing"
                    )
                elif stt_conf < 0.10 or not text.strip():
                    self.logger.info(
                        f"[Iteration {self.interaction_count}] Low STT confidence ({stt_conf:.2f}); skipping"
                    )
                    if not self._low_conf_notice_given and self.runtime_overrides.get("tts_enabled", True):
                        self._safe_speak("I didn’t catch that clearly. Try saying it as a full sentence.", interaction_id=self.interaction_id)
                        self._low_conf_notice_given = True
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

            # Command confidence gate (STT quality)
            stt_metrics = None
            try:
                stt_metrics = self.stt.get_last_metrics()
            except Exception:
                stt_metrics = None
            confidence_threshold = get_config().get("speech_to_text.command_confidence_threshold", 0.35)

            # Determine if this is a canonical/deterministic or procedural command
            is_canonical_or_deterministic = intent.intent_type in {
                IntentType.COMMAND,
                IntentType.COUNT,
                IntentType.MUSIC,
                IntentType.MUSIC_NEXT,
                IntentType.MUSIC_STOP,
                IntentType.MUSIC_STATUS,
                IntentType.SYSTEM_HEALTH,
                IntentType.SYSTEM_INFO,
                IntentType.APP_CONTROL,
                IntentType.ARGO_IDENTITY,
                IntentType.ARGO_GOVERNANCE,
            } or self.executor.can_execute(text)

            # TTS bypass reason constant
            TTS_ALLOWED_REASON_DETERMINISTIC = "DETERMINISTIC_CONFIDENCE_BYPASS"

            # Only apply STT confidence gate to LLM queries and unknown intents
            if stt_metrics:
                stt_conf = float(stt_metrics.get("confidence", 0.0))
                if stt_conf < confidence_threshold:
                    if is_canonical_or_deterministic:
                        # Log bypass for deterministic commands
                        self.logger.info(
                            f"[TTS] Allowed despite low STT confidence "
                            f"(reason={TTS_ALLOWED_REASON_DETERMINISTIC}, "
                            f"confidence={stt_conf:.2f}, intent={intent.intent_type.value})"
                        )
                    else:
                        msg = "Query suppressed — low STT confidence"
                        self.logger.warning(
                            f"[Iteration {self.interaction_count}] {msg} (conf={stt_conf:.2f} < {confidence_threshold:.2f})"
                        )
                        log_event(f"QUERY_SUPPRESSED_LOW_STT conf={stt_conf:.2f} threshold={confidence_threshold:.2f}", stage="stt")
                        if self.runtime_overrides.get("tts_enabled", True):
                            self._safe_speak(msg, interaction_id=self.interaction_id)
                        self.current_probe.mark("llm_end")
                        self.current_probe.mark("tts_start")
                        self.current_probe.mark("tts_end")
                        self.current_probe.log_summary()
                        self.latency_stats.add_probe(self.current_probe)
                        return True

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
                            self._safe_speak(WATCHDOG_FALLBACK_RESPONSE)
                            output_produced = True
                        except Exception:
                            pass
                    # Reset to safe idle state
                    self.stop_requested = False
                    self._is_speaking.clear()

            if intent.intent_type == IntentType.SLEEP:
                self.logger.info(f"[Iteration {self.interaction_count}] Sleep command detected")
                try:
                    self._safe_speak("Going quiet.")
                    output_produced = True
                except Exception:
                    pass
                self._safe_transition(
                    self.state_machine.sleep,
                    State.SLEEP,
                    source="ui",
                    interaction_id=str(self.interaction_id),
                )
                self._last_utterance_time = time.time()
                self.current_probe.mark("llm_end")
                self.current_probe.mark("tts_start")
                self.current_probe.mark("tts_end")
                self.current_probe.log_summary()
                self.latency_stats.add_probe(self.current_probe)
                _finalize_response_watchdog()
                return True

            if intent.intent_type == IntentType.COUNT:
                self.logger.info(f"[Iteration {self.interaction_count}] Count command detected")
                response_text = self._build_count_response(text)
                try:
                    self._safe_speak(response_text, interaction_id=self.interaction_id)
                    output_produced = True
                except Exception:
                    pass
                self._last_utterance_time = time.time()
                self.current_probe.mark("llm_end")
                self.current_probe.mark("tts_start")
                self.current_probe.mark("tts_end")
                self.current_probe.log_summary()
                self.latency_stats.add_probe(self.current_probe)
                _finalize_response_watchdog()
                return True

            if intent.intent_type == IntentType.SYSTEM_HEALTH:
                self.logger.info(f"[Iteration {self.interaction_count}] System health command detected")
                subintent = getattr(intent, "subintent", None)
                raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
                bypass_llm = False
                if "drive" in raw_text_lower or "disk" in raw_text_lower:
                    bypass_llm = True
                    if subintent is None:
                        subintent = "disk"
                if bypass_llm:
                    self.logger.info("[SYSTEM] Disk query detected; bypassing LLM")
                if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
                    disks = get_disk_info()
                    if not disks:
                        response_text = "Hardware information unavailable."
                    else:
                        drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
                        if not drive_match:
                            drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
                        if drive_match:
                            letter = drive_match.group(1).upper()
                            key = f"{letter}:"
                            info = disks.get(key) or disks.get(letter)
                            if info:
                                response_text = (
                                    f"{letter} drive is {info['percent']} percent full, "
                                    f"with {info['free_gb']} gigabytes free."
                                )
                            else:
                                response_text = "Hardware information unavailable."
                        elif "fullest" in raw_text_lower or "most used" in raw_text_lower:
                            disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
                            response_text = f"{disk} is the fullest drive at {info['percent']} percent used."
                        elif "most free" in raw_text_lower or "most space" in raw_text_lower:
                            disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
                            response_text = f"{disk} has the most free space at {info['free_gb']} gigabytes free."
                        else:
                            total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
                            response_text = f"You have {total_free} gigabytes free across {len(disks)} drives."
                elif subintent == "full":
                    report = get_system_full_report()
                    response_text = self._format_system_full_report(report)
                elif subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
                    profile = get_system_profile()
                    gpus = get_gpu_profile()
                    wants_specs = "spec" in raw_text_lower or "detail" in raw_text_lower
                    if subintent == "memory":
                        ram_gb = profile.get("ram_gb") if profile else None
                        if wants_specs and profile:
                            speed = profile.get("memory_speed_mhz")
                            modules = profile.get("memory_modules")
                            extra = []
                            if speed:
                                extra.append(f"{speed}MHz")
                            if modules:
                                extra.append(f"{modules} modules")
                            extra_text = f" ({', '.join(extra)})" if extra else ""
                            response_text = f"Your system has {ram_gb} gigabytes of memory{extra_text}."
                            self._safe_speak(response_text, interaction_id=self.interaction_id)
                            output_produced = True
                            self._last_utterance_time = time.time()
                            self.current_probe.mark("llm_end")
                            self.current_probe.mark("tts_start")
                            self.current_probe.mark("tts_end")
                            self.current_probe.log_summary()
                            self.latency_stats.add_probe(self.current_probe)
                            _finalize_response_watchdog()
                            return True
                        response_text = (
                            f"Your system has {ram_gb} gigabytes of memory."
                            if ram_gb is not None
                            else "Hardware information unavailable."
                        )
                    elif subintent == "cpu":
                        cpu_name = profile.get("cpu") if profile else None
                        if wants_specs and profile:
                            cores = profile.get("cpu_cores")
                            threads = profile.get("cpu_threads")
                            mhz = profile.get("cpu_max_mhz")
                            maker = profile.get("cpu_manufacturer")
                            bits = []
                            if maker:
                                bits.append(maker)
                            if cores:
                                bits.append(f"{cores} cores")
                            if threads:
                                bits.append(f"{threads} threads")
                            if mhz:
                                bits.append(f"{mhz} MHz max")
                            detail = f" ({', '.join(bits)})" if bits else ""
                            response_text = f"Your CPU is a {cpu_name}{detail}." if cpu_name else "Hardware information unavailable."
                            self._safe_speak(response_text, interaction_id=self.interaction_id)
                            output_produced = True
                            self._last_utterance_time = time.time()
                            self.current_probe.mark("llm_end")
                            self.current_probe.mark("tts_start")
                            self.current_probe.mark("tts_end")
                            self.current_probe.log_summary()
                            self.latency_stats.add_probe(self.current_probe)
                            _finalize_response_watchdog()
                            return True
                        response_text = (
                            f"Your CPU is a {cpu_name}."
                            if cpu_name
                            else "Hardware information unavailable."
                        )
                    elif subintent == "gpu":
                        if gpus:
                            if wants_specs:
                                gpu_bits = []
                                for gpu in gpus:
                                    name = gpu.get("name")
                                    vram = gpu.get("vram_mb")
                                    dv = gpu.get("driver_version")
                                    detail = []
                                    if vram:
                                        detail.append(f"{vram}MB VRAM")
                                    if dv:
                                        detail.append(f"driver {dv}")
                                    gpu_bits.append(f"{name} ({', '.join(detail)})" if detail else f"{name}")
                                response_text = "Your GPU(s): " + "; ".join(gpu_bits) + "."
                                self._safe_speak(response_text, interaction_id=self.interaction_id)
                                output_produced = True
                                self._last_utterance_time = time.time()
                                self.current_probe.mark("llm_end")
                                self.current_probe.mark("tts_start")
                                self.current_probe.mark("tts_end")
                                self.current_probe.log_summary()
                                self.latency_stats.add_probe(self.current_probe)
                                _finalize_response_watchdog()
                                return True
                            response_text = f"Your GPU is {gpus[0].get('name')}."
                        else:
                            response_text = "No GPU detected."
                    elif subintent == "os":
                        os_name = profile.get("os") if profile else None
                        response_text = (
                            f"You are running {os_name}."
                            if os_name
                            else "Hardware information unavailable."
                        )
                    elif subintent == "motherboard":
                        board = profile.get("motherboard") if profile else None
                        if wants_specs and profile:
                            bios = profile.get("bios_version")
                            sys_maker = profile.get("system_manufacturer")
                            sys_model = profile.get("system_model")
                            parts = []
                            if sys_maker or sys_model:
                                parts.append(" ".join(p for p in [sys_maker, sys_model] if p))
                            if bios:
                                parts.append(f"BIOS {bios}")
                            extra = f" ({', '.join(parts)})" if parts else ""
                            response_text = f"Your motherboard is {board}{extra}." if board else "Hardware information unavailable."
                            self._safe_speak(response_text, interaction_id=self.interaction_id)
                            output_produced = True
                            self._last_utterance_time = time.time()
                            self.current_probe.mark("llm_end")
                            self.current_probe.mark("tts_start")
                            self.current_probe.mark("tts_end")
                            self.current_probe.log_summary()
                            self.latency_stats.add_probe(self.current_probe)
                            _finalize_response_watchdog()
                            return True
                        response_text = (
                            f"Your motherboard is {board}."
                            if board
                            else "Hardware information unavailable."
                        )
                    else:
                        cpu_name = profile.get("cpu") if profile else None
                        ram_gb = profile.get("ram_gb") if profile else None
                        gpu_name = gpus[0].get("name") if gpus else None
                        if not cpu_name or ram_gb is None:
                            response_text = "Hardware information unavailable."
                        else:
                            response_text = (
                                f"Your CPU is a {cpu_name}. "
                                f"You have {ram_gb} gigabytes of memory."
                            )
                            if gpu_name:
                                response_text += f" Your GPU is {gpu_name}."
                            if wants_specs and profile:
                                drives = profile.get("storage_drives") or []
                                if drives:
                                    drive_bits = []
                                    for d in drives:
                                        name = d.get("model") or "Drive"
                                        size = d.get("size_gb")
                                        iface = d.get("interface")
                                        detail = []
                                        if size:
                                            detail.append(f"{size}GB")
                                        if iface:
                                            detail.append(iface)
                                        drive_bits.append(f"{name} ({', '.join(detail)})" if detail else name)
                                    response_text += " Storage: " + "; ".join(drive_bits) + "."
                elif subintent == "temperature":
                    temps = get_temperature_health()
                    if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
                        response_text = "Temperature sensors are not available on this system."
                    else:
                        response_text = self._format_temperature_response(temps)
                else:
                    health = get_system_health()
                    self.logger.info(
                        "[SYSTEM] cpu=%s ram=%s disk=%s",
                        health.get("cpu_percent"),
                        health.get("ram_percent"),
                        health.get("disk_percent"),
                    )
                    response_text = self._format_system_health(health)
                try:
                    self._safe_speak(response_text, interaction_id=self.interaction_id)
                    output_produced = True
                except Exception:
                    pass
                self._last_utterance_time = time.time()
                self.current_probe.mark("llm_end")
                self.current_probe.mark("tts_start")
                self.current_probe.mark("tts_end")
                self.current_probe.log_summary()
                self.latency_stats.add_probe(self.current_probe)
                _finalize_response_watchdog()
                return True

            if intent.intent_type == IntentType.SYSTEM_INFO:
                self.logger.info(f"[Iteration {self.interaction_count}] System profile command detected")
                profile = get_system_profile()
                gpus = get_gpu_profile()
                subintent = getattr(intent, "subintent", None)
                if subintent == "memory":
                    ram_gb = profile.get("ram_gb") if profile else None
                    response_text = (
                        f"Your system has {ram_gb} gigabytes of memory."
                        if ram_gb is not None
                        else "Hardware information unavailable."
                    )
                elif subintent == "cpu":
                    cpu_name = profile.get("cpu") if profile else None
                    response_text = (
                        f"Your CPU is a {cpu_name}."
                        if cpu_name
                        else "Hardware information unavailable."
                    )
                elif subintent == "gpu":
                    if gpus:
                        response_text = f"Your GPU is {gpus[0].get('name')}."
                    else:
                        response_text = "No GPU detected."
                elif subintent == "os":
                    os_name = profile.get("os") if profile else None
                    response_text = (
                        f"You are running {os_name}."
                        if os_name
                        else "Hardware information unavailable."
                    )
                elif subintent == "motherboard":
                    board = profile.get("motherboard") if profile else None
                    response_text = (
                        f"Your motherboard is {board}."
                        if board
                        else "Hardware information unavailable."
                    )
                else:
                    response_text = "Hardware information unavailable."
                try:
                    self._safe_speak(response_text, interaction_id=self.interaction_id)
                    output_produced = True
                except Exception:
                    pass
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

            stop_terms = {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
            if any(term in text.lower() for term in stop_terms):
                from core.music_player import get_music_player
                music_player = get_music_player()
                if music_player.is_playing():
                    self.logger.info("[ARGO] Active music detected")
                    music_player.stop()
                    self._last_utterance_time = time.time()
                    _finalize_response_watchdog()
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

                blocked = music_player.preflight()
                if blocked:
                    msg = "Music library not indexed yet."
                    self.logger.info(f"[Iteration {self.interaction_count}] Music blocked: {blocked.get('reason')}")
                    if self.runtime_overrides.get("tts_enabled", True):
                        self._safe_speak(msg, interaction_id=self.interaction_id)
                    self.release_audio("MUSIC")
                    self.current_probe.mark("llm_end")
                    _finalize_response_watchdog()
                    self._last_utterance_time = time.time()
                    return True
                music_player.stop()
                try:
                    self.release_audio("MUSIC")
                except Exception:
                    pass

                # Optional brief response
                # HARDENING STEP 2: Pass interaction_id to prevent zombie callbacks
                self._safe_speak("Stopped.", interaction_id=self.interaction_id)
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
                    # HARDENING STEP 2: Pass interaction_id to prevent zombie callbacks
                    self._safe_speak("No music playing.", interaction_id=self.interaction_id)
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
                # HARDENING STEP 2: Pass interaction_id to prevent zombie callbacks
                self._safe_speak(status, interaction_id=self.interaction_id)
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
                if not self.runtime_overrides.get("music_enabled", True):
                    msg = "Music is disabled."
                    self.logger.info(f"[Iteration {self.interaction_count}] {msg}")
                    if self.runtime_overrides.get("tts_enabled", True):
                        self._safe_speak(msg, interaction_id=self.interaction_id)
                    self.current_probe.mark("llm_end")
                    return True
                # Music playback with STRICT priority routing
                # IMPORTANT: Music commands don't count as conversational turns
                is_music_iteration = True
                self.logger.info(f"[Iteration {self.interaction_count}] Music command - not counting as interaction turn")

                from core.music_player import get_music_player
                music_player = get_music_player()

                try:
                    self.acquire_audio("MUSIC")
                except Exception as e:
                    self.logger.warning(f"[Iteration {self.interaction_count}] Music blocked: {e}")
                    if self.runtime_overrides.get("tts_enabled", True):
                        self._safe_speak("Audio busy. Try again.", interaction_id=self.interaction_id)
                    self.current_probe.mark("llm_end")
                    return True

                playback_started = False
                error_message = ""

                artist = getattr(intent, "artist", None)
                title = getattr(intent, "title", None)
                do_not_try_genre_lookup = bool(title)
                explicit_genre = bool(getattr(intent, "explicit_genre", False))
                if getattr(intent, "is_generic_play", False) and not artist and not title and not intent.keyword:
                    self.logger.info(f"[Iteration {self.interaction_count}] Music route: RANDOM (generic play)")
                    playback_started = music_player.play_random(None)
                    if not playback_started:
                        error_message = "Your music library is empty or unavailable."
                
                if title:
                    self.logger.info(f"[Iteration {self.interaction_count}] Music title: '{title}'")
                    if not playback_started:
                        playback_started = music_player.play_by_song(title, None)
                        if playback_started:
                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: SONG match")
                        elif not artist:
                            playback_started = music_player.play_by_artist(title, None)
                            if playback_started:
                                self.logger.info(f"[Iteration {self.interaction_count}] Music route: ARTIST fallback (title-only)")

                if not playback_started and artist:
                    self.logger.info(f"[Iteration {self.interaction_count}] Music artist: '{artist}'")
                    playback_started = music_player.play_by_artist(artist, None)
                    if playback_started:
                        self.logger.info(f"[Iteration {self.interaction_count}] Music route: ARTIST match")

                if not playback_started and intent.keyword:
                    keyword = intent.keyword
                    self.logger.info(f"[Iteration {self.interaction_count}] Music keyword: '{keyword}'")

                    # PRIORITY ORDER (FIXED):
                    # 1. Genre match (with adjacent fallback)
                    if not playback_started:
                        if explicit_genre and not do_not_try_genre_lookup:
                            playback_started = music_player.play_by_genre(keyword, None)  # No sink here
                        if playback_started:
                            self.logger.info(f"[Iteration {self.interaction_count}] Music route: GENRE match")

                    # 2. Keyword token match
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

                if intent.intent_type == IntentType.MUSIC and not playback_started and title:
                    setattr(intent, "unresolved", True)
                    self._safe_speak("I can’t find that track in your library.", interaction_id=self.interaction_id)
                    output_produced = True
                    self.release_audio("MUSIC")
                    self.current_probe.mark("llm_end")
                    _finalize_response_watchdog()
                    self._last_utterance_time = time.time()
                    return True

                # Speak error message only once (if no playback started)
                if error_message and not playback_started:
                    # HARDENING STEP 2: Pass interaction_id to prevent zombie callbacks
                    self._safe_speak(error_message, interaction_id=self.interaction_id)
                    output_produced = True

                # Monitor for interrupt during music playback
                if playback_started:
                    self.logger.info(f"[Iteration {self.interaction_count}] Monitoring for interrupt during music...")
                    self._monitor_music_interrupt(music_player)
                    output_produced = True
                else:
                    self.release_audio("MUSIC")

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
            if not self.runtime_overrides.get("tts_enabled", True):
                self.logger.info("[TTS] Disabled by runtime override")
            elif overrides.get("suppress_tts"):
                self.logger.info("[TTS] Suppressed for next interaction override")
            elif response_text and response_text.strip():
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
            # HARDENING STEP 3: Reset audio authority after each interaction
            try:
                self.force_release_audio("ITERATION_END")
            except Exception as e:
                self.logger.warning(f"[Iteration] Error resetting audio owner: {e}")
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

        # Start Porcupine wake listener thread (runs continuously)
        self._start_wake_listener()
        
        try:
            # Loop until stop condition
            while not self.stop_requested:
                # Handle queued wake events on main thread
                try:
                    self._wake_event_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._handle_wake_event()
                    if self.stop_requested:
                        break
                    continue

                if self.state_machine.is_asleep:
                    self.logger.info("[Loop] Sleeping - waiting for wake event...")
                    time.sleep(0.05)
                    continue

                # Awake state: continuous listening
                if self._last_utterance_time is not None:
                    idle_elapsed = time.time() - self._last_utterance_time
                    if idle_elapsed >= self.idle_sleep_seconds:
                        self.logger.info(
                            f"[Idle] No activity for {idle_elapsed:.1f}s; entering sleep"
                        )
                        self._safe_transition(
                            self.state_machine.sleep,
                            State.SLEEP,
                            source="ui",
                            interaction_id=str(self.interaction_id),
                        )
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
        self._set_audio_state(self.AUDIO_STATE_IDLE)
        self._stop_input_audio("stop_requested")
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
            # DEBUG: Print available devices so we can see what's connected
            import sounddevice as sd_enum
            if self.record_debug:
                self.logger.info("[Record] Available audio devices:")
                devices = sd_enum.query_devices()
                for i, dev in enumerate(devices):
                    self.logger.info(f"  [{i}] {dev['name']} (in={dev['max_input_channels']}, out={dev['max_output_channels']})")
            
            # Select microphone by index (prevent Windows "virtual nothing mic")
            # For now use default; if you know your mic index, set: sd.default.device = (MIC_INDEX, None)
            # MIC_INDEX should be from the device list above
            
            stream = sd.InputStream(
                channels=1,
                samplerate=self.AUDIO_SAMPLE_RATE,
                dtype=np.int16,
                device=self.input_device_index,
            )
            self._input_stream = stream
            self._input_stream_active = True
            stream.start()
            
            # INSTRUMENTATION: Log mic open
            log_event("MIC OPEN")
            
            rms = 0.0  # Initialize before loop (defensive: prevents UnboundLocalError in logging)
            chunk_count = 0  # For RMS logging every 20 chunks
            
            while total_samples < max_samples:
                if self._is_speaking.is_set() or self._input_stop_event.is_set() or self._audio_state == self.AUDIO_STATE_SPEAKING:
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
                chunk_count += 1
                
                # Log RMS every 20 chunks (~2 seconds) to see if mic is capturing
                if chunk_count % 20 == 0:
                    self.logger.debug(f"[AudioDebug] RMS={rms:.4f} (elapsed={elapsed_time:.2f}s)")
                
                # CRITICAL: Abort early if no voice detected after 2.5s
                if elapsed_time > 2.5 and np.mean(rms_samples[-25:] if len(rms_samples) >= 25 else rms_samples) < 0.002:
                    stop_reason = "no_voice_detected"
                    self.logger.warning("[Record] No voice detected (avg RMS < 0.002 after 2.5s), aborting early")
                    break
                
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
                    calibration_chunks = 3  # Ignore first 300ms (3 x 100ms)
                    filtered_rms = rms_samples[calibration_chunks:] if len(rms_samples) > calibration_chunks else rms_samples
                    avg_rms = np.mean(filtered_rms) if filtered_rms else 0.0
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
            
            # INSTRUMENTATION: Log mic close
            log_event("MIC CLOSE")
            
            self._input_stream = None
            self._input_stream_active = False
        
        # Emit debug metrics (gated by RECORD_DEBUG flag)
        if self.record_debug and rms_samples:
            calibration_chunks = 3  # Ignore first 300ms (3 x 100ms)
            filtered_rms = rms_samples[calibration_chunks:] if len(rms_samples) > calibration_chunks else rms_samples
            avg_rms = np.mean(filtered_rms) if filtered_rms else 0.0
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
            audio = np.concatenate(audio_buffer, axis=0)
            
            # FIX 3: Normalize audio before Whisper (critical for weak signals)
            # Peak normalization does not amplify noise meaningfully but gives Whisper a fighting chance
            peak = np.max(np.abs(audio.astype(float)))
            if peak > 0:
                audio = (audio.astype(float) / peak * 32767).astype(np.int16)
                if self.record_debug:
                    self.logger.debug(f"[Record] Audio normalized (peak was {peak:.0f})")
            
            return audio
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
        finally:
            try:
                self.release_audio("MUSIC")
            except Exception:
                pass

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
        tts_paused = False
        try:
            self.logger.info("[TTS] Speaking response (interrupts disabled during playback)...")
            
            # CRITICAL: Pause input BEFORE starting TTS to prevent feedback loop
            # where speaker output is picked up by microphone
            try:
                self._pause_trigger_for_tts()
                tts_paused = True
            except Exception as e:
                self.logger.warning(f"[TTS] Failed to pause input: {e}")
            
            try:
                # Speak in main thread (blocking, event loop-safe)
                # IMPORTANT: Do NOT monitor for interrupts while Argo is speaking
                # This prevents Argo from interrupting itself with its own audio
                # HARDENING STEP 2: Pass interaction_id to prevent zombie callbacks
                try:
                    self.acquire_audio("TTS")
                except Exception as e:
                    self.logger.warning(f"[TTS] Audio ownership denied: {e}")
                    return
                try:
                    self.sink.speak(response_text, interaction_id=self.interaction_id)
                finally:
                    self.release_audio("TTS")
                
                self.logger.info("[TTS] Response finished")
            except Exception as e:
                self.logger.error(f"[TTS] Error during sink.speak(): {e}")
                raise
            finally:
                # Resume input immediately after TTS completes
                if tts_paused:
                    try:
                        self._resume_trigger_after_tts()
                    except Exception as e:
                        self.logger.warning(f"[TTS] Failed to resume input: {e}")
        
        except Exception as e:
            self.logger.error(f"[TTS] Fatal error during speech: {e}", exc_info=True)
        
        finally:
            # Ensure speaking flag is cleared even if exception occurred
            try:
                self._is_speaking.clear()
            except Exception:
                pass

    def _build_count_response(self, text: str) -> str:
        target = self._parse_count_target(text)
        if target < 1:
            target = 1
        target = min(target, 50)
        return ", ".join(str(i) for i in range(1, target + 1))

    def _parse_count_target(self, text: str) -> int:
        if not text:
            return 5
        match = re.search(r"\b(\d+)\b", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 5
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }
        for word, value in words.items():
            if re.search(rf"\b{word}\b", text, flags=re.IGNORECASE):
                return value
        return 5

    def _format_system_health(self, health: dict) -> str:
        return (
            f"CPU at {health.get('cpu_percent')} percent. "
            f"Memory at {health.get('ram_percent')} percent. "
            f"Disk {health.get('disk_percent')} percent full."
        )

    def _format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        text = (
            f"Your system has {total_gb} gigabytes of memory installed. "
            f"Currently using about {used_pct} percent."
        )
        cpu_temp = temps.get("cpu")
        gpu_temp = temps.get("gpu")
        if cpu_temp is not None:
            text += f" CPU temperature is {cpu_temp} degrees."
        if gpu_temp is not None:
            text += f" GPU temperature is {gpu_temp} degrees."
        return text

    def _format_temperature_response(self, temps: dict) -> str:
        parts = []
        cpu_temp = temps.get("cpu")
        gpu_temp = temps.get("gpu")
        if cpu_temp is not None:
            parts.append(f"CPU temperature is {cpu_temp} degrees.")
        if gpu_temp is not None:
            parts.append(f"GPU temperature is {gpu_temp} degrees.")
        if not parts:
            return "Temperature sensors are not available on this system."
        return " ".join(parts) + " Normal."

    def _format_system_full_report(self, report: dict) -> str:
        health = report.get("health", {}) or {}
        disks = report.get("disks", {}) or {}
        uptime_seconds = report.get("uptime_seconds", 0) or 0
        network = report.get("network", []) or []
        battery = report.get("battery")
        fans = report.get("fans")

        parts = []
        cpu_pct = health.get("cpu_percent")
        ram_pct = health.get("ram_percent")
        disk_pct = health.get("disk_percent")
        gpu_pct = health.get("gpu_percent")
        gpu_mem = health.get("gpu_mem_percent")
        if cpu_pct is not None and ram_pct is not None and disk_pct is not None:
            parts.append(f"CPU is {cpu_pct} percent. Memory is {ram_pct} percent. Disk usage is {disk_pct} percent.")
        if gpu_pct is not None:
            if gpu_mem is not None:
                parts.append(f"GPU usage is {gpu_pct} percent, with VRAM at {gpu_mem} percent.")
            else:
                parts.append(f"GPU usage is {gpu_pct} percent.")

        cpu_temp = health.get("cpu_temp")
        gpu_temp = health.get("gpu_temp")
        if cpu_temp is not None or gpu_temp is not None:
            temp_bits = []
            if cpu_temp is not None:
                temp_bits.append(f"CPU {cpu_temp}°C")
            if gpu_temp is not None:
                temp_bits.append(f"GPU {gpu_temp}°C")
            parts.append("Temperatures: " + ", ".join(temp_bits) + ".")

        if uptime_seconds:
            hours = round(uptime_seconds / 3600, 1)
            parts.append(f"Uptime is {hours} hours.")

        if disks:
            disk_bits = []
            for label, info in sorted(disks.items()):
                drive_label = label.replace(":", "")
                free_text = self._format_size_gb(info["free_gb"])
                total_text = self._format_size_gb(info["total_gb"])
                disk_bits.append(
                    f"{drive_label} drive is {info['percent']} percent full, with {free_text} free out of {total_text}."
                )
            parts.append("Drives: " + " ".join(disk_bits))

        if network:
            net_bits = []
            for nic in network:
                label = nic.get("name")
                ip = nic.get("ip")
                speed = nic.get("speed_mbps")
                seg = label or "Network"
                if ip:
                    seg += f" {ip}"
                if speed:
                    seg += f" {speed}Mbps"
                net_bits.append(seg)
            parts.append("Network: " + ", ".join(net_bits) + ".")

        if battery:
            pct = battery.get("percent")
            plugged = battery.get("plugged")
            if pct is not None:
                status = "plugged in" if plugged else "on battery"
                parts.append(f"Battery is {pct} percent, {status}.")

        if fans:
            fan_bits = [f"{f['label']} {f['rpm']}RPM" for f in fans if f.get("rpm") is not None]
            if fan_bits:
                parts.append("Fans: " + ", ".join(fan_bits) + ".")

        if not parts:
            return "Hardware information unavailable."

        return "System status. " + " ".join(parts)

    def _format_size_gb(self, gb: float) -> str:
        try:
            if gb >= 1024:
                tb = round(gb / 1024, 2)
                return f"{tb} terabytes"
            gigs = int(gb)
            megs = int(round((gb - gigs) * 1024))
            if gigs > 0 and megs > 0:
                return f"{gigs} gigs {megs} megs"
            if gigs > 0:
                return f"{gigs} gigs"
            return f"{megs} megs"
        except Exception:
            return f"{gb} gigs"

    def _safe_speak(self, text: str, interaction_id: Optional[str] = None) -> None:
        if not text or not text.strip():
            return
        if not self.runtime_overrides.get("tts_enabled", True):
            return
        current_interaction_id = interaction_id or self.interaction_id
        if self._response_interaction_id != current_interaction_id:
            self._response_interaction_id = current_interaction_id
            self._response_committed = False
        if self._response_committed:
            self.logger.warning(
                "[Response] Duplicate response suppressed (interaction_id=%s)",
                current_interaction_id,
            )
            return
        self.logger.info(f"Argo: {text}")
        self._response_committed = True
        try:
            self.acquire_audio("TTS")
        except Exception as e:
            self.logger.warning(f"[TTS] Audio ownership denied: {e}")
            return
        try:
            self.sink.speak(text, interaction_id=interaction_id or self.interaction_id)
        finally:
            self.release_audio("TTS")
