"""Fixed application registry for deterministic app control."""

import re

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
