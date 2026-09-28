"""Cross-process preferences shared by ARGO's realtime worker and UI."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import get_config

ROOT = Path(__file__).resolve().parents[1]
VOICE_PERSONALITY_FILE = ROOT / "runtime" / "voice_personality.json"
REALTIME_VOICE_FILE = ROOT / "runtime" / "realtime_voice.json"
VOICE_MODE_FILE = ROOT / "runtime" / "voice_mode.json"

REALTIME_VOICES = [
    ("marin", "Marin - warm, natural (default)"),
    ("cedar", "Cedar - warm, lower"),
    ("alloy", "Alloy - balanced, neutral"),
    ("ash", "Ash - clear, even"),
    ("ballad", "Ballad - soft, expressive"),
    ("coral", "Coral - bright, friendly"),
    ("echo", "Echo - crisp, measured"),
    ("sage", "Sage - calm, steady"),
    ("shimmer", "Shimmer - light, quick"),
    ("verse", "Verse - rich, narrative"),
]
REALTIME_VOICE_NAMES = [voice for voice, _ in REALTIME_VOICES]


def _env_or_config(config: Any, env_key: str, config_key: str, default: Any) -> Any:
    env_value = os.getenv(env_key)
    if env_value not in (None, ""):
        return env_value
    value = config.get(config_key, default)
    return default if value in (None, "") else value


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_realtime_voice(config: Any | None = None) -> str:
    env_value = (os.getenv("ARGO_REALTIME_VOICE") or "").strip()
    if env_value:
        return env_value
    chosen = str(_read_json(REALTIME_VOICE_FILE).get("voice", "")).strip().lower()
    if chosen in REALTIME_VOICE_NAMES:
        return chosen
    cfg = config or get_config()
    return str(_env_or_config(cfg, "ARGO_REALTIME_VOICE", "livekit.voice", "marin") or "marin")


def write_realtime_voice(voice: str) -> None:
    name = str(voice or "").strip().lower()
    if name not in REALTIME_VOICE_NAMES:
        raise ValueError(
            f"{voice!r} is not a gpt-realtime voice. Choose from: "
            f"{', '.join(REALTIME_VOICE_NAMES)}"
        )
    _write_json(
        REALTIME_VOICE_FILE,
        {"voice": name, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


def read_voice_personality(config: Any | None = None) -> str:
    env_value = (os.getenv("ARGO_REALTIME_PERSONALITY") or "").strip()
    if env_value:
        return env_value
    selected = str(_read_json(VOICE_PERSONALITY_FILE).get("personality", "")).strip()
    if selected:
        return selected
    cfg = config or get_config()
    return str(_env_or_config(cfg, "ARGO_PERSONALITY", "personality.default", "argo") or "argo")


def write_voice_personality(personality: str) -> None:
    name = str(personality or "").strip()
    if not name:
        return
    _write_json(
        VOICE_PERSONALITY_FILE,
        {"personality": name, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


def read_voice_mode() -> str:
    mode = str(_read_json(VOICE_MODE_FILE).get("mode", "")).strip().lower()
    return mode if mode in ("smooth", "classic") else "classic"
