"""Home Assistant devices and the GE SmartHQ air conditioners.
"""

from __future__ import annotations

from dataclasses import asdict

from core.realtime_tools._base import capability

__all__ = [
    "smart_home_command",
    "ac_list",
    "ac_status",
    "ac_control",
]


@capability
def smart_home_command(text: str) -> dict:
    """Run a spoken smart-home command through Home Assistant.

    One entry point for lights, switches, climate, locks and scenes - turn
    on/off, dim, set color, ask status, or "list my devices" - because that
    is how Tommy talks to her, not by domain. The parsing and the HA REST
    calls already existed for the classic pipeline (tools/home_assistant.py);
    this just gives the realtime agent the same door.
    """
    from tools.home_assistant import execute_smart_home_command, is_home_assistant_configured

    if not is_home_assistant_configured():
        return {
            "ok": False,
            "error": "not_configured",
            "message": (
                "Home Assistant isn't configured yet - add its URL and "
                "access token to config.json under home_assistant."
            ),
        }
    message = execute_smart_home_command(text)
    return {"ok": True, "message": message}


_AC_NOT_CONFIGURED = {
    "ok": False,
    "error": "not_configured",
    "message": (
        "GE SmartHQ isn't configured yet - add GE_SMARTHQ_USERNAME and "
        "GE_SMARTHQ_PASSWORD to .env."
    ),
}


def _ac_unit_dict(unit) -> dict:
    d = asdict(unit)
    d.pop("raw", None)  # internal SDK payload, not for the model
    d["description"] = unit.describe()
    return d


@capability
def ac_list(include_all: bool = False) -> dict:
    """List the GE SmartHQ air conditioners and their current state."""
    from core.smart_home import SmartHomeError, credentials_present, discover

    if not credentials_present():
        return dict(_AC_NOT_CONFIGURED)
    try:
        units = discover(include_all=include_all)
        return {"ok": True, "count": len(units), "units": [_ac_unit_dict(u) for u in units]}
    except SmartHomeError as exc:
        return {"ok": False, "error": "smart_home_error", "message": str(exc)}


@capability
def ac_status(name: str) -> dict:
    """Current state of one air conditioner by name (power, temperature, mode)."""
    from core.smart_home import SmartHomeError, ac_state, credentials_present

    if not credentials_present():
        return dict(_AC_NOT_CONFIGURED)
    try:
        unit = ac_state(name)
        return {"ok": True, **_ac_unit_dict(unit)}
    except SmartHomeError as exc:
        return {"ok": False, "error": "smart_home_error", "message": str(exc)}


@capability
def ac_control(name: str, power: str = "", temperature_f: int = 0,
               mode: str = "", fan: str = "") -> dict:
    """Turn an air conditioner on/off, or set its temperature, mode or fan.

    power is "on"/"off" or "" to leave it alone. temperature_f is 60-86, or
    0 to leave it alone. mode/fan are whatever GE calls them ("cool",
    "auto", "low", "high", ...) passed through as heard - the SDK enum
    lookup is fuzzy. Returns the unit's real state after the change, not
    just an acknowledgement.
    """
    from core.smart_home import SmartHomeError, ac_set, credentials_present

    if not credentials_present():
        return dict(_AC_NOT_CONFIGURED)
    try:
        power_val = {"on": True, "off": False}.get((power or "").strip().lower())
        temp_val = int(temperature_f) if temperature_f else None
        unit = ac_set(
            name,
            power=power_val,
            temperature_f=temp_val,
            mode=mode or None,
            fan=fan or None,
        )
        return {"ok": True, **_ac_unit_dict(unit)}
    except SmartHomeError as exc:
        return {"ok": False, "error": "smart_home_error", "message": str(exc)}
