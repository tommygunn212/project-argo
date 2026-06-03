"""Application status/control (Windows)."""

from __future__ import annotations

import base64
import subprocess
import logging
import ctypes
import time
from ctypes import wintypes

import psutil

from core.app_registry import APP_REGISTRY, get_supported_app_displays, resolve_app_name

LOGGER = logging.getLogger("ARGO.AppControl")

BLOCKED_PROCESSES = {
    "code.exe",
    "code - insiders.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "windowsterminal.exe",
    "wt.exe",
    "services.exe",
    "lsass.exe",
    "csrss.exe",
    "smss.exe",
    "wininit.exe",
    "winlogon.exe",
}

WRITABLE_APPS = {"notepad", "word"}


def _get_foreground_pid() -> int | None:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return None


def _close_foreground_window_if_match(pid: int) -> bool:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        fg_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
        if int(fg_pid.value) != pid:
            return False
        WM_CLOSE = 0x0010
        return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    except Exception:
        return False


def list_running_apps() -> list[str]:
    processes = []
    for proc in psutil.process_iter(attrs=["name"]):
        name = proc.info.get("name")
        if name:
            processes.append(name)
    return sorted(set(processes))


def is_app_running(app_key: str) -> bool:
    meta = APP_REGISTRY.get(app_key)
    if not meta:
        return False
    target = meta.get("process")
    if not target:
        return False
    for proc in psutil.process_iter(attrs=["name"]):
        if proc.info.get("name") == target:
            return True
    return False


def get_active_app() -> tuple[str | None, str | None]:
    pid = _get_foreground_pid()
    if not pid:
        return None, None
    try:
        proc = psutil.Process(pid)
        name = proc.name()
    except Exception:
        return None, None
    for app_key, meta in APP_REGISTRY.items():
        if meta.get("process", "").lower() == name.lower():
            return app_key, meta.get("display", app_key)
    return None, name


def open_app(app_key: str) -> tuple[bool, str]:
    meta = APP_REGISTRY.get(app_key)
    if not meta:
        return False, "I don't have a known application called that."
    display = meta.get("display", app_key.capitalize())
    launch = meta.get("launch")
    if not launch:
        return False, "I don't have a known application called that."
    # Check if already running - short deterministic response
    if is_app_running(app_key):
        LOGGER.info("[APP_OPEN] result=already_open app=%s", app_key)
        return True, f"{display} is already open."
    try:
        subprocess.Popen([launch], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        LOGGER.info("[APP_OPEN] result=success app=%s", app_key)
        return True, f"Opening {display}."
    except Exception:
        LOGGER.info("[APP_OPEN] result=failed app=%s", app_key)
        return False, f"Failed to open {display}."


def close_app(app_key: str) -> tuple[bool, str]:
    ok, message, _, _ = close_app_deterministic(app_key)
    return ok, message


def close_app_deterministic(app_key: str) -> tuple[bool, str, int | None, str]:
    meta = APP_REGISTRY.get(app_key)
    if not meta:
        LOGGER.info("[APP_CLOSE] result=blocked app=%s pid=<none>", app_key)
        return False, "I don't have a known application called that.", None, "blocked"
    target = meta.get("process")
    display = meta.get("display", app_key)
    if not target:
        LOGGER.info("[APP_CLOSE] result=blocked app=%s pid=<none>", app_key)
        return False, "I don't have a known application called that.", None, "blocked"
    if target.lower() in BLOCKED_PROCESSES:
        LOGGER.info("[APP_CLOSE] result=blocked app=%s pid=<none>", app_key)
        return False, "I can't close that application.", None, "blocked"
    matches = []
    for proc in psutil.process_iter(attrs=["name", "pid"]):
        if proc.info.get("name") == target:
            matches.append(proc)
    if not matches:
        LOGGER.info("[APP_CLOSE] result=already_closed app=%s pid=<none>", app_key)
        return False, f"{display} is not currently open.", None, "already_closed"
    chosen = None
    fg_pid = _get_foreground_pid()
    if fg_pid:
        for proc in matches:
            if proc.pid == fg_pid:
                chosen = proc
                break
    if len(matches) > 1 and chosen is None:
        LOGGER.info("[APP_CLOSE] result=blocked app=%s pid=<none>", app_key)
        return False, f"Please focus {display} and try again.", None, "blocked"
    if chosen is None:
        chosen = matches[0]
    pid = chosen.pid
    ok = False
    if target.lower() == "explorer.exe":
        if fg_pid != pid:
            LOGGER.info("[APP_CLOSE] result=blocked app=%s pid=<none>", app_key)
            return False, f"Please focus {display} and try again.", None, "blocked"
        ok = _close_foreground_window_if_match(pid)
    else:
        try:
            chosen.terminate()
            ok = True
        except Exception:
            ok = False
    if ok:
        LOGGER.info("[APP_CLOSE] result=success app=%s pid=%s", app_key, pid)
        return True, f"{display} closed.", pid, "success"
    LOGGER.info("[APP_CLOSE] result=failed app=%s pid=%s", app_key, pid)
    return False, f"I couldn't close {display}.", pid, "failed"


def focus_app(app_key: str) -> tuple[bool, str]:
    ok, message, _ = focus_app_deterministic(app_key)
    return ok, message


def focus_app_deterministic(app_key: str) -> tuple[bool, str, str]:
    meta = APP_REGISTRY.get(app_key)
    if not meta:
        LOGGER.info("[FOCUS] app=%s result=failed", app_key)
        return False, "I don't have a known application called that.", "failed"
    display = meta.get("display", app_key)
    focus_title = meta.get("focus_title", display)
    if not is_app_running(app_key):
        LOGGER.info("[FOCUS] app=%s result=not_running", app_key)
        return False, f"{display} isn't running, so I didn't bring it forward.", "not_running"
    try:
        command = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"if ($ws.AppActivate('{focus_title}')) {{ 'true' }} else {{ 'false' }}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=3,
        )
        ok = "true" in (result.stdout or "").lower()
    except Exception:
        ok = False
    if ok:
        LOGGER.info("[FOCUS] app=%s result=focused", app_key)
        return True, f"{display} focused.", "focused"
    LOGGER.info("[FOCUS] app=%s result=failed", app_key)
    return False, f"I couldn't focus {display}.", "failed"


