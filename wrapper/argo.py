"""Classic wrapper facade for CLI, wake, transcription, and execution flows.

The implementation lives in focused ``wrapper.*`` modules. This file preserves
the historical import and script entry points used by the CLI and input shell.
Smooth Voice uses ``livekit_realtime_agent.py`` and ``core.voice`` instead.
"""

import sys
import os
import uuid
import logging
from pathlib import Path

# When executed as ``python wrapper/argo.py``, Python puts ``wrapper/`` rather
# than the repository root on sys.path. Bootstrap the package root before any
# ``wrapper.*`` imports; module execution already has it and remains unchanged.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from wrapper.conversation_history import (
    _append_daily_log,
    _get_log_dir,
)
from wrapper.behavior_policy import classify_query_type
from wrapper.cli_policy import (
    classify_input,
    classify_verbosity,
)
from wrapper.preflight import (
    dispatch_governance,
    dispatch_music_volume,
    dispatch_self_knowledge,
    neural_terminology_sink,
)
from wrapper.ollama_generation import generate_ollama_response
from wrapper.replay_context import build_replay_context
from wrapper.prompt_composition import compose_prompt
from wrapper.post_generation import audit_and_record_response
from wrapper.runtime_composition import prepare_conversation, update_preferences
from wrapper.interaction_runtime import InteractionRuntime, run_classified_interaction
from wrapper.public_runtime import PublicRuntime, run_public_interaction
from wrapper.transcription_workflow import (
    TranscriptionWorkflow,
    transcribe_with_confirmation,
)
from wrapper.execution_workflow import ExecutionWorkflow, execute_approved_plan
from wrapper.audio_output import AudioOutputBridge
from wrapper.session_ids import resolve_session_id as _resolve_session_id
from wrapper.wake_controls import (
    detector_status,
    pause_detector,
    resume_detector,
    start_detector,
    stop_detector,
)
from wrapper.wake_interaction import WakeInteractionRuntime, run_wake_interaction
from wrapper.state_controls import transition_to_speaking, transition_to_thinking

# Module-level logger (consistent with rest of system)
logger = logging.getLogger(__name__)

# Load .env configuration (must happen before other imports that read env vars)
# Important: override=False ensures shell environment variables take precedence
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # dotenv optional; use system environment variables if not installed

# Import Argo Memory (RAG-based interaction recall)
sys.path.insert(0, os.path.dirname(__file__))
from browsing import (
    list_conversations, show_by_date, show_by_topic,
    get_conversation_context, summarize_conversation
)

# Import Whisper Transcription (audio-to-text with confirmation gate)
try:
    from transcription import (
        transcribe_audio,
        transcription_storage,
        TranscriptionArtifact
    )
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    # Whisper optional; graceful degradation if not installed

# Import Execution Engine (simulation mode, v1.3.0-alpha & real execution, v1.4.0)
try:
    from execution_engine import (
        DryRunExecutionReport,
        ExecutionPlanArtifact,
        ExecutionMode,
        ExecutionResultArtifact,
        ExecutionStatus,
        SimulationStatus
    )
    EXECUTION_ENGINE_AVAILABLE = True
except ImportError:
    EXECUTION_ENGINE_AVAILABLE = False
    # Execution engine optional; graceful degradation if not installed

# Import Output Sink (Phase 7A-0: Piper TTS integration)
try:
    from core.output_sink import get_output_sink
    OUTPUT_SINK_AVAILABLE = True
except ImportError:
    OUTPUT_SINK_AVAILABLE = False
    # Output sink optional; graceful degradation if not installed

# Import State Machine (Phase 7B: Wake/sleep/stop control)
try:
    from core.state_machine import (
        StateMachine,
        get_state_machine,
    )
    STATE_MACHINE_AVAILABLE = True
except ImportError:
    STATE_MACHINE_AVAILABLE = False
    # State machine optional; graceful degradation if not installed

# Import Wake-Word Detector (Phase 7A-3b: "ARGO" wake-word recognition)
try:
    from core.wake_word_detector import (
        WakeWordDetector,
        WakeWordRequest,
        initialize_detector,
    )
    WAKE_WORD_DETECTOR_AVAILABLE = True
