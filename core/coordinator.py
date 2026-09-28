"""Classic voice interaction coordinator.

Owns bounded interaction sequencing and delegates capture, parsing, generation,
delivery, memory, and audio-authority work to focused services.
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
from core.coordinator_stages import (
    capture_audio_stage,
    dispatch_procedural_stage,
    dispatch_simple_deterministic_stage,
    parse_intent_stage,
    process_transcript_stage,
    transcribe_audio_stage,
)
from core.coordinator_system_health_stage import dispatch_system_health_stage
from core.coordinator_response_stage import deliver_and_record_response
from core.coordinator_response_guard import CoordinatorResponseGuard
from core.coordinator_generation_stage import generate_interaction_response
from core.coordinator_music_stage import (
    stop_active_music_for_phrase,
)
from core.state_machine import StateMachine, State
from core.actuators.python_builder import PythonBuilder
from core.audio_owner import get_audio_owner
from core.config import get_config, get_runtime_overrides, set_runtime_override, clear_runtime_overrides
from core.coordinator_responses import CoordinatorResponseMixin
from core.coordinator_recording import RecordingConfig, RecordingHooks, record_with_silence_detection
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
class Coordinator(CoordinatorResponseMixin):
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
    # Normalized RMS (0-1), matching the `rms` actually computed in the record
    # loop. This was 250 - an absolute int16 level - compared against a
    # normalized value, so "rms < SILENCE_THRESHOLD" was true on every chunk
    # and the silence timer ran continuously from the first sample of speech.
    # Recording therefore stopped ~2.2s in regardless of whether Tommy was
    # still talking. Only used when Silero is unavailable.
    # 0.03 sits above this room's measured ambient noise: startup calibration
    # reports mean=0.009, p95=0.024. A floor below that would mean silence is
    # never detected and every recording runs to the 15s cap.
    SILENCE_THRESHOLD = 0.03
    RMS_SPEECH_THRESHOLD = 0.0005  # RMS normalized level (0-1) to START silence timer — LOWERED to 0.0005 for weak Brio signal
    VAD_SPEECH_PROBABILITY = 0.5  # Silero speech probability that counts as speech
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

            audio_bytes = capture_audio_stage(self, initial_frames=initial_frames)
            text = transcribe_audio_stage(self, audio_bytes)
            transcript_result = process_transcript_stage(self, text, overrides)
            if not transcript_result.continue_processing:
                return transcript_result.interaction_result
            text = transcript_result.text
            stt_conf = transcript_result.stt_confidence
            parse_result = parse_intent_stage(self, text, log_event)
            if not parse_result.continue_processing:
                return parse_result.interaction_result
            intent = parse_result.intent
            # 4. Fast-path deterministic commands (before LLM generation)
            # Procedural and deterministic commands must execute immediately without LLM latency

            response_guard = CoordinatorResponseGuard(self)

            deterministic_result = dispatch_simple_deterministic_stage(
                self, intent, text
            )
            if deterministic_result.handled:
                response_guard.set_output(deterministic_result.output_produced)
                response_guard.finalize()
                return deterministic_result.interaction_result
            if dispatch_system_health_stage(
                self, intent, response_guard.mark_output, response_guard.finalize
            ):
                return True
            procedural_result = dispatch_procedural_stage(
                self, text, response_guard.mark_output, response_guard.finalize
            )
            if procedural_result.handled:
                response_guard.set_output(procedural_result.output_produced)
                return procedural_result.interaction_result

            if stop_active_music_for_phrase(
                self, text, response_guard.finalize
            ):
                return True
            generation = generate_interaction_response(
                self,
                intent,
                response_guard.mark_output,
                response_guard.finalize,
            )
            response_guard.set_output(generation.output_produced)
            is_music_iteration = generation.is_music_iteration
            if generation.return_interaction:
                return generation.interaction_result
            response_text = generation.response_text
            response_guard.set_output(deliver_and_record_response(
                self,
                intent=intent,
                user_text=text,
                response_text=response_text,
                overrides=overrides,
                output_produced=response_guard.output_produced,
            ))

            response_guard.finalize()

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
        """Run bounded interactions until stop, sleep, or the configured limit."""
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
    
    def _speech_gate(self):
        """The Silero gate, loaded once, or None if it will not load.

        The ONNX session costs a few hundred milliseconds to build, so it is
        created on first use and kept. A failure is cached as None so we do
        not retry on every single recording.
        """
        gate = getattr(self, "_silero_gate", None)
        if gate is not None:
            return gate
        if getattr(self, "_silero_gate_failed", False):
            return None
        try:
            from core.vad_silero import SileroGate

            gate = SileroGate(
                sample_rate=self.AUDIO_SAMPLE_RATE,
                threshold=self.VAD_SPEECH_PROBABILITY,
            )
        except Exception:
            self.logger.exception("[Record] Silero gate could not be created; using energy detection")
            self._silero_gate_failed = True
            return None
        if not gate.available:
            self._silero_gate_failed = True
            return None
        self._silero_gate = gate
        return gate

    def _record_with_silence_detection(self, initial_frames: Optional[list] = None) -> np.ndarray:
        """Record one utterance with pre-roll, VAD, and bounded silence detection."""
        def set_stream_state(stream, active: bool) -> None:
            self._input_stream = stream
            self._input_stream_active = active

        config = RecordingConfig(
            sample_rate=self.AUDIO_SAMPLE_RATE,
            minimum_duration=self.MINIMUM_RECORD_DURATION,
            dynamic_silence_timeout=self.dynamic_silence_timeout,
            maximum_duration=self.MAX_RECORDING_DURATION,
            rms_speech_threshold=self.RMS_SPEECH_THRESHOLD,
            silence_threshold=self.SILENCE_THRESHOLD,
            silence_timeout_label=self.SILENCE_TIMEOUT_SECONDS,
            record_debug=self.record_debug,
            input_device_index=self.input_device_index,
        )
        hooks = RecordingHooks(
            logger=self.logger,
            should_abort=lambda: (
                self._is_speaking.is_set()
                or self._input_stop_event.is_set()
                or self._audio_state == self.AUDIO_STATE_SPEAKING
            ),
            speech_gate=self._speech_gate,
            get_preroll=self.trigger.get_preroll_buffer,
            set_stream_state=set_stream_state,
            event_logger=log_event,
            last_transcript=lambda: self._last_transcript,
        )
        return record_with_silence_detection(
            config,
            hooks,
            stream_factory=sd.InputStream,
            device_query=sd.query_devices,
            initial_frames=initial_frames,
        )

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
