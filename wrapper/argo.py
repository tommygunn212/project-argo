"""
================================================================================
ARGO (Autonomous-Resistant Governed Operator)
Local-First AI Control System
================================================================================

Module:      argo.py (Main Execution Engine)
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0
Created:     December 2025
Purpose:     Core orchestration layer for ARGO AI system

================================================================================
FEATURES
================================================================================

1. CONVERSATIONAL AI
   - Direct interface to Ollama's llama3.1:8b model
   - Example-based voice guidance (warm, confident, casual tone)
   - Adaptive persona based on user familiarity and query type
   - Full auditability with JSON logging of all interactions

2. MEMORY & CONTEXT
   - TF-IDF + topic fallback for relevant past interaction retrieval
   - Automatic preference detection (tone, verbosity, humor, structure)
   - Explicit memory storage (no background learning)
   - Session-aware context building

3. RECALL MODE
   - Deterministic meta-query detection (what did we discuss?)
   - Formatted conversation summaries without model re-inference
   - No model inference for recall—deterministic list formatting

4. CONVERSATION BROWSING
   - Read-only access to past interactions by date or topic
   - Search by keyword without modification
   - Session isolation and management

5. INTERACTIVE & SINGLE-SHOT MODES
   - Multi-turn conversation with full context
   - Single-shot query execution
   - Natural input/output flow

6. WHISPER AUDIO TRANSCRIPTION
   - Audio-to-text conversion with explicit confirmation gate
   - TranscriptionArtifact for full auditability
   - No blind automation: user sees and approves every transcript
   - Deterministic transcription (same audio → same text)
   - Comprehensive logging of all transcription events

7. INTENT PARSING (No Execution)
   - Structured intent parsing from confirmed text
   - IntentArtifact with {verb, target, object, parameters}
   - Ambiguity preserved (never guessed)
   - Zero side effects: parsing only, no execution
   - Confirmation gate before downstream processing
   - Clean handoff to future execution layer

================================================================================
DEPENDENCIES
================================================================================

- Python 3.9+
- requests (HTTP library for Ollama API)
- ollama (Ollama Python wrapper)
- openai-whisper (Audio transcription with confirmation gate)
- memory.py (TF-IDF + topic retrieval)
- prefs.py (Preference detection and application)
- browsing.py (Conversation browser)
- transcription.py (Whisper integration with TranscriptionArtifact)
- intent.py (Intent parsing without execution)

================================================================================
"""

import sys
import os
import json
import uuid
import asyncio
import logging
import threading
import queue
from types import SimpleNamespace
from datetime import datetime
from pathlib import Path
from wrapper.conversation_history import (
    _append_daily_log,
    _get_log_dir,
    detect_context,
    detect_recall_query,
    format_recall_response,
    get_confidence_instruction,
)
from wrapper.behavior_policy import (
    FAMILIARITY_STATE,
    build_behavior_instruction,
    build_casual_humor_instruction,
    classify_query_type,
    detect_plausible_hallucination,
    get_familiarity_level,
    infer_canonical_knowledge,
    is_casual_question,
    select_behavior_profile,
    select_primary_frame,
    should_inject_observational_humor,
    update_familiarity,
    validate_human_first_sentence,
    validate_personality_discipline,
    validate_scope,
)
from wrapper.cli_policy import (
    classify_input,
    classify_verbosity,
    get_cli_formatting_suppression,
    get_persona_text,
    get_verbosity_text,
    validate_cli_format,
)
from wrapper.preflight import (
    dispatch_governance,
    dispatch_music_volume,
    dispatch_self_knowledge,
    neural_terminology_sink,
)
from wrapper.ollama_generation import generate_ollama_response
from wrapper.replay_context import build_replay_context

# Module-level logger (consistent with rest of system)
logger = logging.getLogger(__name__)

# Load .env configuration (must happen before other imports that read env vars)
# Important: override=False ensures shell environment variables take precedence
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # dotenv optional; use system environment variables if not installed

# Import Phase 4D drift monitor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from system.runtime.drift_monitor import get_drift_monitor

# Import Argo Memory (RAG-based interaction recall)
sys.path.insert(0, os.path.dirname(__file__))
from memory import find_relevant_memory, store_interaction, load_memory
from prefs import load_prefs, save_prefs, update_prefs, build_pref_block
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

# Import Intent Artifact System (structured intent parsing, no execution)
try:
    from intent import (
        create_intent_artifact,
        intent_storage,
        IntentArtifact
    )
    INTENT_AVAILABLE = True
except ImportError:
    INTENT_AVAILABLE = False
    # Intent system optional; graceful degradation if not installed

# Import Executable Intent System (plans from intents, no execution)
try:
    from executable_intent import (
        ExecutableIntentEngine,
        ExecutionPlanArtifact
    )
    EXECUTABLE_INTENT_AVAILABLE = True
except ImportError:
    EXECUTABLE_INTENT_AVAILABLE = False
    # Executable intent system optional; graceful degradation if not installed