except ImportError:
    WAKE_WORD_DETECTOR_AVAILABLE = False
    # Wake-word detector optional; graceful degradation if not installed
    WakeWordDetector = object  # type: ignore
    WakeWordRequest = object  # type: ignore

# Import Command Parser (Phase 7B-3: Deterministic command classification)
try:
    from core.command_parser import (
        CommandClassifier,
        CommandType,
        get_classifier as get_command_classifier,
    )
    COMMAND_PARSER_AVAILABLE = True
except ImportError:
    COMMAND_PARSER_AVAILABLE = False
    # Command parser optional; graceful degradation if not installed

# ============================================================================
# UTF-8 Encoding Configuration (Windows terminal safety)
# ============================================================================

# Force UTF-8 encoding for stdout/stderr on all platforms (especially Windows)
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================================
# Audio Output Configuration (Phase 7A-0)
# ============================================================================

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() == "true"
"""Enable/disable audio output entirely. Default: false (text-only)."""

PIPER_ENABLED = os.getenv("PIPER_ENABLED", "false").lower() == "true"
"""Enable/disable Piper TTS specifically. Default: false. Requires VOICE_ENABLED=true."""


# ============================================================================
# Audio Output Helper (Async Bridge for CLI)
# ============================================================================

_audio_output_bridge = AudioOutputBridge(
    get_output_sink if OUTPUT_SINK_AVAILABLE else None,
    enabled=VOICE_ENABLED,
    piper_enabled=PIPER_ENABLED,
    logger=logger,
)

def _send_to_output_sink(text: str) -> None:
    """
    Bridge between sync CLI context and async OutputSink.
    
    If VOICE_ENABLED and PIPER_ENABLED:
    - Try to use existing event loop if available (FastAPI)
    - Fall back to new event loop for CLI
    - Cap spoken output to MAX_VOICE_CHARS to prevent long audio
    
    If disabled or unavailable:
    - No-op (text already printed to stdout)
    
    Args:
        text: Text to send to audio output
    """
    _audio_output_bridge.send(text)


# ============================================================================
# Session Management
# ============================================================================

# Define a system-wide session identifier
SESSION_ID = str(uuid.uuid4())
"""Unique identifier for this execution. Set in __main__ based on CLI args."""

# Initialize state machine (Phase 7B)
_state_machine: StateMachine | None = None
"""Global state machine for wake/sleep/stop control."""

if STATE_MACHINE_AVAILABLE:
    try:
        _state_machine = get_state_machine()
    except Exception as e:
        print(f"⚠ State machine initialization error: {e}", file=sys.stderr)
        STATE_MACHINE_AVAILABLE = False

# Initialize command parser (Phase 7B-3)
_command_parser: CommandClassifier | None = None
"""Global command parser for deterministic classification."""

if COMMAND_PARSER_AVAILABLE:
    try:
        _command_parser = get_command_classifier(state_machine=_state_machine)
    except Exception as e:
        print(f"⚠ Command parser initialization error: {e}", file=sys.stderr)
        COMMAND_PARSER_AVAILABLE = False

# Initialize wake-word detector (Phase 7A-3b)
_wake_word_detector: WakeWordDetector | None = None
"""Global wake-word detector for "ARGO" keyword recognition."""

def _on_wake_word_detected():
    """
    Callback when "ARGO" wake-word is detected.
    
    CRITICAL: This function MUST force recording and transcription.
    This is the core wake-word flow.
    """
    if not WAKE_WORD_DETECTOR_AVAILABLE:
        return
    if _state_machine is None:
        return

    def load_voice_input():
        from voice_input import record_audio_on_wake_word, transcribe_audio

        return record_audio_on_wake_word, transcribe_audio

    run_wake_interaction(
        WakeInteractionRuntime(
            state_machine=_state_machine,
            command_parser=_command_parser,
            request_factory=WakeWordRequest,
            load_voice_input=load_voice_input,
            logger=logger,
        )
    )

def _get_current_state():
    """Get current state machine state for detector."""
    if _state_machine:
        return _state_machine.current_state
    return "UNKNOWN"

