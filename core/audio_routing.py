"""Audio routing status/control (Windows)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sounddevice as sd


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: dict[str, Any]) -> None:
    path = _config_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _device_name(index: int | None, is_input: bool) -> str | None:
    try:
        if index is None:
            index = sd.default.device[0 if is_input else 1]
        if index is None:
            return None
        info = sd.query_devices(index)
        return info.get("name") if isinstance(info, dict) else None
    except Exception:
        return None


def get_audio_routing_status() -> dict[str, Any]:
    devices = sd.query_devices()
    default_in = sd.default.device[0]
    default_out = sd.default.device[1]
    input_name = _device_name(default_in, True)
    output_name = _device_name(default_out, False)
    output_devices = [d.get("name") for d in devices if d.get("max_output_channels", 0) > 0]
    input_devices = [d.get("name") for d in devices if d.get("max_input_channels", 0) > 0]
    return {
        "default_output": output_name,
        "default_input": input_name,
        "output_devices": output_devices,
        "input_devices": input_devices,
    }


def _match_devices(target: str, devices: list[dict]) -> list[dict]:
    target_lower = target.lower()
    matches = []
    for d in devices:
        name = d.get("name") or ""
        if target_lower in name.lower():
            matches.append(d)
    return matches


def set_audio_routing(target: str, is_input: bool) -> tuple[bool, str]:
    if not target:
        return False, "That audio device is not available."
    devices = sd.query_devices()
    candidates = [
        {"index": i, **d}
        for i, d in enumerate(devices)
        if (d.get("max_input_channels", 0) > 0 if is_input else d.get("max_output_channels", 0) > 0)
    ]
    matches = _match_devices(target, candidates)
    if not matches:
        return False, "That audio device is not available."
    if len(matches) > 1:
        names = ", ".join(sorted({m.get("name") for m in matches if m.get("name")}))
        return False, f"Multiple matches: {names}. Please specify the device name."
    index = matches[0].get("index")
    if index is None:
        return False, "That audio device is not available."

    config = _load_config()
    config.setdefault("audio", {})
    if is_input:
        config["audio"]["input_device_index"] = int(index)
        label = "Input"
    else:
        config["audio"]["output_device_index"] = int(index)
        label = "Output"
    _save_config(config)
    name = matches[0].get("name") or "device"
    return True, f"{label} device set to {name}."