# Import Execution Engine (simulation mode, v1.3.0-alpha & real execution, v1.4.0)
try:
    from execution_engine import (
        ExecutionEngine,
        DryRunExecutionReport,
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
    from core.output_sink import get_output_sink, set_output_sink, PiperOutputSink
    OUTPUT_SINK_AVAILABLE = True
except ImportError:
    OUTPUT_SINK_AVAILABLE = False
    # Output sink optional; graceful degradation if not installed

# Import State Machine (Phase 7B: Wake/sleep/stop control)
try:
    from core.state_machine import (
        State,
        StateMachine,
        get_state_machine,
        set_state_machine,
        WAKE_WORD_ENABLED,
        SLEEP_WORD_ENABLED
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
        get_detector
    )
    WAKE_WORD_DETECTOR_AVAILABLE = True
except ImportError:
    WAKE_WORD_DETECTOR_AVAILABLE = False
    # Wake-word detector optional; graceful degradation if not installed
    WakeWordDetector = object  # type: ignore
    WakeWordRequest = object  # type: ignore

# If wake-word module is removed, hard-disable wake-word handling
try:
    if not WAKE_WORD_DETECTOR_AVAILABLE:
        WAKE_WORD_ENABLED = False
except Exception:
    pass

# Import Command Parser (Phase 7B-3: Deterministic command classification)
try:
    from core.command_parser import (
        CommandClassifier,
        CommandType,
        ParsedCommand,
        get_classifier as get_command_classifier,
        set_classifier as set_command_classifier
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

MAX_VOICE_CHARS = 150

_output_queue: "queue.Queue[str]" = queue.Queue()
_output_thread: threading.Thread | None = None
_output_thread_lock = threading.Lock()


def _output_worker() -> None:
    """Background worker to send TTS output without blocking the main loop."""
    sink = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        text = _output_queue.get()
        if text is None:
            break
        if sink is None:
            try:
                sink = get_output_sink()
            except Exception as e:
                print(f"⚠ Audio output error: {e}", file=sys.stderr)
                sink = None
        if sink is None:
            continue
        try:
            loop.run_until_complete(sink.send(text))
        except Exception as e:
            print(f"⚠ Audio output error: {e}", file=sys.stderr)
    try:
        loop.stop()
    finally:
        loop.close()


def _start_output_thread() -> None:
    global _output_thread
    if _output_thread and _output_thread.is_alive():
        return
    if not OUTPUT_SINK_AVAILABLE or not VOICE_ENABLED or not PIPER_ENABLED:
        return
    with _output_thread_lock:
        if _output_thread and _output_thread.is_alive():
            return
        _output_thread = threading.Thread(
            target=_output_worker,
            name="ArgoOutputSink",
            daemon=True,
        )
        _output_thread.start()

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
    if not OUTPUT_SINK_AVAILABLE or not VOICE_ENABLED or not PIPER_ENABLED:
        return  # Audio disabled, text already printed

    spoken_text = text[:MAX_VOICE_CHARS]
    if len(text) > MAX_VOICE_CHARS:
        logger.debug(f"Capping voice output: {len(text)} → {MAX_VOICE_CHARS} chars")

    _start_output_thread()
    _output_queue.put(spoken_text)


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
    
    current_state = _state_machine.current_state
    
    # [DIAGNOSTIC] Log wake-word detection
    logger.warning("WAKE WORD DETECTED — FORCING RECORD")
    
    # Only process if in SLEEP or LISTENING
    if current_state not in ["SLEEP", "LISTENING"]:
        logger.debug(f"Wake-word ignored: in {current_state} state")
        return
    
    # If SLEEP → transition to LISTENING (this wakes the system)
    if current_state == "SLEEP":
        logger.info("Wake-word detected in SLEEP - transitioning to LISTENING")
        if not _state_machine.wake():
            logger.debug("State machine rejected wake transition")
            return
        current_state = "LISTENING"
    
    # Now record the spoken question
    try:
        from voice_input import record_audio_on_wake_word, transcribe_audio
        
        logger.info("Waking up - recording user's question...")
        audio = record_audio_on_wake_word()
        
        if audio is None or len(audio) == 0:
            logger.warning("No audio recorded after wake-word")
            return
        
        # Transcribe the question
        logger.info("Transcribing wake-word audio...")
        user_input = transcribe_audio(audio)
        
        if not user_input:
            logger.warning("No speech transcribed from wake-word recording")
            return
        
        logger.info(f"Wake-word transcription: '{user_input}'")
        
        # Process the command (transition to THINKING, generate LLM response, speak)
        if _command_parser and _state_machine:
            try:
                logger.debug(f"Sending wake-word command to parser: '{user_input}'")
                request = WakeWordRequest(confidence=0.95)
                _command_parser.process_wake_word_event(request)
            except Exception as e:
                logger.error(f"Error processing wake-word event: {e}")
    
    except Exception as e:
        logger.error(f"Error in wake-word callback: {e}")

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
    if _wake_word_detector:
        try:
            _wake_word_detector.start()
            logger.debug("Wake-word detector started")
        except Exception as e:
            logger.error(f"Error starting wake-word detector: {e}")

def stop_wake_word_detector():
    """
    Stop the wake-word detector.
    
    Called when exiting LISTENING state (e.g., entering SLEEP).
    """
    if _wake_word_detector:
        try:
            _wake_word_detector.stop()
            logger.debug("Wake-word detector stopped")
        except Exception as e:
            logger.error(f"Error stopping wake-word detector: {e}")

def pause_wake_word_detector():
    """
    Pause the wake-word detector (e.g., during PTT).
    
    Non-blocking pause; detector remains initialized but doesn't listen.
    Resumed after PTT completes.
    """
    if _wake_word_detector:
        try:
            _wake_word_detector.pause()
            logger.debug("Wake-word detector paused (PTT active)")
        except Exception as e:
            logger.error(f"Error pausing wake-word detector: {e}")

def resume_wake_word_detector():
    """
    Resume the wake-word detector after pause.
    
    Called after PTT completes; detector resumes listening.
    """
    if _wake_word_detector:
        try:
            _wake_word_detector.resume()
            logger.debug("Wake-word detector resumed")
        except Exception as e:
            logger.error(f"Error resuming wake-word detector: {e}")

def get_wake_word_detector_status() -> dict:
    """Get wake-word detector status for diagnostics."""
    if _wake_word_detector:
        return _wake_word_detector.get_status()
    return {"available": False}




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
    os.makedirs(_get_log_dir(), exist_ok=True)

    # Load existing sessions
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            sessions = json.load(f)
    else:
        sessions = {}

    # Create new session if needed
    if name not in sessions:
        sessions[name] = str(uuid.uuid4())
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=2)

    return sessions[name]


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
    def _failure_artifact(status: str, reason: str):
        """Create a failure artifact for blocked/unavailable transcription paths."""
        if "TranscriptionArtifact" in globals() and TranscriptionArtifact:
            artifact = TranscriptionArtifact()
            artifact.source_audio = audio_path
            artifact.transcript_text = None
            artifact.language_detected = None
            artifact.confidence = 0.0
            artifact.status = status
            artifact.error_detail = reason
            artifact.confirmation_status = "rejected"
            return artifact
        return SimpleNamespace(
            id=None,
            timestamp=None,
            source_audio=audio_path,
            transcript_text=None,
            language_detected=None,
            confidence=0.0,
            status=status,
            error_detail=reason,
            confirmation_status="rejected",
        )

    # Short-circuit missing files before listening gate (explicit failure artifact)
    if audio_path and not Path(audio_path).exists():
        reason = f"Audio file not found: {audio_path}"
        return False, "", _failure_artifact("failure", reason)

    # [Phase 7B] Gate: Check if listening is enabled
    if STATE_MACHINE_AVAILABLE and _state_machine:
        if not _state_machine.listening_enabled():
            reason = "Microphone input blocked: not in LISTENING state"
            print(f"⚠ {reason}", file=sys.stderr)
            return False, "", _failure_artifact("blocked", reason)
    
    if not WHISPER_AVAILABLE:
        reason = "Whisper not installed. Run: pip install openai-whisper"
        print(f"⚠ {reason}", file=sys.stderr)
        return False, "", _failure_artifact("failure", reason)
    
    # Transcribe audio file
    print(f"\n🎤 Transcribing audio...", file=sys.stderr)
    artifact = transcribe_audio(audio_path, max_duration_seconds=max_duration_seconds)
    
    # Handle transcription failure
    if artifact.status == "failure":
        print(f"❌ Transcription failed: {artifact.error_detail}", file=sys.stderr)
        return False, "", artifact
    
    if artifact.status == "partial":
        print(f"⚠ Partial transcription: {artifact.error_detail}", file=sys.stderr)
    
    # Display confirmation gate (core philosophy)
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"Here's what I heard:", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\n  \"{artifact.transcript_text}\"", file=sys.stderr)
    print(f"\nLanguage: {artifact.language_detected} | Confidence: {artifact.confidence:.0%}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\nProceed with this transcript? (yes/no): ", end="", file=sys.stderr)
    sys.stderr.flush()
    
    # Get user confirmation
    try:
        response = input().strip().lower()
    except EOFError:
        # Piped input or non-interactive: assume no confirmation
        response = "no"
    
    # Process confirmation
    if response in ["yes", "y", "yep", "yeah", "ok", "sure"]:
        transcription_storage.confirm(artifact.id)
        print(f"✅ Confirmed. Processing transcript...\n", file=sys.stderr)
        return True, artifact.transcript_text, artifact
    else:
        transcription_storage.reject(artifact.id)
        print(f"❌ Rejected. Please try again.\n", file=sys.stderr)
        return False, "", artifact