if WAKE_WORD_DETECTOR_AVAILABLE and STATE_MACHINE_AVAILABLE:
    try:
        _wake_word_detector = initialize_detector(
            on_wake_word=_on_wake_word_detected,
            state_getter=_get_current_state
        )
        logger.info("Wake-word detector initialized (Phase 7A-3b)")
    except Exception as e:
        print(f"⚠ Wake-word detector initialization error: {e}", file=sys.stderr)
        WAKE_WORD_DETECTOR_AVAILABLE = False


# ============================================================================
# Wake-Word Detector Control (Phase 7A-3b)
# ============================================================================

def start_wake_word_detector():
    """
    Start the wake-word detector.
    
    Called when entering LISTENING state.
    Detector runs independently and pauses during PTT/SLEEP/THINKING/SPEAKING.
    """
    start_detector(_wake_word_detector, logger)

def stop_wake_word_detector():
    """
    Stop the wake-word detector.
    
    Called when exiting LISTENING state (e.g., entering SLEEP).
    """
    stop_detector(_wake_word_detector, logger)

def pause_wake_word_detector():
    """
    Pause the wake-word detector (e.g., during PTT).
    
    Non-blocking pause; detector remains initialized but doesn't listen.
    Resumed after PTT completes.
    """
    pause_detector(_wake_word_detector, logger)

def resume_wake_word_detector():
    """
    Resume the wake-word detector after pause.
    
    Called after PTT completes; detector resumes listening.
    """
    resume_detector(_wake_word_detector, logger)

def get_wake_word_detector_status() -> dict:
    """Get wake-word detector status for diagnostics."""
    return detector_status(_wake_word_detector)




SESSION_FILE = os.path.join(_get_log_dir(), ".sessions.json")
"""Persistent store of named session IDs. Format: {"name": "uuid", ...}"""


def resolve_session_id(name: str) -> str:
    """
    Resolve a human-readable session name to a persistent UUID.
    
    If the session name already exists in .sessions.json, return its UUID.
    If not, generate a new UUID, persist it, and return it.
    
    This allows multiple CLI runs to share the same session_id by using
    the same --session <name> flag. Sessions persist until manually deleted.
    
    Args:
        name: Human-readable session name (e.g., "work", "demo", "project-x")
        
    Returns:
        str: UUID associated with this session name (same across runs)
        
    Side Effects:
        Creates .sessions.json in logs directory if it doesn't exist.
        Updates .sessions.json when a new session name is first seen.
    """
    return _resolve_session_id(name, SESSION_FILE)


# ============================================================================
# Intent Classification & Gating
# ============================================================================



# ============================================================================
# System Prompts & Constraints
# ============================================================================

MODE_ENFORCEMENT = """You must strictly follow the rules of any activated conversation mode.
These rules are mandatory constraints, not suggestions.

Do not narrate modes.
Do not ask permission to begin.
Do not ask clarifying questions before producing output if the active mode forbids it.

If Brainstorming Mode applies:
- Start by generating ideas immediately
- Provide multiple distinct ideas before asking any questions
- Do not ask "what's the concept" or similar gatekeeping questions

Respond to the user. Do not mention conversation modes or internal state.
"""
"""System constraint injected when --mode flag is used. Enforces mode rules."""


# ============================================================================
# Replay Filtering Policy
# ============================================================================

# ============================================================================
# Phase 4C: Pre-Generation Behavior Selector
# ============================================================================

"""
Query type classification patterns.
Priority indicates detection order (higher priority checked first).
"""




# ============================================================================
# Logging Infrastructure
# ============================================================================



# ============================================================================
# WHISPER TRANSCRIPTION WITH CONFIRMATION GATE
# ============================================================================

