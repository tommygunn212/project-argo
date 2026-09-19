"""Gaming / editing PC profile switch: power plan, display refresh rate, and
a configured set of background apps to close on entry.

Config-driven via config.json's "pc_profiles" key (mirrors music_aliases.json /
user_preferences.json - Tommy retunes it without a code change). Two fixed,
named profiles ("gaming", "editing") rather than a generic snapshot/restore:
predictable voice behaviour - "switch to gaming" always means the same thing.

Windows-only. Power plan uses `powercfg` (no new dependency). Display refresh
rate uses raw ctypes ChangeDisplaySettingsW (no pywin32 in requirements.txt).
"""

from __future__ import annotations

import ctypes
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("ARGO.PCProfile")

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "pc_profile_state.json"

# Windows' well-known built-in power scheme GUIDs - present on every Windows
# install. "Ultimate Performance" is hidden by default and only appears once
# duplicated with `powercfg /duplicatescheme`; that duplication is done lazily,
# only if a profile actually asks for it.
BUILTIN_POWER_PLANS = {
    "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "ultimate_performance": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}

# No refresh-rate / close_apps changes until Tommy fills in config.json's
# "pc_profiles" - see docs/PC_PROFILES.md.
DEFAULT_PROFILES = {
    "gaming": {"power_plan": "high_performance", "refresh_hz": None, "close_apps": []},
    "editing": {"power_plan": "balanced", "refresh_hz": None, "close_apps": []},
}

ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
DISP_CHANGE_SUCCESSFUL = 0


class _DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort),
        ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_ulong),
        ("dmPositionX", ctypes.c_long),
        ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort),
        ("dmBitsPerPel", ctypes.c_ulong),
        ("dmPelsWidth", ctypes.c_ulong),
        ("dmPelsHeight", ctypes.c_ulong),
        ("dmDisplayFlags", ctypes.c_ulong),
        ("dmDisplayFrequency", ctypes.c_ulong),
        ("dmICMMethod", ctypes.c_ulong),
        ("dmICMIntent", ctypes.c_ulong),
        ("dmMediaType", ctypes.c_ulong),
        ("dmDitherType", ctypes.c_ulong),
        ("dmReserved1", ctypes.c_ulong),
        ("dmReserved2", ctypes.c_ulong),
        ("dmPanningWidth", ctypes.c_ulong),
        ("dmPanningHeight", ctypes.c_ulong),
    ]


def _load_profiles() -> dict:
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        profiles = cfg.get("pc_profiles")
        if isinstance(profiles, dict) and "gaming" in profiles and "editing" in profiles:
            merged = {}
            for mode, defaults in DEFAULT_PROFILES.items():
                merged[mode] = {**defaults, **(profiles.get(mode) or {})}
            return merged
    except Exception:
        logger.exception("[PCProfile] config.json unreadable, using defaults")
    return DEFAULT_PROFILES


def _run_powercfg(*args: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["powercfg", *args], capture_output=True, text=True, timeout=10,
        )
        ok = result.returncode == 0
        return ok, (result.stdout or result.stderr or "").strip()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def get_active_power_plan() -> dict:
    ok, out = _run_powercfg("/getactivescheme")
    if not ok:
        return {"ok": False, "message": out}
    guid, name = None, None
    if "GUID:" in out:
        rest = out.split("GUID:", 1)[1].strip()
        guid = rest.split()[0].strip()
        if "(" in rest and ")" in rest:
            name = rest.split("(", 1)[1].rsplit(")", 1)[0]
    return {"ok": True, "guid": guid, "name": name, "raw": out}


def _resolve_plan_guid(plan_ref: str) -> str:
    key = (plan_ref or "").strip().lower().replace(" ", "_")
    return BUILTIN_POWER_PLANS.get(key, plan_ref)


def set_power_plan(plan_ref: str) -> dict:
    guid = _resolve_plan_guid(plan_ref)
    if guid == BUILTIN_POWER_PLANS["ultimate_performance"]:
        _run_powercfg("/duplicatescheme", guid)  # hidden by default; make it exist first
    ok, out = _run_powercfg("/setactive", guid)
    after = get_active_power_plan()
    verified = ok and after.get("ok", False) and (after.get("guid") or "").lower() == guid.lower()
    return {"ok": verified, "requested": plan_ref, "guid": guid, "active": after, "message": out}


def get_display_settings() -> dict:
    devmode = _DEVMODE()
    devmode.dmSize = ctypes.sizeof(_DEVMODE)
    ok = ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode))
    if not ok:
        return {"ok": False, "message": "Could not read display settings."}
    return {"ok": True, "width": devmode.dmPelsWidth, "height": devmode.dmPelsHeight,
             "refresh_hz": devmode.dmDisplayFrequency}


def set_refresh_rate(hz: int) -> dict:
    current = get_display_settings()
    if not current.get("ok"):
        return current
    devmode = _DEVMODE()
    devmode.dmSize = ctypes.sizeof(_DEVMODE)
    ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode))
    devmode.dmPelsWidth = current["width"]
    devmode.dmPelsHeight = current["height"]
    devmode.dmDisplayFrequency = int(hz)
    devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
    result_code = ctypes.windll.user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)
    after = get_display_settings()
    verified = result_code == DISP_CHANGE_SUCCESSFUL and after.get("refresh_hz") == int(hz)
    return {"ok": verified, "requested_hz": int(hz), "result_code": int(result_code),
             "before": current, "after": after}


def _close_configured_apps(names: list) -> list:
    from core.app_control import close_app, resolve_app_name

    results = []
    for name in names or []:
        key = resolve_app_name(name) or name
        try:
            ok, message = close_app(key)
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        results.append({"app": name, "ok": bool(ok), "message": message})
    return results


def _save_last_mode(mode: str) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"last_mode": mode}), encoding="utf-8")
    except Exception:
        logger.exception("[PCProfile] could not persist last mode")


def _load_last_mode():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8")).get("last_mode")
    except Exception:
        return None


def apply_profile(mode: str) -> dict:
    mode = (mode or "").strip().lower()
    if mode not in ("gaming", "editing"):
        return {"ok": False, "error": "bad_mode", "message": "mode must be 'gaming' or 'editing'."}

    profile = _load_profiles()[mode]
    before = {"power_plan": get_active_power_plan(), "display": get_display_settings()}

    plan_result = set_power_plan(profile["power_plan"]) if profile.get("power_plan") else None
    display_result = set_refresh_rate(profile["refresh_hz"]) if profile.get("refresh_hz") else None
    closed = _close_configured_apps(profile.get("close_apps") or [])

    _save_last_mode(mode)

    ok = (plan_result is None or plan_result.get("ok")) and (display_result is None or display_result.get("ok"))
    return {
        "ok": ok,
        "mode": mode,
        "before": before,
        "power_plan": plan_result,
        "display": display_result,
        "closed_apps": closed,
    }


def get_status() -> dict:
    return {
        "ok": True,
        "power_plan": get_active_power_plan(),
        "display": get_display_settings(),
        "last_mode": _load_last_mode(),
    }
