"""
JARVIS CODEBASE DOCUMENTATION SUMMARY

This document provides an overview of all Python modules in the JARVIS project,
their purposes, and how they interact with each other.
"""

# ============================================================================
# PROJECT STRUCTURE
# ============================================================================

"""
i:\jarvis\
├── wrapper/
│   ├── jarvis.py              ← Main CLI entry point
│   └── __pycache__/
├── runtime/
│   └── ollama/
│       ├── hal_chat.py        ← Alternative HAL model interface
│       ├── logs/              ← Daily interaction logs
│       ├── modelfiles/        ← Ollama model definitions
│       └── models/            ← Cached Ollama models
├── memory/
│   ├── embeddings/            ← Vector embeddings storage
│   ├── rag/                   ← Retrieval-augmented generation
│   └── ...
├── test_session_replay.py     ← Test suite for session replay
└── logs/                      ← Daily log files (YYYY-MM-DD.log)
"""


# ============================================================================
# MODULE DOCUMENTATION
# ============================================================================

"""
────────────────────────────────────────────────────────────────────────────
1. wrapper/jarvis.py
────────────────────────────────────────────────────────────────────────────

PURPOSE:
  Main CLI entry point for JARVIS. Handles subprocess calls to Ollama,
  persistent logging, and selective replay functionality.

KEY FEATURES:
  - Session tracking (unique UUID per run)
  - Persistent daily logging (NDJSON format)
  - Selective replay: last:N turns or entire session
  - Conversation mode enforcement
  - Intent gating (optional strict mode)
  - Persona layer (tone adjustment: neutral/dry)
  - Verbosity governor (response length control: short/long)
  - Clean CLI interface

MAIN COMPONENTS:

  SESSION_ID (line 28)
    Generated once at import time.
    All log entries share the same SESSION_ID for the entire script run.
    Format: UUID string (e.g., "c89594b7-90af-4fea-969e-8cd776b15409")

  MODE_ENFORCEMENT (line 33-48)
    System prompt injected when --mode flag is used.
    Enforces strict rule-following for conversation modes.
    Only injected if active_mode parameter is set.

  classify_input() (line 93-140)
    Deterministic intent classification based on word count.
    Returns: "empty" | "ambiguous" | "low_intent" | "command" | "valid"
    Used by: strict_mode gating to reject ambiguous input.

  LONG_FORM_CUES (line 144-149)
    Tuple of substrings that trigger "long" verbosity classification.
    Examples: "explain in detail", "step by step", "walk me through"
    Matching is case-insensitive.

  classify_verbosity() (line 151-160)
    Determines response length preference from input content.
    Returns: "short" (default) | "long" (if cues detected)
    Classification is automatic; no flag required.

  PERSONAS (line 196-206)
    Dict mapping persona names to prompt fragments.
    "neutral": empty string (no tone adjustment)
    "dry": concise, restrained tone instruction
    Presentation-only; does not affect logic or memory.

  get_persona_text() (line 209-219)
    Retrieves persona prompt fragment for injection.
    Returns: string (may be empty for neutral)

  get_verbosity_text() (line 222-235)
    Retrieves verbosity prompt fragment for injection.
    "short": concise instruction
    "long": detailed explanation instruction
    Always injects (never empty).

  _get_log_dir() (line 280)
    Resolves log directory path (always: <workspace>/logs/)
    Creates directory if it doesn't exist.

  _append_daily_log() (line 284)
    Writes a single interaction record to daily log file.
    Format: YYYY-MM-DD.log (one per calendar day)
    Records include: timestamp, session_id, user_prompt, model_response, 
                     replay_metadata, persona, verbosity

  get_last_n_entries(n) (line 336)
    Reads last N interaction records from logs (chronologically).
    Used by: --replay last:N flag
    Returns: List of dicts, oldest to newest

  get_session_entries(session_id) (line 370)
    Reads all interaction records matching a session_id.
    Used by: --replay session flag
    Returns: List of dicts, chronologically ordered

  run_jarvis() (line 413)
    Core execution function:
      1. Classify input intent (gating check)
      2. Classify input verbosity (response length preference)
      3. Handle rejected input or route commands (if gating active)
      4. Build replay context (if requested)
      5. Build final prompt (mode → persona → verbosity → replay → user input)
      6. Call Ollama's "jarvis" model via subprocess
      7. Log the interaction with all metadata
      8. Print model response to stdout

USAGE:

  Basic:
    python jarvis.py "What is the weather?"

  With mode:
    python jarvis.py --mode brainstorm "List 10 ideas"

  With persona:
    python jarvis.py --persona dry "Explain quantum mechanics"

  With long-form cue (automatic verbosity):
    python jarvis.py "Explain in detail how photosynthesis works"

  With replay (last 3 turns):
    python jarvis.py --replay last:3 "Continue"

  With session replay:
    python jarvis.py --replay session "Summarize what we discussed"

  Combined:
    python jarvis.py --session work --persona dry --replay last:2 "Step by step"

LOG FORMAT:
  
  {
    "timestamp": "2026-01-11T00:56:58",
    "session_id": "c89594b7-90af-4fea-969e-8cd776b15409",
    "active_mode": null,
    "persona": "neutral",
    "verbosity": "short",
    "replay": {
      "enabled": false,
      "count": null,
      "session": false
    },
    "user_prompt": "test message",
    "model_response": "Model's response here..."
  }


────────────────────────────────────────────────────────────────────────────
2. runtime/ollama/hal_chat.py
────────────────────────────────────────────────────────────────────────────

PURPOSE:
  Direct REST API interface to Ollama's HAL model.
  Simpler and more direct than jarvis.py (no logging, no replay).
  Useful for testing the HAL model in isolation.

KEY FEATURES:
  - HTTP-based chat completions
  - Optional system context support
  - JSON request/response handling
  - Simple CLI interface

MAIN COMPONENTS:

  OLLAMA_URL (line 26)
    Endpoint: http://localhost:11434/api/chat
    Default Ollama API server address.

  MODEL (line 29)
    Model name to query: "hal"

  chat(user_message, context=None) (line 34)
    Sends message to HAL model and returns response.
    
    Message structure:
      - System prompt: "You are called HAL."
      - Optional context: Custom system context
      - User message: User's actual input
    
    Args:
      user_message (str): User's input
      context (str|None): Optional system context
      
    Returns:
      str: Model's response

USAGE:

  Basic:
    python hal_chat.py "What is your name?"

  With context:
    python hal_chat.py "Help me debug" --context "You are technical"

NOTE:
  Unlike jarvis.py:
  - No logging
  - No replay
  - No session tracking
  - Direct API calls only


────────────────────────────────────────────────────────────────────────────
3. test_session_replay.py
────────────────────────────────────────────────────────────────────────────

PURPOSE:
  Test suite for verifying session replay functionality.
  All 3 turns execute in the same session (sharing SESSION_ID).
  Useful for development and debugging.

BEHAVIOR:
  
  Turn 1: Initial input ("one") with no replay
  Turn 2: Follow-up input ("two") with no replay
  Turn 3: Query with session replay enabled
  
  Turn 3 should reference Turn 1 and Turn 2 because replay context
  is prepended to the prompt.

USAGE:
  
  python test_session_replay.py

EXPECTED OUTPUT:
  
  - Session ID printed
  - Turn 1 & 2: Clean responses without context
  - Turn 3: Model references previous turns
  - Log metadata shows: replay.enabled=true, replay.session=true on Turn 3


────────────────────────────────────────────────────────────────────────────
"""


