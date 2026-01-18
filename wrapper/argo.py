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
from datetime import datetime
from pathlib import Path
import requests

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

def _send_to_output_sink(text: str) -> None:
    """
    Bridge between sync CLI context and async OutputSink.
    
    If VOICE_ENABLED and PIPER_ENABLED:
    - Try to use existing event loop if available (FastAPI)
    - Fall back to new event loop for CLI
    
    If disabled or unavailable:
    - No-op (text already printed to stdout)
    
    Args:
        text: Text to send to audio output
    """
    if not OUTPUT_SINK_AVAILABLE or not VOICE_ENABLED or not PIPER_ENABLED:
        return  # Audio disabled, text already printed
    
    try:
        sink = get_output_sink()
        
        # Try to get existing event loop (FastAPI context)
        try:
            loop = asyncio.get_running_loop()
            # We're in async context, create task to send
            asyncio.create_task(sink.send(text))
        except RuntimeError:
            # No running loop, create one for CLI
            asyncio.run(sink.send(text))
    except Exception as e:
        # Gracefully degrade: log error but don't crash
        print(f"⚠ Audio output error: {e}", file=sys.stderr)


# ============================================================================
# Session Management
# ============================================================================

# Define a system-wide session identifier
SESSION_ID = str(uuid.uuid4())
"""Unique identifier for this execution. Set in __main__ based on CLI args."""


def _get_log_dir() -> str:
    """
    Resolve the log directory path.
    
    Logs are stored in: <workspace_root>/logs/
    One file per day: YYYY-MM-DD.log
    Format: newline-delimited JSON (NDJSON)
    
    Returns:
        str: Absolute path to the logs directory.
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base_dir, "logs")


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

def classify_input(user_input: str) -> str:
    """
    Classify user input to determine if it's intentional and unambiguous.
    
    Intent classification is deterministic and rule-based:
    - "empty": whitespace-only input
    - "command": input starting with /argo (reserved for system commands)
    - "ambiguous": exactly 1 word (too vague)
    - "low_intent": 2 words (barely enough context)
    - "valid": 3+ words (sufficient intent signal)
    
    This prevents the LLM from being invoked on minimal input where the
    user likely hasn't fully formed their intent.
    
    Args:
        user_input: Raw user input
        
    Returns:
        str: One of: "empty", "command", "ambiguous", "low_intent", "valid"
    """
    # Classify empty/whitespace
    if not user_input or not user_input.strip():
        return "empty"
    
    # Classify commands (reserved syntax)
    if user_input.strip().startswith("/argo"):
        return "command"
    
    # Count words (split on whitespace)
    words = user_input.strip().split()
    word_count = len(words)
    
    if word_count == 1:
        return "ambiguous"
    elif word_count == 2:
        return "low_intent"
    else:
        return "valid"


# ============================================================================
# Verbosity Classification & Control
# ============================================================================

LONG_FORM_CUES = (
    "explain in detail",
    "detailed explanation",
    "walk me through",
    "deep dive",
    "step by step",
    "full explanation",
)
"""
Explicit cues that trigger long-form responses.
All matches are case-insensitive substring matches.
"""


def classify_verbosity(user_input: str) -> str:
    """
    Classify user input to determine desired response length.
    
    Verbosity classification is deterministic and rule-based:
    - "short": default (concise response)
    - "long": only when explicit long-form cues are present
    
    Long-form cues (case-insensitive substring match):
    - "explain in detail"
    - "detailed explanation"
    - "walk me through"
    - "deep dive"
    - "step by step"
    - "full explanation"
    
    Default is concise to reduce latency. Long-form responses require
    explicit user intent to prevent unnecessary verbosity.
    
    Args:
        user_input: Raw user input
        
    Returns:
        str: Either "short" or "long"
    """
    # Convert to lowercase for case-insensitive matching
    user_input_lower = user_input.lower()
    
    # Check for explicit long-form cues
    for cue in LONG_FORM_CUES:
        if cue in user_input_lower:
            return "long"
    
    # Default to short (concise)
    return "short"


# ============================================================================
# Persona Definitions
# ============================================================================

PERSONAS = {
    "neutral": "",
    "dry": """Tone: concise, restrained, slightly wry. Avoid filler, enthusiasm, or speculation.
Do not invent context. When uncertain, say so plainly.""",
}
"""
Persona definitions: name -> prompt fragment.
Each persona injects text into the prompt to adjust tone without changing logic.
Persona text is injected after system rules, before user input.
"""


def get_persona_text(persona_name: str) -> str:
    """
    Retrieve the persona prompt fragment.
    
    Args:
        persona_name: Name of persona (e.g., "neutral", "dry")
        
    Returns:
        str: Persona prompt text (may be empty for neutral)
    """
    return PERSONAS.get(persona_name, "")


def get_verbosity_text(verbosity: str) -> str:
    """
    Retrieve the verbosity prompt fragment.
    
    Args:
        verbosity: One of "short" (concise) or "long" (detailed)
        
    Returns:
        str: Verbosity control prompt text
    """
    verbosity_instructions = {
        "short": "Response length: concise. Avoid unnecessary detail, filler, or elaboration.",
        "long": "Response length: detailed. Provide thorough explanations, step-by-step guidance, and complete examples.",
    }
    return verbosity_instructions.get(verbosity, verbosity_instructions["short"])


def get_cli_formatting_suppression(execution_context: str) -> str:
    """
    CLI formatting suppression: suppress lists/bullets in non-TTY contexts.
    
    When stdin/stdout are not TTY (headless CLI), suppress formatted lists.
    Use plain paragraphs instead. Content rules unchanged.
    
    Args:
        execution_context: "cli" or "gui" from detect_context()
        
    Returns:
        str: Formatting constraint text (empty if GUI context)
    """
    if execution_context == "cli":
        return "Use plain paragraphs. Do not use numbered lists, bullet points, or markdown formatting."
    return ""


def validate_cli_format(response: str, execution_context: str) -> tuple[bool, str]:
    """
    Validate CLI response format: no lists, bullets, or headings.
    
    Post-generation validator (shape only, not content).
    
    Args:
        response: Model response text
        execution_context: "cli" or "gui" from detect_context()
        
    Returns:
        tuple: (is_valid: bool, error_message: str or "")
    """
    if execution_context != "cli":
        return True, ""
    
    lines = response.split("\n")
    
    # Check for forbidden list tokens
    for i, line in enumerate(lines):
        # Numbered lists (1., 2., etc.)
        if line.lstrip() and line.lstrip()[0].isdigit() and len(line.lstrip()) > 1 and line.lstrip()[1] == ".":
            return False, f"Line {i+1}: Numbered list detected ('{line.strip()}')"
        
        # Bullet points (-, *, etc.)
        if line.lstrip().startswith("-") or line.lstrip().startswith("*"):
            return False, f"Line {i+1}: Bullet point detected ('{line.strip()}')"
        
        # Section headers (markdown headers #)
        if line.lstrip().startswith("#"):
            return False, f"Line {i+1}: Section header detected ('{line.strip()}')"
    
    return True, ""


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

REPLAY_FILTERS = {
    "continuation": {"instruction", "correction", "question"},
    "clarification": {"question", "instruction"},
    "session": {"instruction", "correction"},
}
"""
Deterministic replay filtering policy by reason.

