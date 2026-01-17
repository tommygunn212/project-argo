"""
================================================================================
ARGO (Autonomous-Resistant Governed Operator)
User Preferences Module — Automatic Personalization
================================================================================

Module:      prefs.py
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0 (Phase 3a)
Created:     December 2025
Purpose:     Detect and apply user preferences across sessions

================================================================================
FEATURES
================================================================================

1. PREFERENCE CATEGORIES
   - tone: casual, formal, neutral
   - verbosity: concise, detailed, medium
   - humor: likes_humor, no_humor, neutral
   - structure: bullets, prose, mixed

2. AUTOMATIC DETECTION
   - Pattern-based detection from user messages
   - Learns from explicit feedback
   - Non-invasive observation of communication style

3. PERSISTENCE
   - Stored in user_preferences.json
   - Survives across conversation sessions
   - Manual override available

4. AUTOMATIC APPLICATION
   - Injected into SYSTEM prompt before each generation
   - Model sees preferences as part of context, not hard constraints
   - Preference block prepended to memory + user input

================================================================================
FUNCTIONS
================================================================================

1. load_prefs() → dict
   Load preferences from disk, return defaults if missing

2. save_prefs(prefs: dict)
   Persist preferences to disk

3. update_prefs(user_input: str, prefs: dict) → dict
   Auto-detect preferences from user message, update dict

4. build_pref_block(prefs: dict) → str
   Create human-readable preference block for SYSTEM prompt

================================================================================
DESIGN PRINCIPLES
================================================================================

- Explicit only: Users control what ARGO learns
- No background learning: Changes only on request
- Guidance-based: Preferences are suggestions, not hard rules
- Transparent: Users can review and edit preferences.json
- Persistent: Preferences survive across sessions
- Session-independent: Each conversation receives the same prefs

================================================================================
"""

import json
from pathlib import Path

PREF_FILE = Path(__file__).parent.joinpath("user_preferences.json")

DEFAULT_PREFS = {
    "tone": None,
    "verbosity": None,
    "humor": None,
    "structure": None
}


def load_prefs():
    """Load user preferences from disk, creating default if missing."""
    if not PREF_FILE.exists():
        with open(PREF_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PREFS, f, indent=2)
        return DEFAULT_PREFS.copy()
    with open(PREF_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return DEFAULT_PREFS.copy()


def save_prefs(prefs):
    """Save user preferences to disk."""
    with open(PREF_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def update_prefs(user_input: str, prefs: dict) -> dict:
    """
    Detect and update preferences from user input.
    
    Looks for explicit preference statements like:
    - "be more casual" -> tone: casual
    - "keep it short" -> verbosity: concise
    - "be funny" -> humor: likes humor
    - "use bullet points" -> structure: bullets
    
    Returns updated preferences dict (does not save).
    """
    ui = user_input.lower()

    # Tone preferences
    if "be more casual" in ui or "casual" in ui or "chill out" in ui:
        prefs["tone"] = "casual"
    elif "be more formal" in ui or "formal" in ui or "professional" in ui:
        prefs["tone"] = "formal"

    # Verbosity preferences
    if "keep it short" in ui or "brief" in ui or "concise" in ui or "tldr" in ui:
        prefs["verbosity"] = "concise"
    elif "tell me all the details" in ui or "go deep" in ui or "detailed" in ui or "comprehensive" in ui:
        prefs["verbosity"] = "detailed"

    # Humor preferences
    if "be funny" in ui or "make me laugh" in ui or "joke" in ui or "humor" in ui or "funny" in ui:
        prefs["humor"] = "likes humor"
    elif "no joke" in ui or "serious" in ui or "no humor" in ui:
        prefs["humor"] = "no humor"

    # Structure preferences
    if "no lists" in ui or "don't use lists" in ui or "no bullet points" in ui:
        prefs["structure"] = "no lists"
    elif "use bullet points" in ui or "list out" in ui or "bullets" in ui:
        prefs["structure"] = "bullets"

    return prefs


def build_pref_block(prefs: dict) -> str:
    """
    Build a preference injection block for the prompt.
    
    Returns formatted string like:
    User preferences:
    Tone preference: casual
    Verbosity preference: concise
    ...
    
    Returns empty string if no preferences are set.
    """
    pref_lines = []
    if prefs.get("tone"):
        pref_lines.append(f"Tone preference: {prefs['tone']}")
    if prefs.get("verbosity"):
        pref_lines.append(f"Verbosity preference: {prefs['verbosity']}")
    if prefs.get("humor"):
        pref_lines.append(f"Humor preference: {prefs['humor']}")
    if prefs.get("structure"):
        pref_lines.append(f"Structure preference: {prefs['structure']}")

    if pref_lines:
        return "User preferences:\n" + "\n".join(pref_lines) + "\n\n"
    return ""