# ============================================================================
# DATA FLOW
# ============================================================================

"""
CLI INVOCATION:
  
  jarvis.py "user input"
    ↓
  Parse arguments (--mode, --replay)
    ↓
  Load/retrieve session context from logs (if replay)
    ↓
  Build prompt (replay + mode + user input)
    ↓
  subprocess.run(["ollama", "run", "jarvis"]) with prompt
    ↓
  Capture stdout
    ↓
  Log interaction (timestamp, session_id, user_input, response, metadata)
    ↓
  Print response to console


REPLAY FLOW:

  --replay last:3 "continue"
    ↓
  get_last_n_entries(3)
    ↓
  Read log files (newest first) until 3 entries found
    ↓
  Format as: "User: ...\nAssistant: ...\n\n"
    ↓
  Prepend to prompt: "<replay>\n\n<user_input>"
    ↓
  Send to Ollama

  --replay session "continue"
    ↓
  get_session_entries(SESSION_ID)
    ↓
  Read all logs and filter by current session_id
    ↓
  Format and prepend to prompt (same as above)
    ↓
  Send to Ollama


LOG PERSISTENCE:

  All interactions → logs/YYYY-MM-DD.log (daily)
    ↓
  NDJSON format (one JSON record per line)
    ↓
  Readable with: cat logs/2026-01-11.log | jq
    ↓
  Analyzable for: session tracking, replay verification, audit trail
"""


# ============================================================================
# KEY DESIGN DECISIONS
# ============================================================================