def transcribe_and_confirm(audio_path: str, max_duration_seconds: int = 300) -> tuple:
    """
    Transcribe audio file and display confirmation gate before processing.
    
    ARGO's philosophy on transcription:
      1. Audio in → text out (no intent detection)
      2. Display text to user
      3. Wait for explicit confirmation
      4. Only confirmed transcripts flow downstream
    
    This function enforces the confirmation gate: users must see what Whisper
    heard before any downstream processing. No blind automation.
    
    Args:
        audio_path: Path to WAV file
        max_duration_seconds: Maximum audio duration (default 5 minutes)
    
    Returns:
        tuple: (confirmed: bool, transcript_text: str, artifact: TranscriptionArtifact)
               - confirmed: True if user approved, False if rejected
               - transcript_text: Raw transcript (empty if rejected or failed)
               - artifact: Full artifact with metadata (for logging/audit)
    
    Example:
        confirmed, text, artifact = transcribe_and_confirm("user_audio.wav")
        
        if confirmed:
            # Safe to use: user explicitly approved this text
            run_argo(text)
        else:
            print("Transcript rejected. Please try again.")
    """
    return transcribe_with_confirmation(
        TranscriptionWorkflow(
            whisper_available=WHISPER_AVAILABLE,
            state_machine_available=STATE_MACHINE_AVAILABLE,
            state_machine=_state_machine,
            artifact_factory=(
                TranscriptionArtifact
                if "TranscriptionArtifact" in globals() and TranscriptionArtifact
                else None
            ),
            transcribe_audio=transcribe_audio if WHISPER_AVAILABLE else None,
            storage=transcription_storage if WHISPER_AVAILABLE else None,
            read_confirmation=input,
        ),
        audio_path,
        max_duration_seconds,
    )


def execute_and_confirm(
    dry_run_report: DryRunExecutionReport,
    plan_artifact: ExecutionPlanArtifact,
    user_approved: bool = False,
    intent_id: str = ""
) -> ExecutionResultArtifact | None:
    """
    Execute an approved execution plan with all hard gates.
    
    This is a GLUE FUNCTION ONLY. It:
    1. Validates all five execution hard gates
    2. Calls ExecutionMode.execute_plan()
    3. Returns ExecutionResultArtifact
    
    It does NOT:
    - Add new logic
    - Modify plan steps
    - Bypass confirmation flags
    - Retry on failure
    
    HARD GATES (all must pass):
    1. DryRunExecutionReport must exist
    2. Simulation status must be SUCCESS
    3. User must have approved execution
    4. execution_plan_id must match between report and plan
    5. All gates checked before any system state changes
    
    Args:
        dry_run_report: DryRunExecutionReport from simulation layer
        plan_artifact: ExecutionPlanArtifact that was simulated
        user_approved: Boolean confirmation from user
        intent_id: ID of original intent (for chain traceability)
    
    Returns:
        ExecutionResultArtifact on success
        None if any hard gate fails (zero side effects)
    
    Raises:
        None - errors are recorded in result artifact
    """
    
    return execute_approved_plan(
        ExecutionWorkflow(
            engine_available=EXECUTION_ENGINE_AVAILABLE,
            execution_mode_factory=(
                ExecutionMode if EXECUTION_ENGINE_AVAILABLE else None
            ),
            simulation_status=(
                SimulationStatus if EXECUTION_ENGINE_AVAILABLE else None
            ),
            execution_status=(
                ExecutionStatus if EXECUTION_ENGINE_AVAILABLE else None
            ),
        ),
        dry_run_report,
        plan_artifact,
        user_approved=user_approved,
        intent_id=intent_id,
    )


# ============================================================================
# PHASE 7B: STATE MACHINE INTEGRATION HELPERS
# ============================================================================
# Note: Command detection now handled by Phase 7B-3 CommandClassifier
# These helpers perform state transitions only


def _transition_to_thinking() -> bool:
    """Transition to THINKING state when a command is accepted."""
    return transition_to_thinking(
        STATE_MACHINE_AVAILABLE,
        _state_machine,
        lambda message: print(message, file=sys.stderr),
    )


def _transition_to_speaking() -> bool:
    """Transition to SPEAKING state when audio playback starts."""
    return transition_to_speaking(
        STATE_MACHINE_AVAILABLE,
        _state_machine,
        lambda message: print(message, file=sys.stderr),
    )


