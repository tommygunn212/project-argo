"""Opening, closing, focusing and typing into desktop applications.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

from core.realtime_tools._base import capability, logger

__all__ = [
    "app_open",
    "apps_launchable",
    "app_close",
    "app_focus",
    "apps_running",
    "writable_apps",
    "read_app_text",
    "app_write",
]


@capability
def app_open(name: str) -> dict:
    """Launch an app by the name Tommy said.

    ARGO's curated registry knows five apps, so anything else used to fail
    silently. Fall through to what is actually installed - taskbar pins first,
    then the registry's App Paths, the Start Menu, and PATH.
    """
    from core.app_control import open_app, resolve_app_name

    key = resolve_app_name(name)
    if key:
        ok, message = open_app(key)
        return {"ok": bool(ok), "app": key, "requested": name,
                "source": "argo_registry", "message": message}

    from core.app_resolver import resolve

    hit = resolve(name)
    if not hit:
        return {
            "ok": False,
            "error": "not_installed",
            "requested": name,
            "message": f"I couldn't find anything installed called {name}.",
        }

    os.startfile(hit["target"])  # handles .lnk shortcuts and .exe alike
    return {
        "ok": True,
        "app": hit["name"],
        "requested": name,
        "source": hit["source"],
        "message": f"Opening {hit['name']}.",
    }


@capability
def apps_launchable() -> dict:
    """Everything ARGO could open, and what is pinned to the taskbar."""
    from core.app_resolver import installed_names, _taskbar_index

    names = installed_names()
    return {
        "ok": True,
        "count": len(names),
        "pinned": sorted(p.stem for p in _taskbar_index().values()),
        "all": names,
    }


@capability
def app_close(name: str) -> dict:
    from core.app_control import close_app, resolve_app_name

    key = resolve_app_name(name) or name
    ok, message = close_app(key)
    return {"ok": bool(ok), "app": key, "requested": name, "message": message}


@capability
def app_focus(name: str) -> dict:
    from core.app_control import focus_app, resolve_app_name

    key = resolve_app_name(name) or name
    ok, message = focus_app(key)
    return {"ok": bool(ok), "app": key, "requested": name, "message": message}


@capability
def apps_running() -> dict:
    from core.app_control import get_active_app, list_running_apps, get_supported_app_displays

    active, title = get_active_app()
    return {
        "ok": True,
        "running": list_running_apps() or [],
        "active": active,
        "active_window_title": title,
        "known_apps": get_supported_app_displays() or [],
    }


@capability
def writable_apps() -> dict:
    """Which apps ARGO can actually type into, as opposed to merely open."""
    from core.app_control import WRITABLE_APPS

    return {"ok": True, "apps": sorted(WRITABLE_APPS)}


_UIA_READ_PS = """
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ClassNameProperty, '__CLASS__')
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
foreach ($w in $wins) {
    $docCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document)
    $doc = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $docCond)
    if ($doc -ne $null) {
        $tp = $doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        Write-Output $tp.DocumentRange.GetText(-1)
    }
}
"""


# Window class names, for reading a window's text back out via UI Automation.
_UIA_CLASS = {"notepad": "Notepad", "word": "OpusApp"}


def read_app_text(app_key: str) -> Optional[str]:
    """Read what is actually in an app's window, or None if it can't be read.

    None means "could not check", which is not the same as "empty" - callers
    must not treat it as proof either way.
    """
    klass = _UIA_CLASS.get(app_key)
    if not klass:
        return None
    script = _UIA_READ_PS.replace("__CLASS__", klass)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        logger.debug("[Tools] read_app_text failed for %s", app_key, exc_info=True)
        return None
    if result.returncode != 0:
        return None
    return result.stdout or ""


def _normalise_newlines(text: str) -> str:
    """UI Automation hands back Word and Notepad text with \r line breaks."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


@capability
def app_write(name: str, text: str) -> dict:
    """Type text into a running app window (Notepad or Word).

    Opens the app first if it is not already running. Anything outside
    WRITABLE_APPS is refused by name rather than silently dropped, so ARGO
    says "I can't type into Orca Slicer" instead of claiming it wrote.
    """
    from core.app_control import WRITABLE_APPS, resolve_app_name, write_text_to_app

    payload = (text or "").strip()
    if not payload:
        return {"ok": False, "error": "empty_text", "requested": name,
                "message": "There was nothing to write."}

    key = resolve_app_name(name)
    if key not in WRITABLE_APPS:
        return {
            "ok": False,
            "error": "not_writable",
            "requested": name,
            "writable": sorted(WRITABLE_APPS),
            "message": (
                f"I can open {name}, but I can only type into "
                f"{' or '.join(sorted(WRITABLE_APPS))} right now."
            ),
        }

    ok, message = write_text_to_app(key, payload)
    if not ok:
        return {"ok": False, "error": "write_failed", "app": key,
                "requested": name, "message": message}

    # write_text_to_app reports on whether it sent the paste, not on
    # whether anything arrived - a fuzzy AppActivate can match the wrong
    # window and the keystroke goes nowhere. Read the window back.
    time.sleep(0.4)
    seen = read_app_text(key)
    if seen is None:
        return {"ok": True, "verified": False, "app": key, "requested": name,
                "characters": len(payload),
                "message": f"{message} I couldn't check the window to confirm it."}
    if _normalise_newlines(payload) not in _normalise_newlines(seen):
        return {
            "ok": False,
            "error": "not_verified",
            "app": key,
            "requested": name,
            "characters": len(payload),
            "message": (
                f"I sent it to {key}, but the text isn't in the window - "
                "it may have gone somewhere else."
            ),
        }
    return {"ok": True, "verified": True, "app": key, "requested": name,
            "characters": len(payload), "message": message}
