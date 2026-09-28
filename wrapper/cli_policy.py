"""Deterministic CLI input, persona, verbosity, and formatting policy."""

from __future__ import annotations


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