def write_text_to_app(app_key: str, text: str) -> tuple[bool, str]:
    """Write text into a supported writable desktop app via clipboard paste."""
    if app_key not in WRITABLE_APPS:
        return False, "I can only type into Notepad or Word right now."

    meta = APP_REGISTRY.get(app_key)
    if not meta:
        return False, "I don't have a known application called that."

    display = meta.get("display", app_key.capitalize())
    focus_title = meta.get("focus_title", display)
    payload = (text or "").strip()
    if not payload:
        return False, f"There was nothing to insert into {display}."

    if not is_app_running(app_key):
        ok, msg = open_app(app_key)
        if not ok:
            return False, msg
        time.sleep(1.0 if app_key == "word" else 0.35)

    ok, msg, _ = focus_app_deterministic(app_key)
    if not ok:
        return False, msg
    time.sleep(0.12)

    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')); "
        "Set-Clipboard -Value $text; "
        "Start-Sleep -Milliseconds 120; "
        f"if ($ws.AppActivate('{focus_title}')) {{ "
        "Start-Sleep -Milliseconds 120; "
        "$ws.SendKeys('^v'); "
        "'true' "
        "} else { 'false' }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=6,
        )
        pasted = "true" in (result.stdout or "").lower()
    except Exception:
        pasted = False

    if pasted:
        LOGGER.info("[APP_WRITE] app=%s result=success chars=%s", app_key, len(payload))
        return True, f"Inserted it into {display}."

    LOGGER.info("[APP_WRITE] app=%s result=failed chars=%s", app_key, len(payload))
    return False, f"I couldn't insert it into {display}."


def app_status_response(query: str) -> str:
    app = resolve_app_name(query)
    if app:
        running = is_app_running(app)
        display = APP_REGISTRY.get(app, {}).get("display", app.title())
        return f"{display} is {'running' if running else 'not running'}."
    running = list_running_apps()
    if not running:
        return "No applications are running."
    return "Running applications: " + ", ".join(running[:10]) + "."