Defines which entry types to include when filtering replay context.
Meta entries are excluded by default. Other entries are lowest priority.
Policy is configurable without changing logic.
"""


# ============================================================================
# Phase 4C: Pre-Generation Behavior Selector
# ============================================================================

QUERY_TYPE_PATTERNS = {
    "factual": {
        "patterns": ("what is", "define", "who is", "when was", "where is", "how many", "isn't", "doesn't", "aren't"),
        "priority": 1,
    },
    "exploratory": {
        "patterns": ("tell me about", "explain", "describe", "how does", "why"),
        "priority": 2,
    },
    "corrective": {
        "patterns": ("actually", "no wait", "correction", "wrong", "mistake", "that's not", "instead"),
        "priority": 3,
    },
    "instructional": {
        "patterns": ("how to", "steps to", "walk me through", "guide", "tutorial", "process", "add", "install", "setup", "configure"),
        "priority": 4,
    },
    "speculative": {
        "patterns": ("what if", "suppose", "imagine", "could", "would it", "possible to"),
        "priority": 5,
    },
}
"""
Query type classification patterns.
Priority indicates detection order (higher priority checked first).
"""


def classify_query_type(user_input: str) -> str:
    """
    Classify the query into a behavioral category.
    
    Types:
    - "factual": asking for facts, definitions, specs
    - "exploratory": open-ended questions, seeking understanding
    - "corrective": correcting/updating previous statements
    - "instructional": asking for step-by-step guidance
    - "speculative": hypothetical/future questions
    - "other": fallback
    
    Args:
        user_input: Raw user input
        
    Returns:
        str: Query type classification
    """
    user_input_lower = user_input.lower().strip()
    
    # Sort by priority (highest first)
    sorted_types = sorted(QUERY_TYPE_PATTERNS.items(), key=lambda x: -x[1]["priority"])
    
    for query_type, config in sorted_types:
        for pattern in config["patterns"]:
            if pattern in user_input_lower:
                return query_type
    
    return "other"


def infer_canonical_knowledge(user_input: str) -> bool:
    """
    Infer whether user is asking about canonical/well-specified knowledge.
    
    Signals for canonical knowledge:
    - Manufacturer names (BigTreeTech, LDO, VzBot, Bambu, Creality, Duet, E3D)
    - Product model numbers (SKR 3, LK4pro, RRF, etc.)
    - Technical specifications (specs, datasheet, reference)
    - Established standards (NEMA 17, 24V, PWM, etc.)
    - Well-defined procedures (calibrate, home, tune, etc.)
    
    Signals for non-canonical knowledge:
    - Opinion words (think, believe, probably, maybe, seems)
    - Vague references (that thing, some setup, random config)
    - Future/hypothetical context
    
    This is a stub that infers canonical status until a real knowledge
    database is available.
    
    Args:
        user_input: Raw user input
        
    Returns:
        bool: True if query appears to be about canonical knowledge
    """
    user_input_lower = user_input.lower()
    
    # Canonical knowledge signals
    canonical_signals = (
        "skr 3",
        "bigtreetech",
        "ldo",
        "vzbot",
        "bambu",
        "creality",
        "duet",
        "e3d",
        "nema 17",
        "tmc2209",
        "marlin",
        "klipper",
        "datasheet",
        "spec",
        "specification",
        "24v",
        "12v",
        "heater cartridge",
        "thermistor",
        "stepper",
        "endstop",
        "power supply",
        "calibrate",
        "home",
        "tune",
        "pid",
        "homing",
    )
    
    # Non-canonical signals
    non_canonical_signals = (
        "i think",
        "i believe",
        "probably",
        "maybe",
        "seems like",
        "guess",
        "might be",
        "could be",
        "some random",
        "that thing",
    )
    
    # Check non-canonical first (stronger signal)
    for signal in non_canonical_signals:
        if signal in user_input_lower:
            return False
    
    # Check canonical
    for signal in canonical_signals:
        if signal in user_input_lower:
            return True
    
    # Canonical inference failure: factual queries default to non-canonical (conservative)
    # This forces uncertainty enforcement when facts are demanded but knowledge is unverified
    factual_patterns = ("what ", "what's", "define ", "explain ", "how many", "when was", "where is", "who is")
    if any(user_input_lower.startswith(p) for p in factual_patterns):
        return False  # Non-canonical by default when inference fails on factual query
    
    # Default: uncertain, treat as potentially non-canonical
    return False


def select_behavior_profile(
    query_type: str,
    context_strength: str,
    has_canonical_knowledge: bool,
) -> dict:
    """
    Select behavior profile based on query type, context, and knowledge availability.
    
    Behavior profile determines:
    - verbosity_override: "short", "normal", "long" (None = no override)
    - explanation_depth: "minimal", "standard", "full"
    - correction_style: "factual", "exploratory", "confrontational"
    
    Decision matrix:
    
    Factual + Strong Context + Canonical → SHORT + MINIMAL
    Factual + Weak Context + Canonical → NORMAL + STANDARD
    Factual + Any Context + Non-Canonical → LONG + FULL
    
    Exploratory + Strong Context → NORMAL + MINIMAL (compress, skip primers)
    Exploratory + Weak Context → LONG + STANDARD
    
    Corrective + Any Context → NORMAL + STANDARD (always verify)
    
    Instructional + Any Context → LONG + FULL (always detailed)
    
    Speculative + Any Context → NORMAL + STANDARD
    
    Args:
        query_type: From classify_query_type()
        context_strength: From classify_context_strength() (strong/moderate/weak)
        has_canonical_knowledge: From infer_canonical_knowledge()
        
    Returns:
        dict: Behavior profile with overrides and instructions
    """
    profile = {
        "verbosity_override": None,
        "explanation_depth": "standard",
        "correction_style": "factual",
    }
    
    # ________________________________________________________________________
    # Factual queries
    # ________________________________________________________________________
    if query_type == "factual":
        if has_canonical_knowledge:
            if context_strength == "strong":
                profile["verbosity_override"] = "short"
                profile["explanation_depth"] = "minimal"
            elif context_strength == "moderate":
                profile["verbosity_override"] = "normal"
                profile["explanation_depth"] = "standard"
            else:  # weak
                profile["verbosity_override"] = "normal"
                profile["explanation_depth"] = "standard"
        else:
            # Non-canonical: HARD STOP - refuse speculation
            profile["verbosity_override"] = "long"
            profile["explanation_depth"] = "full"
            profile["force_uncertainty"] = True
            profile["refuse_speculation"] = True
    
    # ________________________________________________________________________
    # Exploratory queries
    # ________________________________________________________________________
    elif query_type == "exploratory":
        if context_strength == "strong":
            # Strong context: can compress, skip primers, front-load conclusions
            profile["verbosity_override"] = "short"
            profile["explanation_depth"] = "minimal"
        elif context_strength == "moderate":
            profile["verbosity_override"] = "normal"
            profile["explanation_depth"] = "standard"
        else:  # weak
            # Weak context: expand to teach mode
            profile["verbosity_override"] = "long"
            profile["explanation_depth"] = "full"
    
    # ________________________________________________________________________
    # Corrective queries (always verify, always standard depth)
    # ________________________________________________________________________
    elif query_type == "corrective":
        profile["verbosity_override"] = "normal"
        profile["explanation_depth"] = "standard"
        profile["correction_style"] = "factual"
    
    # ________________________________________________________________________
    # Instructional queries (always detailed)
    # ________________________________________________________________________
    elif query_type == "instructional":
        profile["verbosity_override"] = "long"
        profile["explanation_depth"] = "full"
    
    # ________________________________________________________________________
    # Speculative queries (neutral depth)
    # ________________________________________________________________________
    elif query_type == "speculative":
        profile["verbosity_override"] = "normal"
        profile["explanation_depth"] = "standard"
    
    # ________________________________________________________________________
    # Other (neutral defaults)
    # ________________________________________________________________________
    else:
        profile["verbosity_override"] = None
        profile["explanation_depth"] = "standard"
    
    return profile


# ============================================================================
# Phase 5B: Familiarity & Trust Layer (Stateful, Earned, Revocable)
# ============================================================================

# Familiarity level state (persists across turns in a session)
# Tracks earned personality privilege
FAMILIARITY_STATE = {
    "level": "neutral",  # neutral, familiar, trusted
    "successful_turns": 0,  # Count of turns without violations
    "violations_count": 0,  # Resets on each violation
}


def update_familiarity(success: bool, violation_type: str | None = None) -> str:
    """
    Update familiarity level based on interaction outcomes.
    
    Promote:
    - neutral → familiar after 3 successful turns
    - familiar → trusted after 5 successful turns
    
    Demote:
    - Any level → neutral on hallucination, uncertainty violation, frame blending
    - trusted → familiar on personality discipline violation
    
    Args:
        success: Whether interaction succeeded (no violations)
        violation_type: Type of violation, if any
        
    Returns:
        str: Current familiarity level
    """
    if violation_type:
        # Immediate demotion on violations
        if violation_type in ("hallucination", "uncertainty_violation", "frame_blending"):
            FAMILIARITY_STATE["level"] = "neutral"
            FAMILIARITY_STATE["successful_turns"] = 0
        elif violation_type == "personality_discipline":
            FAMILIARITY_STATE["level"] = "familiar"
            FAMILIARITY_STATE["successful_turns"] = 0
        FAMILIARITY_STATE["violations_count"] += 1
    else:
        # Increment on success
        FAMILIARITY_STATE["successful_turns"] += 1
        
        # Promote if thresholds met
        if FAMILIARITY_STATE["level"] == "neutral" and FAMILIARITY_STATE["successful_turns"] >= 3:
            FAMILIARITY_STATE["level"] = "familiar"
            FAMILIARITY_STATE["successful_turns"] = 0
        elif FAMILIARITY_STATE["level"] == "familiar" and FAMILIARITY_STATE["successful_turns"] >= 5:
            FAMILIARITY_STATE["level"] = "trusted"
            FAMILIARITY_STATE["successful_turns"] = 0
    
    return FAMILIARITY_STATE["level"]


def get_familiarity_level() -> str:
    """Return current familiarity level: neutral, familiar, or trusted."""
    return FAMILIARITY_STATE["level"]


# ============================================================================
# Phase 5B Extension: Casual Question Observational Humor
# ============================================================================

def is_casual_question(query_text: str) -> bool:
    """
    Detect if question is about casual, everyday, or observational topics.
    
    Casual questions:
    - About people behavior, habits, social dynamics
    - About animals, pets, observable behavior
    - About meetings, conversations, social situations
    - About everyday objects and patterns
    - NOT technical, NOT specialized, NOT expertise-based
    
    Args:
        query_text: User's question
        
    Returns:
        bool: True if casual/observational topic
    """
    query_lower = query_text.lower()
    
    # Specific casual topic patterns (more precise than simple substring match)
    casual_patterns = (
        # Animals/pets
        "dog", "cat", "pet", "animal",
        # People/social behavior and psychology
        "people", "person", "meeting", "conversation", "social",
        "personality", "introvert", "extrovert", "habit",
        "procrastination", "why do people", "why do humans", "why do we",
        # Everyday activities and states
        "coffee", "sleep", "sleep deprivation",
        # Generic patterns (but exclude technical contexts)
        "why do ", "how come ",
    )
    
    # Check if matches casual pattern
    for pattern in casual_patterns:
        if pattern in query_lower:
            # Exclude technical domains (contains technical markers)
            technical_markers = (
                "stepper", "motor", "thermistor", "skr", "klipper",
                "mainboard", "firmware", "code", "program", "algorithm",
                "function", "class", "method", "api", "database",
                "works", "mechanism", "process", "system", "architecture",
            )
            
            # If it's a generic "why do/how come" but also mentions technical term, it's technical
            if pattern in ("why do ", "how come "):
                if any(tech in query_lower for tech in technical_markers):
                    return False  # Technical topic
            
            return True
    
    return False


# ============================================================================
# Phase 5B.2 Patch: Frame Correction & Hallucination Guard
# ============================================================================

def validate_human_first_sentence(response_text: str, is_casual: bool, primary_frame: str) -> tuple[bool, str]:
    """
    PATCH: Human-first sentence enforcement for casual + human frame.
    
    For casual questions with 'human' frame (behavior/motivation), 
    reject academic/technical opening language.
    
    Fails if first sentence contains:
    - Academic nouns: "system", "phenomenon", "aspect", "mechanism", "process"
    - Technical framing: "involves", "consists of", "characterized by"
    
    Forces human-centered opening: "Dogs want...", "People do...", not "The system..."
    
    Args:
        response_text: Model response text
        is_casual: From is_casual_question()
        primary_frame: From select_primary_frame()
        
    Returns:
        tuple: (is_human_first: bool, violation: str or "")
    """
    # Only enforce for casual + human frame
    if not (is_casual and primary_frame == "human"):
        return True, ""
    
    first_sentence_end = response_text.find(".")
    if first_sentence_end <= 0:
        return True, ""
    
    first_sentence = response_text[:first_sentence_end].lower()
    
    # Academic/technical opening markers
    academic_openers = (
        "the system", "the phenomenon", "the aspect", "the mechanism",
        "a system", "a process", "an aspect", "a mechanism",
        "this system", "such mechanisms", "these processes",
        "involves", "consists of", "characterized by", "comprised of",
    )
    
    for opener in academic_openers:
        if opener in first_sentence:
            return False, f"Academic opening in casual human frame: '{opener}'"
    
    return True, ""


def detect_plausible_hallucination(response_text: str, has_canonical_knowledge: bool, primary_frame: str) -> tuple[bool, str]:
    """
    PATCH: Soft hallucination check for "plausible biology" without verification.
    
    If explaining everyday behavior using technical biological claims but 
    WITHOUT strong canonical grounding, downgrade language or flag.
    
    Triggers if:
    - Response claims biological causation ("is because the brain", "due to hormones")
    - has_canonical_knowledge == False
    - primary_frame == "human" (behavioral explanation)
    
    Soft failure: Requires downgrade to plain language ("mostly because", "it's less about X")
    
    Args:
        response_text: Model response text
        has_canonical_knowledge: From infer_canonical_knowledge()
        primary_frame: From select_primary_frame()
        
    Returns:
        tuple: (is_grounded: bool, violation: str or "")
    """
    # Only check behavioral explanations without canonical grounding
    if primary_frame != "human" or has_canonical_knowledge:
        return True, ""
    
    response_lower = response_text.lower()
    
    # Plausible-but-unverified biological claims
    unverified_bio_claims = (
        "is because the brain", "due to the brain", "because of the brain",
        "because of hormones", "due to hormones", "because of dopamine",
        "because of serotonin", "evolutionary reason", "evolutionary trait",
        "is hardwired", "biologically", "neurological", "brain chemistry",
        "releases dopamine", "triggers serotonin", "neural pathway",
    )
    
    has_bio_claim = any(claim in response_lower for claim in unverified_bio_claims)
    
    if has_bio_claim:
        # Check if response uses downgrade language (acceptable without verification)
        downgrade_language = (
            "mostly because", "largely because", "seems to be",
            "it's less about", "rather than", "not so much", "less about"
        )
        has_downgrade = any(phrase in response_lower for phrase in downgrade_language)
        
        if not has_downgrade:
            return False, "Biological claim without canonical grounding or downgrade language"
    
    return True, ""



def should_inject_observational_humor(familiarity_level: str, is_casual: bool) -> bool:
    """
    Determine if observational humor should be suggested.
    
    Rules:
    - Only when familiarity_level == "trusted"
    - Only when topic is casual/everyday
    - Humor is optional but missing obvious opportunity = soft failure
    
    Args:
        familiarity_level: From get_familiarity_level()
        is_casual: From is_casual_question()
        
    Returns:
        bool: True if conditions allow observational humor
    """
    return familiarity_level == "trusted" and is_casual


def build_casual_humor_instruction(query_text: str) -> str | None:
    """
    Create observational humor instruction for casual questions.
    
    Returns observation-based humor guide, not punchlines or sarcasm.
    
    Example queries and expected openers:
    - "Why do dogs always put their head on your lap?"
      → "Dogs aren't subtle about their needs"
    - "Why do meetings always run over?"
      → "Nobody's ever walked out of a meeting thinking 'that was concise'"
    
    Args:
        query_text: User's question
        
    Returns:
        str: Humor instruction, or None if no appropriate observation found
    """
    query_lower = query_text.lower()
    
    # Observation-based openers for common casual topics
    observations = {
        "dog": "Dogs aren't shy about what they want.",
        "cat": "Cats operate on their own schedule.",
        "pet": "Pet behavior follows its own logic.",
        "meeting": "Meetings have a way of expanding.",
        "conversation": "Conversations rarely go where they start.",
        "habit": "Habits are stickier than they seem.",
        "sleep": "Sleep deprivation does things to your brain.",
        "coffee": "Coffee and productivity feel connected until they aren't.",
        "procrastination": "Procrastination is the most punctual thing ever.",
        "why do people": "People's logic isn't always obvious.",
        "why do humans": "Humans are interesting to watch.",
    }
    
    for topic, observation in observations.items():
        if topic in query_lower:
            return (
                f"CASUAL HUMOR (optional): You may open with one observational "
                f"sentence like '{observation}' Then immediately return to "
                f"explanation. The humor is about shared observation, not jokes."
            )
    
    return None


# ============================================================================
# Phase 5A: Judgment Gate (Single-Frame Selection)
# ============================================================================

def select_primary_frame(query_type: str, context_strength: str, is_casual: bool = False) -> str:
    """
    Decide which explanation frame to use when multiple are valid.
    
    Frames available:
    - 'practical': How to do it, tools, steps, mechanics
    - 'structural': How it's organized, processes, relationships
    - 'human': Why people do it, motivations, behavior, consequences
    - 'systems': How parts interact, feedback, effects across system
    
    Selection rules:
    - If casual question (animals, people, habits) → force 'human' frame (behavior/motivation)
    - If why-question + human context → prefer 'human'
    - If why-question + org/process context → prefer 'structural'
    - If how/what + tools/systems → prefer 'practical'
    - Default: 'practical' (not comprehensive)
    
    ⚠️ Returns one frame only. No blending.
    
    Args:
        query_type: From classify_query_type()
        context_strength: "strong", "moderate", or "weak"
        is_casual: From is_casual_question() - casual topics force 'human' frame
        
    Returns:
        str: One of 'practical', 'structural', 'human', 'systems'
    """
    # PATCH: Casual questions (animals, people, habits) → force 'human' frame
    # This ensures "Why don't cats listen" is about agency, not hearing mechanics
    # And "Why do people procrastinate" is about incentives, not neurology
    if is_casual:
        return "human"
    
    # Exploratory queries → choose based on context
    if query_type == "exploratory":
        if context_strength == "strong":
            return "practical"  # Assume user wants practical frame with strong context
        else:
            return "structural"  # Assume systems understanding with weak context
    
    # Instructional queries → always practical
    if query_type == "instructional":
        return "practical"
    
    # Factual queries → practical (just the facts)
    if query_type == "factual":
        return "practical"
    
    # Corrective queries → structural (explain the fix)
    if query_type == "corrective":
        return "structural"
    
    # Speculative queries → systems (how it would interact)
    if query_type == "speculative":
        return "systems"
    
    # Default: practical
    return "practical"


def validate_scope(response_text: str) -> tuple[bool, str]:
    """
    Validate that response stays within single frame.
    
    Soft validator (does not regenerate, only logs).
    
    Fails if response:
    - Introduces multiple perspectives ("another reason is", "from another angle")
    - Hedges into enumeration ("On the other hand", "However")
    - Expands scope beyond initial answer
    
    Args:
        response_text: Model response text
        
    Returns:
        tuple: (is_scoped: bool, drift_signal: str or "")
    """
    response_lower = response_text.lower()
    
    # Multi-perspective markers (scope expansion)
    multi_perspective_markers = (
        "another reason",
        "from another angle",
        "alternatively",
        "on the other hand",
        "conversely",
        "however, from a different perspective",
        "but consider also",
        "additional perspective",
        "also worth noting is",
    )
    
    for marker in multi_perspective_markers:
        if marker in response_lower:
            return False, f"Multi-perspective expansion detected: '{marker}'"
    
    # Scope-broadening markers
    scope_markers = (
        "more broadly",
        "in general",
        "this also applies to",
        "moreover, we should consider",
        "additionally, it's important",
    )
    
    for marker in scope_markers:
        if marker in response_lower:
            return False, f"Scope expansion detected: '{marker}'"
    
    # Essay-ending markers (signals "conclusion" coming)
    conclusion_markers = (
        "in conclusion",
        "in summary",
        "to summarize",
        "ultimately",
        "all things considered",
    )
    
    for marker in conclusion_markers:
        if marker in response_lower:
            return False, f"Essay-conclusion pattern detected: '{marker}'"
    
    return True, ""


def validate_personality_discipline(response_text: str, query_type: str, has_canonical_knowledge: bool, execution_context: str, is_casual: bool = False) -> tuple[bool, str, bool]:
    """
    Post-generation personality discipline check.
    
    Verify that humor/casual tone doesn't replace explanation, undermine authority,
    or weaken correctness.
    
    Hard fails if:
    - Humor appears when saying "I don't know"
    - Sarcasm directed at user
    - Humor in factual canonical answers
    - Humor/casual in CLI command responses
    - Joke substitutes for actual explanation
    
    Soft fails (log only, no demotion) if:
    - Casual question when trusted, but no observational opener used
    
    Args:
        response_text: Model response text
        query_type: From classify_query_type()
        has_canonical_knowledge: From infer_canonical_knowledge()
        execution_context: "cli" or "gui"
        is_casual: True if is_casual_question() returned True
        
    Returns:
        tuple: (is_disciplined: bool, violation: str or "", soft_failure: bool)
    """
    response_lower = response_text.lower()
    soft_failure = False
    
    # NO HUMOR when saying "I don't know" or any uncertainty statement
    uncertainty_phrases = ("i don't know", "i don't have", "not sure", "unsure", "unclear", "uncertain")
    if any(phrase in response_lower for phrase in uncertainty_phrases):
        humor_markers = ("lol", "haha", "😄", ";)", "just kidding", "just messing", "btw", "fyi")
        for marker in humor_markers:
            if marker in response_lower:
                return False, "Humor detected on uncertainty statement", False
    
    # NO HUMOR in factual canonical answers
    if query_type == "factual" and has_canonical_knowledge:
        joke_indicators = ("apparently", "supposedly", "allegedly", "so-called", "funny thing is")
        for indicator in joke_indicators:
            if indicator in response_lower:
                return False, f"Humor/skepticism in factual canonical answer: '{indicator}'", False
    
    # NO SARCASM INDICATORS (applies to all contexts)
    # These are sarcastic/skeptical markers that weaken credibility
    sarcasm_indicators = ("so-called", "apparently", "supposedly", "allegedly")
    for indicator in sarcasm_indicators:
        if indicator in response_lower:
            # Already caught above for factual canonical, so this catches casual/other contexts
            if not (query_type == "factual" and has_canonical_knowledge):
                return False, f"Sarcasm/skepticism detected: '{indicator}'", False
    
    # NO HUMOR in CLI command responses
    if execution_context == "cli":
        cli_joke_markers = ("btw", "psst", "fyi", "heads up")
        for marker in cli_joke_markers:
            if marker in response_lower:
                return False, f"Casual tone in CLI command: '{marker}'", False
    
    # NO SARCASM aimed at user (check for sarcastic structures)
    # Only flag if sarcasm is directed AT user ("of course you", "sure you can", etc.)
    # Don't flag neutral observational use of "obviously" or "naturally"
    user_directed_sarcasm = ("oh you want", "sure you can", "of course you", "obviously you")
    for pattern in user_directed_sarcasm:
        if pattern in response_lower:
            return False, f"Sarcasm directed at user: '{pattern}'", False
    
    # Check if joke replaces explanation (standalone punchline-like structures)
    if response_text.strip().endswith(("😄", "lol", "haha", "👍", "🤔")):
        return False, "Emoji used as explanation", False
    
    # SOFT FAILURE: Casual question but no observational opener when opportunity is clear
    # Only flag pure definition/cause openers WITHOUT opinion or judgment
    # Examples of soft failure (pure definition/cause):
    # - "Dogs are animals..." (definition)
    # - "A dog puts its head..." (straight cause, no observation hook)
    # - "The reason people...is..." (cause explanation)
    # Examples of NO soft failure (has opinion/observation):
    # - "Dogs are subtle communicators..." (opinion about dogs)
    # - "Meetings have a way..." (observation)
    # - "Honestly, cats are..." (personality)
    if is_casual:
        first_sentence_end = response_text.find(".")
        if first_sentence_end > 0:
            first_sentence = response_text[:first_sentence_end].lower().strip()
            
            # Pattern 1: Simple entity definition ("Dogs are X", "A dog is X")
            simple_defs = ("dogs are", "cats are", "people are", "meetings are", "conversations are", "a dog ", "a cat ", "a person ")
            for def_pattern in simple_defs:
                if first_sentence.startswith(def_pattern):
                    # Check what comes after
                    after = first_sentence[len(def_pattern):].strip()
                    # If it's an opinion word, it's observational
                    opinion_words = ("subtle", "interesting", "remarkable", "surprising", "curious", "strange")
                    if not any(word in after[:30] for word in opinion_words):
                        # No opinion -> pure definition or action without observation
                        # For "a dog puts..." without observation, this is soft fail
                        soft_failure = True
                    break
            
            # Pattern 2: Explanation by cause ("The reason X..." typically lacks observation)
            if first_sentence.startswith("the reason") or first_sentence.startswith("this is because"):
                soft_failure = True
    
    return True, "", soft_failure


def build_behavior_instruction(behavior_profile: dict, execution_context: str = "gui", has_canonical_knowledge: bool = True, primary_frame: str = "practical", familiarity_level: str = "neutral", query_text: str = "", is_casual_q: bool = False) -> str:
    """
    Build the behavior instruction to inject into the prompt.
    
    Translates behavior profile into actionable prompt guidance with Phase 5A judgment gating,
    Phase 5B conditional personality permission, and Phase 5B.2 casual observational humor.
    
    Instructions are ordered by priority (most constraining first):
    1. Confidence-first bias (Phase 5C) - if trusted + casual, sets first-sentence template
    2. CRITICAL hard guards (single-frame, speculation refusal, hallucination ban)
    3. Permission layer (personality permission when trusted)
    4. Optional guidance (casual humor)
    5. Standard behavior instructions
    
    Does NOT narrate reasoning or internal logic.
    Does NOT surface tier labels.
    Does NOT include meta-commentary.
    
    Args:
        behavior_profile: From select_behavior_profile()
        execution_context: "cli" or "gui" from detect_context()
        has_canonical_knowledge: From infer_canonical_knowledge()
        primary_frame: From select_primary_frame() ('practical', 'structural', 'human', 'systems')
        familiarity_level: From get_familiarity_level() ("neutral", "familiar", "trusted")
        query_text: User's original question (for casual topic detection)
        is_casual_q: From is_casual_question(query_text)
        
    Returns:
        str: Instruction text to inject into prompt
    """
    priority_instructions = []
    
    # ________________________________________________________________________
    # PRIORITY 1: CONFIDENCE-FIRST BIAS (Phase 5C) - when trusted AND casual
    # This comes FIRST because it sets the generation frame before anything else
    # ________________________________________________________________________
    if familiarity_level == "trusted" and is_casual_q:
        priority_instructions.append(
            "CRITICAL - FIRST SENTENCE MUST BE ONE OF:\n"
            "\"People do this because …\"\n"
            "\"What's really happening is …\"\n"
            "\"This happens because …\"\n\n"
            "YOU MUST NOT START WITH:\n"
            "\"The phenomenon\", \"In humans\", \"This behavior is often\", \"This can be attributed\", \"Research suggests\"\n\n"
            "After your opening claim: explain just enough. No numbered lists. No lecture mode. Stay conversational."
        )
    
    # ________________________________________________________________________
    # PRIORITY 2: CRITICAL HARD GUARDS (honesty, scope, hallucination prevention)
    # ________________________________________________________________________
    
    # CRITICAL: Refusal to speculate on factual non-canonical
    if behavior_profile.get("refuse_speculation", False):
        priority_instructions.append(
            "CRITICAL: You do not have authoritative information for this factual question. "
            "Respond with 'I don't have verified information on this' and STOP. "
            "Do not guess. Do not speculate. Do not cite sources. Do not add explanations."
        )
    
    # CRITICAL: Source hallucination ban
    if not has_canonical_knowledge:
        priority_instructions.append(
            "CRITICAL: You do not have access to documentation, manuals, or online sources. "
            "Never reference 'verified sources', 'documentation', 'tutorials', or similar. "
            "If information is uncertain, explicitly say 'I don't know'."
        )
    
    # CRITICAL: Single-frame enforcement (Phase 5A judgment gate)
    priority_instructions.append(
        "CRITICAL: Choose one explanation frame and answer from it only. "
        "Do not enumerate alternatives. Do not broaden scope. "
        f"Use the '{primary_frame}' frame: answer this question from that perspective only."
    )
    
    # CRITICAL: CLI explicit negative formatting constraint
    if execution_context == "cli":
        priority_instructions.append(
            "CRITICAL FORMAT CONSTRAINT:\n"
            "You MUST NOT use the following in your response:\n"
            "- numbered lists (e.g. \"1.\", \"2.\")\n"
            "- bullet points (\"-\", \"*\")\n"
            "- section headers or labels\n"
            "- examples blocks\n"
            "- mitigation or advice sections\n"
            "If you violate this format, the response is invalid.\n"
            "Use continuous paragraph prose only."
        )
    
    # ________________________________________________________________________
    # PRIORITY 3: PERMISSION LAYER (personality permission when trusted)
    # ________________________________________________________________________
    if familiarity_level == "trusted":
        priority_instructions.append(
            "PERMISSION: You may use light humor, mild sass, or casual phrasing if it improves clarity or trust. "
            "Never obscure facts. Never override uncertainty or scope constraints. "
            "No jokes when saying 'I don't know'. No sarcasm aimed at the user. No humor in factual canonical answers."
        )
    
    # ________________________________________________________________________
    # PRIORITY 4: OPTIONAL GUIDANCE (casual humor)
    # ________________________________________________________________________
    if familiarity_level == "trusted" and is_casual_q:
        casual_humor_instruction = build_casual_humor_instruction(query_text)
        if casual_humor_instruction:
            priority_instructions.append(casual_humor_instruction)
    
    # ________________________________________________________________________
    # PRIORITY 5: STANDARD BEHAVIOR INSTRUCTIONS
    # ________________________________________________________________________
    
    # Explanation depth instruction
    if behavior_profile["explanation_depth"] == "minimal":
        priority_instructions.append("Provide only the essential facts. Omit elaboration, context, and caveats.")
    elif behavior_profile["explanation_depth"] == "full":
        priority_instructions.append("Provide comprehensive explanation. Include context, examples, and caveats.")
    else:  # standard
        priority_instructions.append("Provide clear explanation. Include necessary context but avoid excessive detail.")
    
    # Reasoning instruction (NEVER force it)
    priority_instructions.append("Explain conclusions only when necessary for correctness or followability.")
    
    # CLI tone tightening
    if execution_context == "cli":
        priority_instructions.append("Answer like a competent peer. No summaries. No conclusions. Just the answer.")
    
    return "\n".join(priority_instructions)


# ============================================================================
# Logging Infrastructure
# ============================================================================

def _append_daily_log(
    *,
    timestamp_iso: str,
    session_id: str,
    user_prompt: str,
    model_response: str,
    active_mode: str | None,
    replay_n: int | None,
    replay_session: bool,
    persona: str = "neutral",
    verbosity: str = "short",
    replay_policy: dict | None = None,
    behavior_profile: dict | None = None,
    honesty_enforcement: dict | None = None,
) -> None:
    """
    Append a single interaction record to the daily log file.
    
    Each record captures:
    - ISO timestamp of the interaction
    - Session ID (shared by all turns in this run)
    - User input and model response
    - Active conversation mode (if any)
    - Replay metadata (whether and how replay was used)
    - Persona and verbosity settings for this turn
    - Replay policy diagnostics (entries used, chars, trimming, reason)
    - Behavior profile (query type, verbosity override, explanation depth)
    - Honesty enforcement (uncertainty flags, violations, drift signals)
    
    Log files are organized by date: YYYY-MM-DD.log
    Corrupt lines are silently skipped during reads.
    
    Args:
        timestamp_iso: ISO 8601 timestamp string (YYYY-MM-DDTHH:MM:SS)
        session_id: UUID of current session
        user_prompt: Raw user input (no modifications)
        model_response: Model output from Ollama
        active_mode: Name of conversation mode or None
        replay_n: If last:N was used, the value N; else None
        replay_session: True if --replay session was used; False otherwise
        persona: Persona name used for this interaction (default: "neutral")
        verbosity: Response length control, "short" or "long" (default: "short")
        replay_policy: Dict with replay diagnostics (entries_used, chars_used, trimmed, reason)
        behavior_profile: Dict with behavior decisions (query_type, verbosity_override, etc.)
        honesty_enforcement: Dict with honesty violation logs
    """
    log_dir = _get_log_dir()
    os.makedirs(log_dir, exist_ok=True)

    # File per day: YYYY-MM-DD.log
    file_name = f"{timestamp_iso[:10]}.log"
    file_path = os.path.join(log_dir, file_name)

    # Build the record
    record = {
        "timestamp": timestamp_iso,
        "session_id": session_id,
        "active_mode": active_mode,
        "persona": persona,
        "verbosity": verbosity,
        "replay": {
            "enabled": replay_n is not None or replay_session,
            "count": replay_n,
            "session": replay_session,
        },
        "user_prompt": user_prompt,
        "model_response": model_response,
    }
    
    # Add replay policy diagnostics if available
    if replay_policy:
        record["replay_policy"] = replay_policy
    
    # Add behavior profile if available
    if behavior_profile:
        record["behavior_profile"] = behavior_profile
    
    # Add honesty enforcement if available
    if honesty_enforcement:
        record["honesty_enforcement"] = honesty_enforcement

    # Append as newline-delimited JSON
    with open(file_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ============================================================================
# Replay Helpers
# ============================================================================

def get_last_n_entries(n: int) -> list[dict]:
    """
    Retrieve the last N interaction records from logs (chronological order).
    
    Scans log files in reverse chronological order (newest first).
    Stops as soon as N entries are found.
    Skips corrupt JSON lines silently.
    
    Args:
        n: Number of entries to retrieve
        
    Returns:
        list[dict]: List of log records, oldest to newest.
                   Empty list if no logs exist or n=0.
    """
    log_dir = _get_log_dir()
    if not os.path.exists(log_dir):
        return []

    log_files = sorted(Path(log_dir).glob("*.log"))
    if not log_files:
        return []

    entries: list[dict] = []

    # Walk logs backward (newest first)
    for log_file in reversed(log_files):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Read lines backward within the file
        for line in reversed(lines):
            try:
                record = json.loads(line)
                entries.append(record)
                if len(entries) >= n:
                    return list(reversed(entries))  # Return oldest to newest
            except json.JSONDecodeError:
                continue

    return list(reversed(entries))


def get_session_entries(session_id: str) -> list[dict]:
    """
    Retrieve all interaction records from a specific session.
    
    Performs a linear scan across all log files.
    Returns entries in chronological order (oldest first).
    Skips corrupt JSON lines silently.
    
    Args:
        session_id: UUID to filter by
        
    Returns:
        list[dict]: List of all log records matching the session_id,
                   or empty list if no matches found.
    """
    log_dir = _get_log_dir()
    if not os.path.exists(log_dir):
        return []

    entries: list[dict] = []

    # Linear scan across all files
    for log_file in sorted(Path(log_dir).glob("*.log")):
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("session_id") == session_id:
                        entries.append(record)
                except json.JSONDecodeError:
                    continue

    return entries


def classify_entry_type(user_prompt: str, model_response: str) -> str:
    """
    Classify entry type for intelligent replay filtering.
    
    Rules (deterministic, no ML):
    - "question": user input ends with ? or contains question words
    - "instruction": starts with verb (do, list, create, explain, etc.)
    - "correction": contains correction keywords (actually, no wait, correction, etc.)
    - "meta": asks about previous conversation (what did, repeat, summary, etc.)
    - "other": fallback
    
    Args:
        user_prompt: The user's input
        model_response: The model's response (for context)
        
    Returns:
        str: One of: "question", "instruction", "correction", "meta", "other"
    """
    prompt_lower = user_prompt.lower().strip()
    
    # Meta: asks about conversation history
    meta_patterns = ("what did", "repeat", "summarize", "recap", "previous", "before", "earlier", "said")
    if any(pattern in prompt_lower for pattern in meta_patterns):
        return "meta"
    
    # Question: ends with ? or has question words
    if prompt_lower.endswith("?") or any(word in prompt_lower for word in ("what", "why", "how", "when", "where", "who")):
        return "question"
    
    # Correction: correction keywords
    correction_patterns = ("actually", "no wait", "correction", "mistake", "wrong", "not", "instead")
    if any(pattern in prompt_lower for pattern in correction_patterns):
        return "correction"
    
    # Instruction: starts with imperative verb
    instruction_verbs = ("do", "list", "create", "write", "explain", "show", "tell", "give", "make", "build", "find", "analyze", "compare")
    first_word = prompt_lower.split()[0] if prompt_lower.split() else ""
    if first_word in instruction_verbs:
        return "instruction"
    
    return "other"


def classify_context_strength(replay_policy: dict | None, entry_types: list[str] | None) -> str:
    """
    Classify context confidence level based on replay diagnostics.
    
    Deterministic rules (no ML, no fuzzy logic):
    
    STRONG:
      - entries_used >= 2
      - trimmed == False
      - replay_reason in {session, continuation}
      - at least one entry type is instruction or correction
    
    MODERATE:
      - entries_used >= 1
      - trimmed may be True
      - replay_reason in {continuation, clarification}
      - mostly question or instruction
    
    WEAK:
      - entries_used == 0
      - OR (replay_reason == clarification AND trimmed == True)
      - OR only meta/other entries survived replay
    
    Args:
        replay_policy: Dict with entries_used, chars_used, trimmed, reason
        entry_types: List of entry type classifications (question, instruction, etc.)
        
    Returns:
        str: One of: "strong", "moderate", "weak"
    """
    if not replay_policy:
        return "weak"
    
    entries_used = replay_policy.get("entries_used", 0)
    trimmed = replay_policy.get("trimmed", False)
    reason = replay_policy.get("reason", "continuation")
    entry_types = entry_types or []
    
    # WEAK: no context or only meta/other
    if entries_used == 0:
        return "weak"
    
    # Check if only meta/other entries survived
    non_meta_other = [t for t in entry_types if t not in ("meta", "other")]
    if entries_used > 0 and not non_meta_other:
        return "weak"
    
    # WEAK: clarification with trimming
    if reason == "clarification" and trimmed:
        return "weak"
    
    # STRONG: rich context, no trimming, good reason, has instruction/correction
    has_instruction_or_correction = any(t in ("instruction", "correction") for t in entry_types)
    if entries_used >= 2 and not trimmed and reason in ("session", "continuation") and has_instruction_or_correction:
        return "strong"
    
    # MODERATE: fallback for any other valid replay
    if entries_used >= 1 and reason in ("continuation", "clarification"):
        return "moderate"
    
    # Final fallback: any replay is better than nothing
    if entries_used >= 1:
        return "moderate"
    
    return "weak"


def get_confidence_instruction(context_strength: str) -> str:
    """
    Get the confidence instruction based on context strength.
    
    Args:
        context_strength: One of: strong, moderate, weak
        
    Returns:
        str: Confidence instruction to inject into prompt
    """
    instructions = {
        "strong": "You have sufficient prior context. Answer directly and confidently.",
        "moderate": "Some prior context exists. Answer carefully and avoid assumptions.",
        "weak": "Prior context may be insufficient. If uncertain, say so plainly and do not guess.",
    }
    return instructions.get(context_strength, instructions["weak"])


def apply_replay_budget(entries: list[dict], max_chars: int = 5500) -> tuple[list[dict], dict]:
    """
    Apply replay budget to entries, trimming from oldest first.
    Always preserves the most recent exchange (latest user+assistant).
    
    Args:
        entries: List of log records (oldest to newest)
        max_chars: Maximum characters allowed for replay context
        
    Returns:
        tuple: (trimmed_entries, stats_dict) where stats_dict contains:
          - entries_used: Number of entries included
          - chars_used: Total characters used
          - trimmed: Boolean indicating if trimming occurred
    """
    if not entries:
        return [], {"entries_used": 0, "chars_used": 0, "trimmed": False}
    
    # Always keep the most recent exchange (last user + last assistant)
    # which means last 2 entries minimum
    min_keep = min(2, len(entries))
    
    total_chars = 0
    selected_entries = []
    trimmed = False
    
    # Walk backward from oldest to newest, keeping only what fits
    for i, entry in enumerate(entries):
        user_prompt = entry.get("user_prompt", "")
        model_response = entry.get("model_response", "")
        entry_chars = len(user_prompt) + len(model_response) + 10  # +10 for formatting
        
        # If adding this would exceed budget AND we have minimum entries kept
        if total_chars + entry_chars > max_chars and len(entries) - i >= min_keep:
            trimmed = True
            continue
        
        selected_entries.insert(0, entry)  # Insert at front to maintain order
        total_chars += entry_chars
    
    stats = {
        "entries_used": len(selected_entries),
        "chars_used": total_chars,
        "trimmed": trimmed
    }
    
    return selected_entries, stats


def filter_replay_entries(entries: list[dict], replay_reason: str, entry_types: list[str]) -> tuple[list[dict], dict]:
    """
    Filter replay entries by type based on replay reason.
    Always preserves the most recent exchange (last user+assistant).
    
    Filtering policy (REPLAY_FILTERS):
    - continuation: instruction, correction, question
    - clarification: question, instruction
    - session: instruction, correction
    - meta is excluded by default
    - other is lowest priority
    
    Args:
        entries: List of log records (oldest to newest)
        replay_reason: One of: session, clarification, continuation
        entry_types: List of entry type strings (parallel to entries)
        
    Returns:
        tuple: (filtered_entries, filter_stats) where filter_stats contains:
          - entries_available: Total entries before filtering
          - entries_filtered: Number of entries removed by type filter
          - filtered_types: List of types that were excluded
    """
    if not entries or not entry_types:
        return entries, {"entries_available": 0, "entries_filtered": 0, "filtered_types": []}
    
    entries_available = len(entries)
    allowed_types = REPLAY_FILTERS.get(replay_reason, set())
    filtered_types = set()
    
    # Build list of (index, entry, type) to identify most recent
    indexed = list(enumerate(zip(entries, entry_types)))
    
    # Always keep last exchange (last 2 entries minimum: user + assistant)
    # Find the last 2 entries regardless of type
    min_keep_indices = set()
    if len(indexed) >= 1:
        min_keep_indices.add(len(indexed) - 1)  # Last entry
    if len(indexed) >= 2:
        min_keep_indices.add(len(indexed) - 2)  # Second to last
    
    filtered_entries = []
    for i, (entry, entry_type) in indexed:
        # Always keep the most recent exchange
        if i in min_keep_indices:
            filtered_entries.append(entry)
        # Keep if type matches policy
        elif entry_type in allowed_types:
            filtered_entries.append(entry)
        # Track filtered types
        else:
            filtered_types.add(entry_type)
    
    filter_stats = {
        "entries_available": entries_available,
        "entries_filtered": entries_available - len(filtered_entries),
        "filtered_types": sorted(list(filtered_types)),
    }
    
    return filtered_entries, filter_stats


# ============================================================================
# Context Detection
# ============================================================================

def detect_context() -> str:
    """
    Detect execution context: CLI vs GUI.
    
    CLI context (headless): running from command line, pipe, script
    GUI context: running in IDE, editor, interactive shell
    
    Returns:
        str: "cli" or "gui"
    """
    # Check for headless indicators
    import platform
    import subprocess
    
    # If stderr is not a TTY, we're likely headless (piped output, script execution)
    if not sys.stderr.isatty():
        return "cli"
    
    # If running in CI/CD or with NO_INTERACTIVE flags
    if os.environ.get("CI") or os.environ.get("OLLAMA_NO_INTERACTIVE"):
        return "cli"
    
    # Default to GUI (interactive)
    return "gui"

# ============================================================================
# ============================================================================
# Main Execution with Memory Integration
# ============================================================================

def detect_recall_query(user_input: str) -> tuple[bool, int | None]:
    """
    Detect if user is asking for a retrieval/recall operation.
    
    Returns: (is_recall_query, count_requested)
    
    Detects patterns like:
    - "what did we talk about"
    - "last 3 things we discussed"
    - "summarize our conversation"
    - "what did you say about"
    - "earlier you mentioned"
    
    Returns:
        (True, N) if recall query detected with count
        (True, None) if recall query but no count specified
        (False, None) if regular conversation query
    """
    ui = user_input.lower().strip()
    
    # Meta-query trigger phrases
    recall_triggers = [
        "what did we talk about",
        "what did we discuss",
        "what have we talked about",
        "what did you say",
        "earlier you",
        "you said",
        "summarize our conversation",
        "list the last",
        "last few things",
        "the last",
        "the previous",
        "recap",
        "remind me what",
        "what topics",
        "things we discussed",
        "our conversation so far"
    ]
    
    is_recall = any(trigger in ui for trigger in recall_triggers)
    
    if not is_recall:
        return False, None
    
    # Try to extract count from "last N things" pattern
    count = None
    import re
    match = re.search(r'last\s+(\d+)\s+(things|topics|items|subjects|conversations|discussions|ideas)', ui)
    if match:
        count = int(match.group(1))
    else:
        # Check for "last X" where X is a word number
        word_numbers = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        for word, num in word_numbers.items():
            if f"last {word}" in ui:
                count = num
                break
    
    return True, count


def format_recall_response(memory: list, count: int | None = None, prefs: dict | None = None) -> str:
    """
    Format memory as deterministic recall output (no narrative synthesis).
    
    Returns a simple, factual list of recent topics/queries.
    
    DESIGN BOUNDARY (non-negotiable):
    ================================
    These are the ONLY two acceptable output formats:
    
    1. NEUTRAL (default):
       Recent topics:
       1. Topic one
       2. Topic two
    
    2. CASUAL (with tone="casual" preference):
       Here's what we covered recently:
       1. Topic one
       2. Topic two
    
    FORBIDDEN: summaries, adjectives, synthesis, narrative preamble.
    Only ever list topics. Never interpret or elaborate.
    
    Args:
        memory: List of memory entries from load_memory()
        count: How many items to return (default: all available)
        prefs: User preferences dict (for tone, optional)
    
    Returns:
        Formatted string with recent topics, or error message if no memory
    """
    if not memory:
        return "I don't have any prior conversation items stored."
    
    # Determine how many to show
    if count is None:
        count = len(memory)
    count = min(count, len(memory))  # Cap at available memory
    
    # Get the most recent N items (from end of list backwards)
    recent = memory[-count:][::-1]  # Reverse to show most recent first
    
    # Extract topics/queries
    topics = []
    for entry in recent:
        user_q = entry.get("user_input", "").strip()
        if user_q:
            topics.append(user_q)
    
    if not topics:
        return "I don't have conversation data to retrieve."
    
    # Format as simple list (no narrative)
    if len(topics) == 1:
        output = f"Recent topic:\n{topics[0]}"
    else:
        output = "Recent topics:\n"
        for i, topic in enumerate(topics, 1):
            output += f"{i}. {topic}\n"
    
    # Apply preference tone lightly (clean confidence, minimal prose)
    if prefs and prefs.get("tone") == "casual":
        output = "Here's what we covered:\n\n" + output
    elif prefs and prefs.get("tone") == "formal":
        output = "The following topics were discussed:\n\n" + output
    
    return output.strip()


def validate_voice_compliance(response_text: str) -> str:
    """
    Safety net for voice drift. Think of this like traction control:
    you don't want it screaming all the time, but you're glad it's there
    when the road gets slick.
    
    This is NOT a style cop. It's a drift alarm.
    
    When you notice Argo starting to drift:
    - Getting too TED Talk-y
    - Adding fake profundity
    - Starting five metaphors instead of one
    - Sounding like a presentation instead of a conversation
    
    Then you can tighten constraints here. But right now?
    Just pass through. Trust your taste.
    
    Returns:
        Response as-is (you're the style arbiter)
    """
    return response_text.strip() if response_text else ""


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
    if not WHISPER_AVAILABLE:
        print("⚠ Whisper not installed. Run: pip install openai-whisper", file=sys.stderr)
        return False, "", None
    
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


def run_argo(
    user_input: str,
    *,
    active_mode: str | None = None,
    replay_n: int | None = None,
    replay_session: bool = False,
    strict_mode: bool = True,
    persona: str = "neutral",
    verbosity: str = "short",
    replay_reason: str = "continuation"
) -> None:
    """
    Public entry point for Argo execution.
    
    Wraps _run_argo_internal with memory and preference integration:
    1. Loads and updates user preferences
    2. Retrieves relevant past interactions
    3. Injects memory context into the prompt
    4. Injects preference context into the prompt
    5. Executes the core logic
    6. Stores the new interaction to memory
    
    Args:
        user_input: User's raw message
        active_mode: Conversation mode name or None
        replay_n: Last N turns to replay or None
        replay_session: True to replay current session
        strict_mode: If True, reject low-intent input
        persona: Tone adjustment ("neutral", etc.)
        verbosity: Response length control ("short" or "long")
        replay_reason: Why replay was requested
    """
    # Step 1: Load, update, and save user preferences
    prefs = load_prefs()
    prefs = update_prefs(user_input, prefs)
    save_prefs(prefs)
    
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
        # IMPORTANT: Do NOT store recall queries to memory
        # Recall queries are meta-operations, not conversational content
        # Storing them would pollute memory with bookkeeping instead of conversation
        return
    
    # GENERATION MODE: Regular conversation
    # Step 3: Find relevant past interactions
    relevant_memory = find_relevant_memory(user_input, top_n=2)
    
    # Step 4: Build memory context to inject
    memory_context = ""
    if relevant_memory:
        memory_lines = []
        for item in relevant_memory:
            memory_lines.append(f"Past: {item['user_input']}")
            memory_lines.append(f"Response: {item['model_response']}")
        memory_context = "From your history:\n" + "\n".join(memory_lines) + "\n\n"
    
    # Step 5: Build preference context to inject
    pref_block = build_pref_block(prefs)
    
    # Step 6: Compose user input with preference + memory prefixes
    composed_input = pref_block + memory_context + user_input
    
    # Step 7: Execute core logic with composed input
    _run_argo_internal(
        composed_input,
        active_mode=active_mode,
        replay_n=replay_n,
        replay_session=replay_session,
        strict_mode=strict_mode,
        persona=persona,
        verbosity=verbosity,
        replay_reason=replay_reason
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
    replay_reason: str = "continuation"
) -> None:
    """
    Execute a single interaction with the Jarvis model.
    
    Flow:
    1. Classify input intent (gating check)
    2. Classify input verbosity (response length preference)
    3. Handle rejected input or route commands
    4. Optional replay: prepend previous turns to context (not sticky)
    5. Optional mode: inject mode enforcement rules
    6. Optional persona: inject tone adjustment (presentation only)
    7. Optional verbosity: inject response length control (presentation only)
    8. Send prompt to Ollama's "jarvis" model
    9. Log the interaction (user input, response, metadata)
    10. Print response to stdout
    
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
    
    replay_block = ""
    replay_policy = None
    context_strength = "weak"
    entry_types = []

    if replay_session:
        entries = get_session_entries(SESSION_ID)
    elif replay_n:
        entries = get_last_n_entries(replay_n)
    else:
        entries = []

    # Process replay entries: classify, filter, then budget
    if entries:
        # Step 1: Classify entry types
        entry_types = [classify_entry_type(e.get("user_prompt", ""), e.get("model_response", "")) for e in entries]
        
        # Step 2: Filter entries by type based on replay reason (BEFORE budget)
        entries, filter_stats = filter_replay_entries(entries, replay_reason, entry_types)
        entry_types = [classify_entry_type(e.get("user_prompt", ""), e.get("model_response", "")) for e in entries]
        
        # Step 3: Apply replay budget to filtered entries
        entries, replay_stats = apply_replay_budget(entries, max_chars=5500)
        
        # Combine stats: replay_policy includes both filter and budget information
        replay_policy = {
            **filter_stats,
            **replay_stats,
            "reason": replay_reason
        }
        
        # Step 4: Determine context strength based on final replay diagnostics
        context_strength = classify_context_strength(replay_policy, entry_types)
        replay_policy["context_strength"] = context_strength
        
        # Format previous turns for context injection
        replay_lines = []
        for e in entries:
            replay_lines.append(f"User: {e['user_prompt']}")
            replay_lines.append(f"Assistant: {e['model_response']}")
        replay_block = "\n".join(replay_lines) + "\n\n"
    
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
    
    behavior_instruction = build_behavior_instruction(behavior_profile, execution_context, has_canonical_knowledge, primary_frame, familiarity_level, user_input, is_casual_q)
    
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
    # Step 3: Call Ollama (with streaming output)
    # ________________________________________________________________________
    
    # Set up environment
    env = os.environ.copy()
    env["OLLAMA_NO_INTERACTIVE"] = "1"

    # Validate Ollama connection before proceeding
    url = "http://localhost:11434/api/generate"
    try:
        # Quick connectivity check
        response = requests.head("http://localhost:11434/api/tags", timeout=2)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("Error: Ollama server is not running.", file=sys.stderr)
        print("Start Ollama with: ollama serve", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("Error: Ollama server is not responding.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error connecting to Ollama: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate model existence
    try:
        tags_response = requests.get("http://localhost:11434/api/tags", timeout=2)
        tags_response.raise_for_status()
        models = tags_response.json().get("models", [])
        model_names = [m.get("name") for m in models]
        
        # Check if 'argo' or 'argo:latest' exists
        argo_exists = any(name.startswith("argo") for name in model_names)
        
        if not argo_exists:
            print("Error: Model 'argo' not found.", file=sys.stderr)
            print(f"Available models: {', '.join(model_names) if model_names else 'none'}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error validating model: {e}", file=sys.stderr)
        sys.exit(1)

    # Make the actual generation request
    payload = {
        "model": "argo",
        "prompt": full_prompt.decode("utf-8"),
        "stream": True
    }

    response = requests.post(url, json=payload, stream=True)
    response.raise_for_status()

    output_lines = []
    MAX_CHARACTERS = 3000
    char_printed = 0
    output_cutoff = False
    cutoff_printed = False
    
    # Token buffer to reduce syscalls
    token_buffer = []
    BUFFER_SIZE = 10

    for line in response.iter_lines(decode_unicode=True):
        if line:
            try:
                data = json.loads(line)
                token = data.get("response", "")
                output_lines.append(token)

                if not output_cutoff:
                    chars_this_line = len(token)
                    if char_printed + chars_this_line > MAX_CHARACTERS:
                        # Flush any pending tokens before cutoff message
                        if token_buffer:
                            print("".join(token_buffer), end="", flush=True)
                            token_buffer.clear()
                        
                        output_cutoff = True
                        cutoff_msg = "\n— Output paused to keep things readable. Say \"continue\" to go deeper."
                        print(cutoff_msg, flush=True)
                    else:
                        char_printed += chars_this_line
                        token_buffer.append(token)
                        
                        # Flush buffer when it reaches size threshold
                        if len(token_buffer) >= BUFFER_SIZE:
                            print("".join(token_buffer), end="", flush=True)
                            token_buffer.clear()
            except json.JSONDecodeError:
                continue
    
    # Final flush of any remaining buffered tokens
    if token_buffer:
        print("".join(token_buffer), flush=True)
    
    # Reconstruct full output for logging (preserves everything, even if truncated in terminal)
    output = "".join(output_lines).strip()
    
    # VOICE COMPLIANCE: Enforce example constraints (brevity, tone, no hedge)
    output = validate_voice_compliance(output)

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
        print("\n📌 Interactive Mode (Type 'exit' or 'quit' to leave)\n", file=sys.stderr)
        try:
            while True:
                try:
                    user_input = input("argo > ").strip()
                    
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
                        persona=persona_value
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