"""
1. SESSION_ID GENERATION
   - Once per script invocation (not per interaction)
   - Allows grouping multiple turns into a conversation session
   - Enables session-based replay
   - No cross-session memory

2. NO AUTOMATIC MEMORY
   - Replay is EXPLICIT (--replay flag required)
   - No persistent state between runs
   - User must opt-in to context injection
   - Clear separation of concerns

3. DAILY LOG FILES
   - One file per calendar day (YYYY-MM-DD.log)
   - Easier to manage/archive than one giant file
   - Natural time-based rotation
   - Simple to scan chronologically

4. NDJSON FORMAT
   - One JSON record per line
   - Easy to stream and parse incrementally
   - Corrupt lines don't break entire file
   - Compatible with standard JSON tools (jq)

5. DUAL INTERFACES
   - jarvis.py: Full-featured wrapper (logging, replay, modes)
   - hal_chat.py: Direct API access (for testing/debugging)
   - Users choose based on their needs

6. SUBPROCESS MODEL
   - Calls `ollama run jarvis` via subprocess (not API)
   - Captures stdout directly
   - Simpler error handling than HTTP
   - No network overhead (local only)

7. INTENT GATING (STRICT MODE)
   - Deterministic rule-based classification (no ML)
   - Word-count based: 0 words (empty), 1 word (ambiguous), 2 words (low_intent)
   - Rejects ambiguous input, asks for clarification
   - Optional: --strict off disables gating, allows LLM to ask for clarification
   - Default: strict_mode=True

8. PERSONA LAYER (PRESENTATION ONLY)
   - Tone adjustment via prompt injection
   - Does NOT affect logic or learning
   - Does NOT affect memory or replay
   - Does NOT affect input validation
   - Examples: "neutral" (no change), "dry" (concise, restrained)
   - Easy to add more personas via PERSONAS dict

9. VERBOSITY GOVERNOR (PRESENTATION ONLY)
   - Response length control via prompt injection
   - Does NOT affect logic or learning
   - Automatic classification based on explicit cues
   - Long-form cues: "explain in detail", "step by step", "walk me through", etc.
   - Classification is case-insensitive
   - Default: "short" (concise responses)
   - Triggered by: "long" (detailed responses)
   - Easy to add/modify cues via LONG_FORM_CUES tuple
   - Works with all other features (replay, persona, modes, gating)
"""


# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

"""
OLLAMA SETTINGS (in jarvis.py):
  env["OLLAMA_NO_INTERACTIVE"] = "1"
    Ensures Ollama doesn't hang waiting for input

LOG DIRECTORY (resolved at runtime):
  base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
  logs = os.path.join(base_dir, "logs")
  Result: i:\jarvis\logs\

MODEL NAMES:
  JARVIS: Called via subprocess ("ollama run jarvis")
  HAL: Called via REST API (http://localhost:11434/api/chat)

TIMEOUTS:
  hal_chat.py: 60 seconds per request
  subprocess calls: No explicit timeout (may hang indefinitely)

ENCODING:
  All files: UTF-8
  All responses decoded with errors="ignore" (graceful failure)
"""


# ============================================================================
# TESTING & VERIFICATION
# ============================================================================

"""
To verify everything is working:

1. Test basic jarvis.py:
   python i:\jarvis\wrapper\jarvis.py "hello"
   
   Expected: Response from model

2. Test session replay:
   python i:\jarvis\test_session_replay.py
   
   Expected: Three turns, with Turn 3 referencing Turns 1 & 2

3. Verify logs are being created:
   Get-Content i:\jarvis\logs\2026-01-11.log | tail -1 | ConvertFrom-Json
   
   Expected: JSON record with session_id, timestamp, etc.

4. Check replay metadata:
   Get-Content i:\jarvis\logs\2026-01-11.log -Tail 1 | ConvertFrom-Json | Select-Object replay
   
   Expected: replay.enabled, replay.count, replay.session fields

5. Test hal_chat.py:
   python i:\jarvis\runtime\ollama\hal_chat.py "Are you working?"
   
   Expected: Response from HAL model

6. Verify log directory location:
   In any Python shell:
   from jarvis import _get_log_dir
   print(_get_log_dir())
   
   Expected: i:\jarvis\logs
"""


# ============================================================================
# FUTURE ENHANCEMENTS
# ============================================================================

"""
Potential improvements (not yet implemented):

1. Memory Persistence
   - Store embeddings of past conversations
   - Automatic retrieval of relevant context
   - Still opt-in via flag (not automatic)

2. Intent Detection
   - Parse user intent before prompting
   - Route to different model or handler
   - Prevent hallucinations when intent is unclear

3. Structured Output
   - Log format options: JSON, CSV, database
   - Query/search logs by session_id, date range, intent
   - Analytics on conversation patterns

4. Multi-turn Transactions
   - Group related interactions
   - Atomic operations (all-or-nothing)
   - Rollback capability

5. Token Counting
   - Track token usage per interaction
   - Alert on excessive tokens
   - Cost estimation for API-based models

6. Audit Trail
   - Track who called what, when, with what result
   - Security logging
   - Compliance reporting
"""