# ============================================================================
# INTENT ARTIFACT CONFIRMATION GATE
# ============================================================================

def intent_and_confirm(raw_text: str, source_type: str = "typed") -> tuple:
    """
    Parse user input into structured intent and request confirmation.
    
    ARGO's philosophy on intent parsing:
      1. Text in → structured intent out (pure parsing)
      2. Display parsed structure to user
      3. Wait for explicit confirmation
      4. Only confirmed intents advance to future execution layer
    
    This function enforces the confirmation gate: users must see what the
    intent parser understood before any downstream processing. No blind
    automation. No guessing.
    
    Args:
        raw_text: Confirmed user input (typed or from transcription)
        source_type: "typed" (default) or "transcription"
    
    Returns:
        tuple: (confirmed: bool, artifact: IntentArtifact)
               - confirmed: True if user approved, False if rejected
               - artifact: Full artifact with parsed intent (for audit/logging)
    
    Example:
        confirmed, artifact = intent_and_confirm(user_text)
        
        if confirmed:
            # Safe to pass to future execution layer
            # artifact.parsed_intent contains {verb, target, object, ...}
            process_approved_intent(artifact)
        else:
            print("Intent rejected. Please try again.")
    """
    if not INTENT_AVAILABLE:
        print("⚠ Intent system not available. Run: pip install (already in requirements.txt)", file=sys.stderr)
        return False, None
    
    # Parse intent deterministically
    artifact = create_intent_artifact(raw_text, source_type=source_type)
    
    # Display confirmation gate
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"Is this what you want to do?", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\nRaw text: \"{artifact.raw_text}\"", file=sys.stderr)
    print(f"\nIntent: {json.dumps(artifact.parsed_intent, indent=2)}", file=sys.stderr)
    print(f"\nConfidence: {artifact.confidence:.0%}", file=sys.stderr)
    
    if artifact.parsed_intent.get("ambiguity"):
        print(f"⚠ Ambiguities: {', '.join(artifact.parsed_intent['ambiguity'])}", file=sys.stderr)
    
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"Approve? (yes/no): ", end="", file=sys.stderr)
    sys.stderr.flush()
    
    # Get user confirmation
    try:
        response = input().strip().lower()
    except EOFError:
        # Piped input: assume no confirmation
        response = "no"
    
    # Process confirmation
    if response in ["yes", "y", "yep", "yeah", "ok", "sure"]:
        intent_storage.approve(artifact.id)
        print(f"✅ Approved. Intent will be processed.\n", file=sys.stderr)
        return True, artifact
    else:
        intent_storage.reject(artifact.id)
        print(f"❌ Rejected. Please try again.\n", file=sys.stderr)
        return False, artifact


def plan_and_confirm(intent_artifact: IntentArtifact) -> tuple:
    """
    Derive an execution plan artifact from a confirmed intent and request plan confirmation.
    
    ARGO's philosophy on planning (v1.2.0):
      1. Intent in → execution plan artifact out (planning only, no execution)
      2. Analyze risks, rollback procedures, confirmations needed
      3. Display plan summary to user
      4. Wait for explicit plan confirmation
      5. Only confirmed plans advance to execution layer (v1.3.0)
    
    Plan artifacts describe WHAT will happen and HOW it will happen.
    Plans do NOT execute anything.
    
    Args:
        intent_artifact: Confirmed IntentArtifact from intent_and_confirm()
    
    Returns:
        tuple: (confirmed: bool, plan: ExecutionPlanArtifact)
               - confirmed: True if user approved plan, False if rejected
               - plan: Full plan artifact with steps, risks, rollback procedures
    
    Example:
        confirmed, artifact = intent_and_confirm(user_text)
        if confirmed:
            plan_confirmed, plan = plan_and_confirm(artifact)
            if plan_confirmed:
                # Ready for v1.3.0 execution layer
                execute_plan(plan)
    """
    if not EXECUTABLE_INTENT_AVAILABLE:
        print("⚠ Executable intent system not available.", file=sys.stderr)
        return False, None
    
    # Initialize engine
    engine = ExecutableIntentEngine()
    
    # Derive plan artifact from intent
    plan = engine.plan_from_intent(
        intent_id=intent_artifact.id,
        intent_text=intent_artifact.raw_text,
        parsed_intent=intent_artifact.parsed_intent
    )
    
    # Display plan confirmation gate
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"Here's the plan:", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\n{plan.summary()}", file=sys.stderr)
    print(f"\n{'='*70}", file=sys.stderr)
    
    if plan.has_irreversible_actions:
        print(f"⚠️  WARNING: This plan includes irreversible actions (no undo).", file=sys.stderr)
    
    if plan.total_confirmations_needed > 0:
        print(f"ℹ️  This plan requires {plan.total_confirmations_needed} confirmation(s) during execution.", file=sys.stderr)
    
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"Proceed with this plan? (yes/no): ", end="", file=sys.stderr)
    sys.stderr.flush()
    
    # Get user confirmation
    try:
        response = input().strip().lower()
    except EOFError:
        # Piped input: assume no confirmation
        response = "no"
    
    # Process confirmation
    if response in ["yes", "y", "yep", "yeah", "ok", "sure"]:
        plan.status = "awaiting_execution"
        print(f"✅ Plan approved. Ready for execution.\n", file=sys.stderr)
        return True, plan
    else:
        plan.status = "rejected"
        print(f"❌ Plan rejected. No changes will be made.\n", file=sys.stderr)
        return False, plan


