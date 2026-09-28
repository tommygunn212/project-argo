"""Conversation history, replay selection, recall, and voice compliance.

These functions are deterministic and side-effect free except for the explicit
NDJSON history reads/writes.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


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
    # Check for explicit environment variable override
    if os.environ.get("ARGO_CONTEXT"):
        return os.environ.get("ARGO_CONTEXT")
    
    # Check for headless indicators
    import platform
    import subprocess
    
    # If stderr is not a TTY, we're likely headless (piped output, script execution)
    if not sys.stderr.isatty():
        return "cli"
    
    # If running in CI/CD or with NO_INTERACTIVE flags
    if os.environ.get("CI") or os.environ.get("OLLAMA_NO_INTERACTIVE"):
        return "cli"
    
    # If VOICE_ENABLED=true, treat as CLI (audio playback is non-interactive/headless)
    if os.environ.get("VOICE_ENABLED", "false").lower() == "true":
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
