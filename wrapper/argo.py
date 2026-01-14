"""
ARGO - Ollama-based conversational AI wrapper with session management and replay.

This module provides:
- Direct interface to Ollama's Jarvis model via subprocess
- Persistent JSON logging of all interactions
- Session tracking with unique IDs (ephemeral or named)
- Selective replay functionality (last:N turns or current session)
- Conversation mode enforcement

Session Structure:
  Ephemeral: Each run gets a unique SESSION_ID (default)
  Named: Multiple runs can share a SESSION_ID using --session <name> flag
  
  Named sessions persist in .sessions.json until manually deleted.
  Replay can be triggered explicitly with --replay flags.
  No automatic memory. No persistence between runs unless --session is used.
"""

import sys
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
import requests

# ============================================================================
# UTF-8 Encoding Configuration (Windows terminal safety)
# ============================================================================

# Force UTF-8 encoding for stdout/stderr on all platforms (especially Windows)
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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


# ============================================================================
# Main Execution
# ============================================================================

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
    # ________________________________________________________________________
    
    replay_block = ""
    replay_policy = None

    if replay_session:
        entries = get_session_entries(SESSION_ID)
    elif replay_n:
        entries = get_last_n_entries(replay_n)
    else:
        entries = []

    # Apply replay budget and get diagnostics
    if entries:
        entries, replay_stats = apply_replay_budget(entries, max_chars=5500)
        replay_policy = {**replay_stats, "reason": replay_reason}
        
        # Format previous turns for context injection
        replay_lines = []
        for e in entries:
            replay_lines.append(f"User: {e['user_prompt']}")
            replay_lines.append(f"Assistant: {e['model_response']}")
        replay_block = "\n".join(replay_lines) + "\n\n"

    # ________________________________________________________________________
    # Step 2: Build final prompt
    # ________________________________________________________________________
    
    # Get persona text (may be empty for neutral)
    persona_text = get_persona_text(persona)
    
    # Get verbosity text (always present: either concise or detailed instruction)
    verbosity_text = get_verbosity_text(classified_verbosity)
    
    # Build prompt: mode enforcement (if any) -> persona (if any) -> verbosity -> replay -> user input
    if active_mode:
        if persona_text:
            full_prompt = f"{MODE_ENFORCEMENT}\n\n{persona_text}\n\n{verbosity_text}\n\n{replay_block}{user_input}".encode("utf-8")
        else:
            full_prompt = f"{MODE_ENFORCEMENT}\n\n{verbosity_text}\n\n{replay_block}{user_input}".encode("utf-8")
    else:
        if persona_text:
            full_prompt = f"{persona_text}\n\n{verbosity_text}\n\n{replay_block}{user_input}".encode("utf-8")
        else:
            full_prompt = f"{verbosity_text}\n\n{replay_block}{user_input}".encode("utf-8")

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

    # ________________________________________________________________________
    # Step 4: Log the interaction
    # ________________________________________________________________________
    
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
        replay_policy=replay_policy,
    )


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
    
    args = sys.argv[1:]

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
                    
                    # Execute query
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