def dry_run_and_confirm(plan_artifact: ExecutionPlanArtifact) -> tuple:
    """
    Simulate execution of a plan and request user approval (v1.3.0-alpha).
    
    ARGO's philosophy on execution validation:
      1. Plan artifact in → DryRunExecutionReport out (simulation only, NO changes)
      2. Validate all preconditions (symbolically)
      3. Predict state changes (text descriptions only)
      4. Validate rollback procedures
      5. Identify failure modes
      6. Display safety analysis to user
      7. Wait for explicit execution approval
      8. Only approved plans advance to actual execution (v1.4.0+)
    
    Reports contain:
      - Full simulation results per step
      - Precondition status (MET/UNKNOWN/UNMET)
      - Predicted state changes (text only, not executed)
      - Rollback procedure validation
      - Failure mode enumeration
      - Risk analysis (SAFE/CAUTIOUS/RISKY/CRITICAL)
      - Execution feasibility verdict
    
    HARD CONSTRAINT: This function makes ZERO changes to system state.
    All simulation is symbolic. No files created, no commands executed.
    
    Args:
        plan_artifact: ExecutionPlanArtifact from plan_and_confirm()
        intent_id: Optional - ID of parent IntentArtifact
        transcription_id: Optional - ID of parent TranscriptionArtifact
    
    Returns:
        tuple: (approved: bool, report: DryRunExecutionReport)
               - approved: True if user approved execution, False if rejected
               - report: Complete simulation results
    
    Example:
        plan_confirmed, plan = plan_and_confirm(intent)
        if plan_confirmed:
            approved, report = dry_run_and_confirm(plan)
            if approved:
                # Ready for v1.4.0 actual execution
                execute_plan_for_real(plan, report)
    """
    if not EXECUTION_ENGINE_AVAILABLE:
        print("⚠ Execution engine (v1.3.0) not available.", file=sys.stderr)
        return False, None
    
    # Initialize execution engine
    engine = ExecutionEngine()
    
    # Simulate execution (NO REAL CHANGES)
    report = engine.dry_run(
        plan=plan_artifact,
        intent_id=getattr(plan_artifact, 'intent_id', None),
        transcription_id=getattr(plan_artifact, 'transcription_id', None)
    )
    
    # Display dry-run results
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"DRY-RUN SIMULATION RESULTS", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"\n{report.summary()}", file=sys.stderr)
    print(f"\n{'='*70}", file=sys.stderr)
    
    # Risk warnings
    if report.highest_risk_detected == "critical":
        print(f"🚨 CRITICAL RISK: This plan has irreversible actions.", file=sys.stderr)
        print(f"   Proceed only if you understand the consequences.", file=sys.stderr)
    elif report.highest_risk_detected == "risky":
        print(f"⚠️  RISKY: Partial rollback available if execution fails.", file=sys.stderr)
    elif report.highest_risk_detected == "cautious":
        print(f"ℹ️  CAUTION: Plan is fully reversible but changes system state.", file=sys.stderr)
    
    if not report.execution_feasible:
        print(f"\n❌ EXECUTION NOT FEASIBLE: {report.blocking_reason}", file=sys.stderr)
        print(f"   Simulation indicates this plan cannot be executed safely.", file=sys.stderr)
        return False, report
    
    # Approval request
    print(f"\n{'='*70}", file=sys.stderr)
    if report.highest_risk_detected == "safe":
        print(f"Approve execution of this plan? (yes/no): ", end="", file=sys.stderr)
    else:
        print(f"⚠️  Execute despite {report.highest_risk_detected} risk? (yes/no): ", end="", file=sys.stderr)
    sys.stderr.flush()
    
    # Get user approval
    try:
        response = input().strip().lower()
    except EOFError:
        # Piped input: assume no approval
        response = "no"
    
    # Process approval
    if response in ["yes", "y", "yep", "yeah", "ok", "sure"]:
        report.user_approved_execution = True
        print(f"✅ Execution approved. Ready for real execution (v1.4.0+).\n", file=sys.stderr)
        return True, report
    else:
        report.user_approved_execution = False
        print(f"❌ Execution rejected. Plan will not be executed.\n", file=sys.stderr)
        return False, report


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
    
    # Sanity check: execution engine available?
    if not EXECUTION_ENGINE_AVAILABLE:
        print("❌ Execution engine not available. Cannot execute plan.", file=sys.stderr)
        return None
    
    # HARD GATES: All must pass
    
    # Gate 1: DryRunExecutionReport must exist
    if dry_run_report is None:
        print("❌ GATE 1 FAILED: No dry-run report provided. Execution aborted.", file=sys.stderr)
        print("   Simulation must complete successfully before execution.", file=sys.stderr)
        return None
    
    # Gate 2: Simulation status must be SUCCESS
    if dry_run_report.simulation_status != SimulationStatus.SUCCESS:
        print(f"❌ GATE 2 FAILED: Simulation status is {dry_run_report.simulation_status.value}.", file=sys.stderr)
        print("   Only SUCCESS simulations can be executed.", file=sys.stderr)
        if dry_run_report.blocking_reason:
            print(f"   Reason: {dry_run_report.blocking_reason}", file=sys.stderr)
        return None
    
    # Gate 3: User approval required
    if not user_approved:
        print("❌ GATE 3 FAILED: User has not approved execution.", file=sys.stderr)
        print("   Execution requires explicit confirmation.", file=sys.stderr)
        return None
    
    # Gate 4 & 5: Artifact IDs must match
    if dry_run_report.execution_plan_id != plan_artifact.plan_id:
        print("❌ GATES 4-5 FAILED: Artifact ID mismatch.", file=sys.stderr)
        print(f"   Report plan ID: {dry_run_report.execution_plan_id}", file=sys.stderr)
        print(f"   Artifact plan ID: {plan_artifact.plan_id}", file=sys.stderr)
        print("   Execution aborted to prevent mismatched execution.", file=sys.stderr)
        return None
    
    # ALL GATES PASSED - Execute the plan
    print("\n" + "="*70, file=sys.stderr)
    print("ALL HARD GATES PASSED - EXECUTING PLAN", file=sys.stderr)
    print("="*70, file=sys.stderr)
    
    # Create execution mode and execute
    execution_mode = ExecutionMode()
    
    result = execution_mode.execute_plan(
        dry_run_report=dry_run_report,
        plan_artifact=plan_artifact,
        user_approved=user_approved,
        intent_id=intent_id
    )
    
    # Report execution result
    if result.execution_status == ExecutionStatus.SUCCESS:
        print(f"\n✅ EXECUTION SUCCESSFUL", file=sys.stderr)
        print(f"   {result.steps_succeeded}/{result.total_steps} steps completed", file=sys.stderr)
    elif result.execution_status == ExecutionStatus.PARTIAL:
        print(f"\n⚠️  EXECUTION PARTIAL", file=sys.stderr)
        print(f"   {result.steps_succeeded}/{result.total_steps} steps succeeded", file=sys.stderr)
        print(f"   {result.steps_failed}/{result.total_steps} steps failed", file=sys.stderr)
    elif result.execution_status == ExecutionStatus.ROLLED_BACK:
        print(f"\n⚠️  EXECUTION ROLLED BACK", file=sys.stderr)
        print(f"   System state restored due to step failure", file=sys.stderr)
    elif result.execution_status == ExecutionStatus.ABORTED:
        print(f"\n❌ EXECUTION ABORTED", file=sys.stderr)
        print(f"   Reason: {result.abort_reason}", file=sys.stderr)
    
    return result


# ============================================================================
# PHASE 7B: STATE MACHINE INTEGRATION HELPERS
# ============================================================================
# Note: Command detection now handled by Phase 7B-3 CommandClassifier
# These helpers perform state transitions only


def _transition_to_thinking() -> bool:
    """
    Transition to THINKING state when command is accepted.
    
    Returns True if transition succeeded.
    """
    if not STATE_MACHINE_AVAILABLE or not _state_machine:
        return False
    
    if _state_machine.accept_command():
        print("[STATE] Accepted command (LISTENING -> THINKING)", file=sys.stderr)
        return True
    
    return False


