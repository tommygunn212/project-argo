"""
Tier-1 application launch (whitelist only).

Control only. No files, URLs, or arguments.
"""

from __future__ import annotations

import subprocess
from typing import Dict, List, Optional


APP_LAUNCH_APPS: Dict[str, Dict[str, List[str] | str]] = {
    "notepad": {
        "exec": "notepad.exe",
        "aliases": ["notepad", "not pad", "note pad", "notpad", "notes"],
    },
    "calculator": {
        "exec": "calc.exe",
        "aliases": ["calculator", "calc"],
    },
    "microsoft edge": {
        "exec": "msedge.exe",
        "aliases": ["edge", "microsoft edge", "browser"],
    },
    "file explorer": {
        "exec": "explorer.exe",
        "aliases": ["file explorer", "explorer"],
    },
    "powershell": {
        "exec": "powershell.exe",
        "aliases": ["powershell", "command prompt", "cmd"],
    },
}


def resolve_app_launch_target(text: str) -> Optional[str]:
    lowered = text.lower()
    for canonical, meta in APP_LAUNCH_APPS.items():
        aliases = meta.get("aliases", [])
        if any(alias in lowered for alias in aliases):
            return canonical
    return None


def launch_app(app_key: str) -> bool:
    meta = APP_LAUNCH_APPS.get(app_key)
    if not meta:
        return False
    command = meta.get("exec")
    if not command:
        return False
    try:
        subprocess.Popen(command, shell=False)
        return True
    except Exception:
        if app_key == "microsoft edge":
            fallback_cmds = [
                ["cmd", "/c", "start", "microsoft-edge:"],
                ["cmd", "/c", "start", "msedge"],
            ]
            for cmd in fallback_cmds:
                try:
                    subprocess.Popen(cmd, shell=False)
                    return True
                except Exception:
                    continue
        return False