def run_argo(
    user_input: str,
    *,
    active_mode: str | None = None,
    replay_n: int | None = None,
    replay_session: bool = False,
    strict_mode: bool = True,
    persona: str = "neutral",
    verbosity: str = "short",
    replay_reason: str = "continuation",
    voice_mode: bool = False,
) -> None:
    """
    Public entry point for Argo execution.
    
    Wraps _run_argo_internal with memory and preference integration:
    1. Loads and updates user preferences
    2. Retrieves relevant past interactions (SKIPPED in voice_mode)
    3. Injects memory context into the prompt (SKIPPED in voice_mode)
    4. Injects preference context into the prompt
    5. Executes the core logic
    6. Stores the new interaction to memory
    
    Voice Mode (voice_mode=True):
    - Disables memory injection entirely (no prior context)
    - Disables replay (always stateless)
    - Forces CLI context for formatting
    - Ensures single-turn, stateless execution
    - CRITICAL for Option B compliance
    
    Args:
        user_input: User's raw message
        active_mode: Conversation mode name or None
        replay_n: Last N turns to replay or None (ignored in voice_mode)
        replay_session: True to replay current session (ignored in voice_mode)
        strict_mode: If True, reject low-intent input
        persona: Tone adjustment ("neutral", etc.)
        verbosity: Response length control ("short" or "long")
        replay_reason: Why replay was requested
        voice_mode: If True, force stateless, memory-free execution for voice input
    """
    def set_send_output(callback) -> None:
        global _send_to_output_sink
        _send_to_output_sink = callback

    run_public_interaction(
        PublicRuntime(
            update_preferences=update_preferences,
            dispatch_music_volume=dispatch_music_volume,
            dispatch_self_knowledge=dispatch_self_knowledge,
            neural_terminology_sink=neural_terminology_sink,
            dispatch_governance=dispatch_governance,
            prepare_conversation=prepare_conversation,
            run_internal=_run_argo_internal,
            get_output_sink=get_output_sink if OUTPUT_SINK_AVAILABLE else None,
            get_send_output=lambda: _send_to_output_sink,
            set_send_output=set_send_output,
            repository_root=Path(__file__).resolve().parent.parent,
            command_parser_available=COMMAND_PARSER_AVAILABLE,
            command_parser=_command_parser,
            command_type=CommandType if COMMAND_PARSER_AVAILABLE else None,
            output_sink_available=OUTPUT_SINK_AVAILABLE,
            state_machine_available=STATE_MACHINE_AVAILABLE,
            state_machine=_state_machine,
            transition_to_thinking=_transition_to_thinking,
            transition_to_speaking=_transition_to_speaking,
        ),
        user_input,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        strict_mode=strict_mode,
        persona=persona,
        verbosity=verbosity,
        replay_reason=replay_reason,
        voice_mode=voice_mode,
    )
    
    # Note: Memory storage happens inside _run_argo_internal after model response is available


def _run_argo_internal(
    user_input: str,
    *,
    active_mode: str | None = None,
    replay_n: int | None = None,
    replay_session: bool = False,
    strict_mode: bool = True,
    persona: str = "neutral",
    verbosity: str = "short",
    replay_reason: str = "continuation",
    voice_mode: bool = False
) -> None:
    """Run one classified, optionally contextualized wrapper interaction."""
    runtime = InteractionRuntime(
        classify_input=classify_input,
        classify_verbosity=classify_verbosity,
        send_output=_send_to_output_sink,
        append_daily_log=_append_daily_log,
        build_replay_context=build_replay_context,
        compose_prompt=compose_prompt,
        generate_response=generate_ollama_response,
        audit_and_record=audit_and_record_response,
        session_id=SESSION_ID,
        mode_enforcement=MODE_ENFORCEMENT,
        state_machine_available=STATE_MACHINE_AVAILABLE,
        state_machine=_state_machine,
        wake_word_detector_available=WAKE_WORD_DETECTOR_AVAILABLE,
        resume_wake_word_detector=resume_wake_word_detector,
        logger=logger,
    )
    run_classified_interaction(
        runtime,
        user_input,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        strict_mode=strict_mode,
        persona=persona,
        verbosity=verbosity,
        replay_reason=replay_reason,
        voice_mode=voice_mode,
    )


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    from wrapper.cli import run_cli

    raise SystemExit(run_cli(sys.modules[__name__]))
