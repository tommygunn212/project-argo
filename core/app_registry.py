"""Fixed application registry for deterministic app control."""

import re

# Lightweight alias normalization map (spoken → canonical)
# Applied before intent parsing to normalize common variations
APP_NAME_ALIASES = {
    # Notepad variations
    "not pad": "notepad",
    "note pad": "notepad",
    "notpad": "notepad",
    "notes": "notepad",
    # Edge/browser variations
    "the browser": "edge",
    "my browser": "edge",
    "web browser": "edge",
    # Word variations
    "ms word": "word",
    "microsoft word": "word",
    # Calculator variations  
    "the calculator": "calculator",
    "my calculator": "calculator",
    # File Explorer variations
    "file manager": "file explorer",
    "files": "file explorer",
    "my files": "file explorer",
}


def normalize_app_text(text: str) -> str:
    """Normalize app name aliases in text before intent parsing.
    
    Simple substring replacement - no fuzzy matching, no ML.
    """
    if not text:
        return text
    result = text.lower()
    for alias, canonical in APP_NAME_ALIASES.items():
        # Only replace if it's a word boundary match
        pattern = rf"\b{re.escape(alias)}\b"
        result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)
    return result


APP_REGISTRY = {
    "notepad": {
        "process": "notepad.exe",
        "launch": "notepad.exe",
        "aliases": ["notepad", "not pad", "note pad", "notpad", "notes"],
        "display": "Notepad",
        "focus_title": "Notepad",
    },
    "word": {
        "process": "WINWORD.EXE",
        "launch": "winword.exe",
        "aliases": ["word", "microsoft word", "ms word"],
        "display": "Word",
        "focus_title": "Word",
    },
    "microsoft edge": {
        "process": "msedge.exe",
        "launch": "msedge.exe",
        "aliases": ["edge", "microsoft edge", "browser", "my browser", "the browser"],
        "display": "Microsoft Edge",
        "focus_title": "Microsoft Edge",
    },
    "calculator": {
        "process": "CalculatorApp.exe",
        "launch": "calc.exe",
        "aliases": ["calculator", "calc"],
        "display": "Calculator",
        "focus_title": "Calculator",
    },
    "file explorer": {
        "process": "explorer.exe",
        "launch": "explorer.exe",
        "aliases": ["file explorer", "explorer"],
        "display": "File Explorer",
        "focus_title": "File Explorer",
    },
}


def resolve_app_name(text: str) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for app, meta in APP_REGISTRY.items():
        if re.search(rf"\b{re.escape(app)}\b", lowered):
            return app
        for alias in meta.get("aliases", []):
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return app
    return None