def _transition_to_speaking() -> bool:
    """
    Transition to SPEAKING state when audio playback starts.
    
    Returns True if transition succeeded.
    """
    if not STATE_MACHINE_AVAILABLE or not _state_machine:
        return False
    
    if _state_machine.start_audio():
        print("[STATE] Starting audio (THINKING -> SPEAKING)", file=sys.stderr)
        return True
    
    return False


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
    global _send_to_output_sink
    # CRITICAL: Voice mode forces stateless execution
    if voice_mode:
        # Force stateless mode for voice input
        replay_n = None
        replay_session = False
        # Memory will be skipped below
    
    # Step 1: Load, update, and save user preferences
    prefs = load_prefs()
    prefs = update_prefs(user_input, prefs)
    save_prefs(prefs)
    
    # [Phase 7B-3] Step 1b: Parse and classify command
    # --- ARGO LAW & 5 GATES INTERCEPT ---
    if dispatch_music_volume(user_input, _send_to_output_sink):
        return

    repository_root = Path(__file__).resolve().parent.parent
    if dispatch_self_knowledge(user_input, _send_to_output_sink, repository_root):
        return

    _send_to_output_sink = neural_terminology_sink(_send_to_output_sink)
    if dispatch_governance(user_input, _send_to_output_sink):
        return
    if COMMAND_PARSER_AVAILABLE and _command_parser:
        parsed = _command_parser.parse(user_input)
        # Handle control commands (never reach LLM)
        if parsed.command_type == CommandType.STOP:
            # Hard stop: call OutputSink.stop() immediately
            if OUTPUT_SINK_AVAILABLE:
                try:
                    sink = get_output_sink()
                    sink.stop()
                    print("[AUDIO] Stopped playback (hard stop, <50ms latency)", file=sys.stderr)
                except Exception as e:
                    print(f"⚠ OutputSink.stop() error: {e}", file=sys.stderr)
            # Transition state
            if STATE_MACHINE_AVAILABLE and _state_machine:
                if _state_machine.stop_audio():
                    print("[STATE] Stopped audio (SPEAKING -> LISTENING)", file=sys.stderr)
            return
        elif parsed.command_type == CommandType.SLEEP:
            # Sleep command
            if STATE_MACHINE_AVAILABLE and _state_machine:
                if _state_machine.sleep():
                    print("[STATE] Going to sleep (-> SLEEP)", file=sys.stderr)
            return
        elif parsed.command_type == CommandType.WAKE:
            # Wake command
            if STATE_MACHINE_AVAILABLE and _state_machine:
                if _state_machine.wake():
                    print("[STATE] Woke up (SLEEP -> LISTENING)", file=sys.stderr)
            return
        # For ACTION and QUESTION, continue with cleaned text
        if parsed.command_type in (CommandType.ACTION, CommandType.QUESTION):
            user_input = parsed.cleaned_text
    
    # [Phase 7B] Step 1c: Transition to THINKING if we have a valid command in LISTENING state
    if STATE_MACHINE_AVAILABLE and _state_machine:
        if _state_machine.is_listening:
            _transition_to_thinking()
    
    # Step 2: Check if this is a recall/retrieval query (meta-question)
    is_recall, count_requested = detect_recall_query(user_input)
    
    if is_recall:
        # RECALL MODE: User asking for list of previous topics
        # Load all memory and format deterministically
        all_memory = load_memory()
        recall_output = format_recall_response(
            all_memory, 
            count=count_requested,
            prefs=prefs
        )
        print(recall_output)
        
        # Send to audio output (if enabled)
        _send_to_output_sink(recall_output)
        
        # IMPORTANT: Do NOT store recall queries to memory
        # Recall queries are meta-operations, not conversational content
        # Storing them would pollute memory with bookkeeping instead of conversation
        return
    
    # GENERATION MODE: Regular conversation
    # Step 3: Find relevant past interactions
    # CRITICAL: Skip memory injection in voice_mode for stateless execution (Option B compliance)
    relevant_memory = None
    if not voice_mode:
        relevant_memory = find_relevant_memory(user_input, top_n=2)
    
    # Step 4: Build memory context to inject
    memory_context = ""
    if relevant_memory and not voice_mode:
        memory_lines = []
        for item in relevant_memory:
            memory_lines.append(f"Past: {item['user_input']}")
            memory_lines.append(f"Response: {item['model_response']}")
        memory_context = "From your history:\n" + "\n".join(memory_lines) + "\n\n"
    
    # Step 5: Build preference context to inject
    pref_block = build_pref_block(prefs)
    
    # Step 6: Compose user input with preference + memory prefixes
    # CRITICAL: Skip memory prefix in voice_mode for stateless execution
    composed_input = user_input
    if not voice_mode:
        composed_input = pref_block + memory_context + user_input
    
    # [Phase 7B] Step 6b: Transition to SPEAKING before generating response
    _transition_to_speaking()
    
    # Step 7: Execute core logic with composed input
    _run_argo_internal(
        composed_input,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        strict_mode=strict_mode,
        persona=persona,
        verbosity=verbosity,
        replay_reason=replay_reason,
        voice_mode=voice_mode
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
    """
    Execute a single interaction with the Jarvis model.
    
    Flow:
    1. Classify input intent (gating check)
    2. Classify input verbosity (response length preference)
    3. Handle rejected input or route commands
    4. Optional replay: prepend previous turns to context (not sticky, skipped in voice_mode)
    5. Optional mode: inject mode enforcement rules
    6. Optional persona: inject tone adjustment (presentation only)
    7. Optional verbosity: inject response length control (presentation only)
    8. Send prompt to Ollama's "jarvis" model
    9. Log the interaction (user input, response, metadata)
    10. Print response to stdout
    
    Voice Mode (voice_mode=True):
    - Skips replay injection (always stateless)
    - Adds explicit stateless prompt guardrail
    - Enforces single-turn execution
    - CRITICAL for Option B compliance
    
    Intent Gating (strict mode):
    - "empty", "ambiguous", "low_intent" → reject and request clarification
    - "command" → route to command handler
    - "valid" → proceed to LLM
    
    In non-strict mode, all input proceeds to the LLM.
    
    Verbosity Classification:
    - Deterministic: if input contains long-form cues, set to "long", else "short"
    - Cues: "explain in detail", "detailed explanation", "walk me through", etc.
    - Effect: injects response-length instruction into prompt (presentation only)
    
    Persona: presentation-only adjustment to tone/style (does not affect logic).
    
    Replay is mutually exclusive:
    - replay_session=True: use all turns from current session
    - replay_n=N: use last N turns across all sessions
    - both False: no replay
    - voice_mode=True: forced to no replay (stateless)
    
    Logging captures:
    - Raw user input (before any injection)
    - Model response (or gating rejection if applicable)
    - Whether replay was used
    - Active mode (if any)
    - Persona (if not default)
    - Verbosity setting for this turn
    - Session ID and timestamp
    
    Args:
        user_input: User's raw message
        active_mode: Conversation mode name (e.g., "brainstorm") or None
        replay_n: If using --replay last:N, the value N; else None
        replay_session: True if using --replay session; False otherwise
        strict_mode: If True (default), reject low-intent input; if False, allow LLM to ask for clarification
        persona: Persona name for tone adjustment (default: "neutral")
        verbosity: Response length control, "short" or "long" (default: "short")
        voice_mode: If True, force stateless execution (no replay, no memory)
    """
    # ________________________________________________________________________
    # Step 0: Intent Classification & Gating
    # ________________________________________________________________________
    
    intent = classify_input(user_input)
    
    # ________________________________________________________________________
    # Step 0b: Verbosity Classification
    # ________________________________________________________________________
    
    # Classify response length preference based on explicit cues
    # Note: verbosity parameter can be overridden, but we compute from input
    classified_verbosity = classify_verbosity(user_input)
    
    # Handle invalid intent in strict mode
    if strict_mode and intent in ("empty", "ambiguous", "low_intent"):
        output = "Input is ambiguous. Please clarify what you want to do."
        
        # Send to audio output (if enabled)
        _send_to_output_sink(output)
        
        # Still log the interaction normally
        timestamp_iso = datetime.now().isoformat(timespec="seconds")
        _append_daily_log(
            timestamp_iso=timestamp_iso,
            session_id=SESSION_ID,
            user_prompt=user_input,
            model_response=output,
            active_mode=active_mode,
            replay_n=replay_n,
            replay_session=replay_session,
            persona=persona,
            verbosity=classified_verbosity,
        )
        
        print(output)
        return
    
    # Handle command routing (reserved for future use)
    if intent == "command":
        output = "Commands not yet implemented. Please provide a question or statement."
        
        # Still log the interaction normally
        timestamp_iso = datetime.now().isoformat(timespec="seconds")
        _append_daily_log(
            timestamp_iso=timestamp_iso,
            session_id=SESSION_ID,
            user_prompt=user_input,
            model_response=output,
            active_mode=active_mode,
            replay_n=replay_n,
            replay_session=replay_session,
            persona=persona,
            verbosity=classified_verbosity,
            replay_policy=None,
        )
        print(output)
        return
    # ________________________________________________________________________
    
    replay_context = build_replay_context(
        session_id=SESSION_ID,
        replay_n=replay_n,
        replay_session=replay_session,
        replay_reason=replay_reason,
        voice_mode=voice_mode,
    )
    replay_block = replay_context.block
    replay_policy = replay_context.policy
    context_strength = replay_context.context_strength

    # ________________________________________________________________________
    # Step 1.5: CLI Context Guard (Suppress GUI Explanations)
    # ________________________________________________________________________
    
    # In CLI context (headless execution), suppress GUI-specific explanations
    execution_context = detect_context()
    if execution_context == "cli":
        context_strength = "weak"  # Force minimal explanations in headless mode
    
    # ________________________________________________________________________
    # Step 1.6: Phase 4C Behavior Selection
    # ________________________________________________________________________
    
    query_type = classify_query_type(user_input)
    has_canonical_knowledge = infer_canonical_knowledge(user_input)
    behavior_profile = select_behavior_profile(query_type, context_strength, has_canonical_knowledge)
    
    # ________________________________________________________________________
    # Step 1.7: Phase 5A Judgment Gate (Single-Frame Selection)
    # ________________________________________________________________________
    
    # PATCH 5B.2: Pass is_casual_q to select_primary_frame for frame correction
    is_casual_q = is_casual_question(user_input)  # Detect early for frame selection
    primary_frame = select_primary_frame(query_type, context_strength, is_casual_q)
    
    # ________________________________________________________________________
    # Step 1.8: Phase 5B Familiarity Check & Phase 5B.2 Casual Question Detection
    # ________________________________________________________________________
    
    familiarity_level = get_familiarity_level()
    # is_casual_q already detected in Step 1.7 for frame correction
    
    # ________________________________________________________________________
    # Step 1.9: Build behavior instruction with frame & personality enforcement
    # ________________________________________________________________________
    
    behavior_instruction = build_behavior_instruction(behavior_profile, execution_context, has_canonical_knowledge, primary_frame, familiarity_level, user_input, is_casual_q, voice_mode)
    
    # Phase 4C may override verbosity classification
    if behavior_profile["verbosity_override"]:
        classified_verbosity = behavior_profile["verbosity_override"]
    
    # ________________________________________________________________________
    # Step 1.9: Phase 4D Pre-Generation Honesty Enforcement
    # ________________________________________________________________________
    
    drift_monitor = get_drift_monitor()
    
    # Check if we should enforce uncertainty
    query_demands_certainty = query_type == "factual" or query_type == "instructional"
    uncertainty_enforcement = drift_monitor.check_preconditions_uncertainty(
        query_type=query_type,
        has_canonical_knowledge=has_canonical_knowledge,
        query_demands_certainty=query_demands_certainty,
    )
    
    # Get current corrective behavior overrides (from drift signals)
    drift_corrections = drift_monitor.apply_corrections()
    
    # Apply drift corrections to behavior profile
    if drift_corrections.get("force_verbosity"):
        classified_verbosity = drift_corrections["force_verbosity"]
    if drift_corrections.get("force_explanation_depth"):
        behavior_profile["explanation_depth"] = drift_corrections["force_explanation_depth"]
    
    # ________________________________________________________________________
    # Step 2: Build final prompt
    # ________________________________________________________________________
    
    # Get persona text (may be empty for neutral)
    persona_text = get_persona_text(persona)
    
    # Get verbosity text (always present: either concise or detailed instruction)
    verbosity_text = get_verbosity_text(classified_verbosity)
    
    # Get CLI formatting suppression (if any)
    cli_formatting_text = get_cli_formatting_suppression(execution_context)
    
    # Get confidence instruction based on context strength
    confidence_text = get_confidence_instruction(context_strength)
    
    # Get uncertainty enforcement if applicable
    uncertainty_text = ""
    if uncertainty_enforcement:
        uncertainty_text = (
            "You lack canonical knowledge on this topic. "
            "Provide only what you can verify. "
            f"Required phrasing: {uncertainty_enforcement['require_phrases'][0]}. "
            f"Prohibited: {', '.join(uncertainty_enforcement['prohibit_phrases'])}. "
            "Declare gaps explicitly."
        )
    
    # Build prompt: mode enforcement (if any) -> persona (if any) -> behavior -> uncertainty (if any) -> verbosity -> cli formatting (if any) -> confidence -> replay -> user input
    prompt_parts = []
    
    # SYSTEM OVERRIDE: Inject confidence-first bias as an ironclad first-line constraint
    # When trusted + casual, this MUST be the very first thing the model processes
    if familiarity_level == "trusted" and is_casual_q:
        prompt_parts.append(
            "RESPOND ACCORDING TO THIS CONSTRAINT, NO EXCEPTIONS:\n\n"
            "Your first sentence must be a direct claim about causation.\n"
            "Your first sentence MUST start with exactly one of these:\n"
            "1. \"People do this because\"\n"
            "2. \"What's really happening is\"\n"
            "3. \"This happens because\"\n\n"
            "Your first sentence MUST NOT start with any of these:\n"
            "- \"The phenomenon\"\n"
            "- \"This behavior\"\n"
            "- \"In humans\"\n"
            "- \"This can be attributed\"\n"
            "- \"Research suggests\"\n\n"
            "After you answer the first sentence, you can explain as needed.\n"
            "But DO NOT open with academic framing or neutral exposition.\n"
            "Stay in human voice from the first word."
        )
    
    if active_mode:
        prompt_parts.append(MODE_ENFORCEMENT)
    if persona_text:
        prompt_parts.append(persona_text)
    prompt_parts.append(behavior_instruction)
    if uncertainty_text:
        prompt_parts.append(uncertainty_text)
    prompt_parts.append(verbosity_text)
    if cli_formatting_text:
        prompt_parts.append(cli_formatting_text)
    prompt_parts.append(confidence_text)
    if replay_block:
        prompt_parts.append(replay_block.rstrip())
    prompt_parts.append(user_input)
    
    full_prompt = "\n\n".join(prompt_parts).encode("utf-8")

    # ________________________________________________________________________
    # ________________________________________________________________________
    # Step 3: Call Ollama (with streaming output)
    # ________________________________________________________________________

    output = generate_ollama_response(full_prompt)

    # Send response to audio output (if VOICE_ENABLED and PIPER_ENABLED)
    # This call blocks until audio playback completes
    _send_to_output_sink(output)
    
    # [CRITICAL FIX] Transition from SPEAKING back to LISTENING after audio completes
    # This ensures the state machine doesn't get stuck in SPEAKING state
    if STATE_MACHINE_AVAILABLE and _state_machine:
        # Only transition if currently in SPEAKING state
        if _state_machine.current_state == "SPEAKING":
            if not _state_machine.stop_audio():
                logger.warning("Failed to transition from SPEAKING to LISTENING after audio playback")
        # Resume wake-word detector in case it was paused
        if WAKE_WORD_DETECTOR_AVAILABLE:
            resume_wake_word_detector()

    # ________________________________________________________________________
    # Step 4: Post-Generation Violation Detection & Logging
    # ________________________________________________________________________
    
    # Validate CLI format (if CLI context)
    cli_format_valid, cli_format_error = validate_cli_format(output, execution_context)
    if not cli_format_valid:
        print(f"⚠ CLI Format Violation: {cli_format_error}", file=sys.stderr)
    
    # Validate scope (Phase 5A judgment gate)
    scope_valid, scope_drift = validate_scope(output)
    if not scope_valid:
        # Soft failure: log drift, apply temporary compression bias
        drift_monitor.flag_signal("scope_expansion", {"force_verbosity": "short"}, duration=2)
    
    # Validate personality discipline (Phase 5B) and check casual humor (Phase 5B.2)
    personality_valid, personality_violation, soft_failure = validate_personality_discipline(output, query_type, has_canonical_knowledge, execution_context, is_casual_q)
    if not personality_valid:
        # Hard failure: personality violation revokes personality
        update_familiarity(False, "personality_discipline")
    elif soft_failure:
        # Soft failure: casual question where observational opener was missing
        # Log it but don't demote
        pass  # Logged implicitly, no state change
    else:
        # No violation: update familiarity on success
        update_familiarity(True)
    
    # PATCH 5B.2: Validate human-first sentence for casual + human frame
    human_first_valid, human_first_violation = validate_human_first_sentence(output, is_casual_q, primary_frame)
    if not human_first_valid:
        # Hard failure: casual human frame requires human-centered opening
        update_familiarity(False, "frame_blending")  # Treat as frame violation
    
    # PATCH 5B.2: Check for plausible hallucinations without canonical grounding
    grounding_valid, grounding_violation = detect_plausible_hallucination(output, has_canonical_knowledge, primary_frame)
    if not grounding_valid:
        # Soft failure: biological claim without grounding or downgrade language
        # Log only, no demotion (user can still use plain-language explanation)
        pass
    
    # Log interaction for drift analysis
    drift_monitor.log_interaction(
        user_prompt=user_input,
        model_response=output,
        query_type=query_type,
        has_canonical_knowledge=has_canonical_knowledge,
        behavior_profile=behavior_profile,
        verbosity=classified_verbosity,
    )
    
    # Detect violations (post-generation)
    violations = drift_monitor.detect_violations()
    
    # Detect drift signals
    drift_signals = drift_monitor.detect_drift()
    
    # Flag any new drift signals for correction
    for signal in drift_signals:
        drift_monitor.flag_signal(
            signal["signal"],
            signal["corrective_action"],
            signal["duration_turns"],
        )
    
    # ________________________________________________________________________
    # Step 5: Build Final Log Record
    # ________________________________________________________________________
    
    timestamp_iso = datetime.now().isoformat(timespec="seconds")
    
    # Build behavior log record
    behavior_log = {
        "query_type": query_type,
        "verbosity_override": behavior_profile["verbosity_override"],
        "explanation_depth": behavior_profile["explanation_depth"],
        "correction_style": behavior_profile["correction_style"],
    }
    
    # Build honesty enforcement log
    honesty_log = {
        "uncertainty_enforced": uncertainty_enforcement is not None,
        "violations_detected": len(violations),
        "drift_signals_detected": len(drift_signals),
    }
    
    if violations:
        honesty_log["violations"] = [v["type"] for v in violations]
    if drift_signals:
        honesty_log["drift_signals"] = [s["signal"] for s in drift_signals]
    
    _append_daily_log(
        timestamp_iso=timestamp_iso,
        session_id=SESSION_ID,
        user_prompt=user_input,
        model_response=output,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        persona=persona,
        verbosity=classified_verbosity,
        replay_policy=replay_policy,
        behavior_profile=behavior_log,
        honesty_enforcement=honesty_log,
    )
    
    # Store to Argo Memory (RAG-based interaction recall)
    # Strip any composed memory context from the original input before storing
    original_input = user_input
    if original_input.startswith("From your history:"):
        # Extract the original input after the memory context prefix
        parts = original_input.split("\n\n", 1)
        if len(parts) > 1:
            original_input = parts[1]
    store_interaction(original_input, output)


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    # ________________________________________________________________________
    # Argument Parsing & Interactive Mode Detection
    # ________________________________________________________________________
    
    session_name: str | None = None
    mode_value: str | None = None
    persona_value: str = "neutral"
    replay_n: int | None = None
    replay_session: bool = False
    strict_mode: bool = True
    interactive_mode: bool = False
    user_message: str = ""
    transcribe_file: str | None = None
    
    args = sys.argv[1:]

    # Parse --transcribe flag (transcribe audio file and get confirmation)
    if len(args) >= 2 and args[0] == "--transcribe":
        transcribe_file = args[1]
        args = args[2:]

    # Parse flags FIRST (works for both interactive and non-interactive)
    if len(args) >= 2 and args[0] == "--session":
        session_name = args[1]
        args = args[2:]

    if len(args) >= 2 and args[0] == "--mode":
        mode_value = args[1]
        args = args[2:]

    if len(args) >= 2 and args[0] == "--persona":
        persona_value = args[1]
        args = args[2:]

    if len(args) >= 1 and args[0] == "--strict":
        args = args[1:]
        if len(args) >= 1 and args[0] in ("off", "false", "0"):
            strict_mode = False
            args = args[1:]

    if len(args) >= 2 and args[0] == "--replay":
        value = args[1]
        if value == "session":
            replay_session = True
        elif value.startswith("last:"):
            try:
                replay_n = int(value.split(":", 1)[1])
            except ValueError:
                print("Invalid replay value. Use last:N or session", file=sys.stderr)
                sys.exit(1)
        else:
            print("Invalid replay value. Use last:N or session", file=sys.stderr)
            sys.exit(1)
        args = args[2:]

    # Parse --voice flag (enable audio output)
    if len(args) >= 1 and args[0] == "--voice":
        os.environ["VOICE_ENABLED"] = "true"
        os.environ["PIPER_ENABLED"] = "true"
        args = args[1:]
    
    # Parse --no-voice flag (disable audio output)
    if len(args) >= 1 and args[0] == "--no-voice":
        os.environ["VOICE_ENABLED"] = "false"
        os.environ["PIPER_ENABLED"] = "false"
        args = args[1:]

    # ________________________________________________________________________
    # Handle Transcription (if --transcribe flag provided)
    # ________________________________________________________________________
    
    if transcribe_file:
        # Transcribe audio and get user confirmation
        confirmed, transcript, artifact = transcribe_and_confirm(transcribe_file)
        
        if not confirmed:
            sys.exit(1)
        
        # Use transcribed text as the message
        user_message = transcript
        interactive_mode = False
    else:
        # NOW check if interactive mode (after flags consumed, if anything remains, it's the message)
        user_message = " ".join(args)
        if not user_message:
            interactive_mode = True
        else:
            interactive_mode = False

    # ________________________________________________________________________
    # Resolve Session ID (shared across all turns in interactive mode)
    # ________________________________________________________________________
    
    if session_name:
        SESSION_ID = resolve_session_id(session_name)
    else:
        SESSION_ID = str(uuid.uuid4())

    # ________________________________________________________________________
    # Main Execution Loop
    # ________________________________________________________________________
    
    if interactive_mode:
        # Interactive mode: continuous prompt loop
        print("\n📌 Interactive Mode (Voice PTT - Hold SPACEBAR to speak)\n", file=sys.stderr)
        
        # [CRITICAL] Start continuous audio stream for wake-word detection
        # This enables hands-free "Argo" to work
        try:
            from voice_input import start_continuous_audio_stream, stop_continuous_audio_stream
            if not start_continuous_audio_stream():
                logger.warning("Failed to start continuous audio stream (wake-word will not work)")
        except Exception as e:
            logger.warning(f"Error starting audio stream: {e}")
        
        # Try to load voice input module
        voice_input_available = False
        try:
            # Add parent directory to path to import voice_input.py
            parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
            
            # Test if keyboard module is available (required for PTT)
            # Note: On Windows, keyboard module requires administrator privileges
            try:
                import keyboard
                logger.debug("✓ keyboard module imported successfully")
                # Successfully imported - keyboard module is available
                from voice_input import get_voice_input_ptt
                logger.debug("✓ voice_input module imported successfully")
                voice_input_available = True
            except ImportError as e:
                logger.debug(f"✗ keyboard/voice_input import failed: {e}")
                print(f"⚠️  Voice input not available (ImportError: {e}), falling back to text input", file=sys.stderr)
                print("    To enable PTT: pip install keyboard", file=sys.stderr)
        except Exception as e:
            logger.debug(f"✗ Unexpected error in voice_input init: {e}")
            print(f"⚠️  Voice input not available ({e}), falling back to text input", file=sys.stderr)
        
        try:
            while True:
                try:
                    # Track whether THIS specific input came from voice
                    input_was_from_voice = False
                    
                    # Use voice input if available AND stdin is a TTY (interactive terminal)
                    # When stdin is piped, skip PTT and use text input instead
                    is_interactive = sys.stdin.isatty()
                    
                    if voice_input_available and is_interactive:
                        print("\n🎤 Hold SPACEBAR to record (or type 'exit' to quit):", file=sys.stderr)
                        
                        # Pause wake-word detector during PTT (PTT always overrides wake-word)
                        pause_wake_word_detector()
                        
                        try:
                            user_input = get_voice_input_ptt().strip()
                        finally:
                            # Resume detector after PTT completes
                            resume_wake_word_detector()
                        
                        input_was_from_voice = True  # CRITICAL: Mark that this input came from voice
                        if not user_input:
                            continue
                    else:
                        user_input = input("argo > ").strip()
                        input_was_from_voice = False  # Text input from keyboard
                    
                    # Check for exit commands
                    if user_input.lower() in ("exit", "quit"):
                        print("\nGoodbye.", file=sys.stderr)
                        break
                    
                    # Skip empty input
                    if not user_input:
                        continue
                    
                    # Check for conversation browser commands
                    if user_input.lower().startswith("list conversations"):
                        print(list_conversations())
                        continue
                    
                    if user_input.lower().startswith("show yesterday"):
                        print(show_by_date("yesterday"))
                        continue
                    
                    if user_input.lower().startswith("show today"):
                        print(show_by_date("today"))
                        continue
                    
                    if user_input.lower().startswith("show ") and user_input.lower().count("-") == 2:
                        # Date format: show YYYY-MM-DD
                        date_part = user_input[5:].strip()
                        print(show_by_date(date_part))
                        continue
                    
                    if user_input.lower().startswith("show topic "):
                        topic = user_input[11:].strip()
                        print(show_by_topic(topic))
                        continue
                    
                    if user_input.lower().startswith("open "):
                        topic_or_idx = user_input[5:].strip()
                        success, msg, context = get_conversation_context(topic_or_idx)
                        print(msg)
                        if success and context:
                            # Load context into memory for continuation
                            # Inject context as preamble for next query
                            print("(Ready to continue. Type your next question.)", file=sys.stderr)
                        continue
                    
                    if user_input.lower().startswith("summarize "):
                        topic_or_idx = user_input[10:].strip()
                        print(summarize_conversation(topic_or_idx))
                        continue
                    
                    if user_input.lower().startswith("summarize last"):
                        # Summarize most recent conversation
                        print(summarize_conversation("last"))
                        continue
                    
                    # Regular query (non-browser command)
                    run_argo(
                        user_input,
                        active_mode=mode_value,
                        replay_n=replay_n,
                        replay_session=replay_session,
                        strict_mode=strict_mode,
                        persona=persona_value,
                        voice_mode=input_was_from_voice  # CRITICAL: Only True if THIS input came from voice PTT
                    )
                    print()  # Blank line between turns
                    
                except KeyboardInterrupt:
                    # Ctrl+C: interrupt current response but stay in loop
                    print("\n[Interrupted. Type your next question or 'exit' to quit]\n", file=sys.stderr)
                    continue
        except EOFError:
            # Ctrl+D or piped input ends loop gracefully
            print("\nSession ended.", file=sys.stderr)
    else:
        # Single-shot mode: execute once and exit
        run_argo(
            user_message,
            active_mode=mode_value,
            replay_n=replay_n,
            replay_session=replay_session,
            strict_mode=strict_mode,
            persona=persona_value
        )
