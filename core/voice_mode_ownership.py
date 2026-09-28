"""Persistent microphone ownership policy for Smooth and Classic Voice."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection


@dataclass(frozen=True)
class VoiceModeDependencies:
    get_mode: Callable[[], str]
    set_mode: Callable[[str], None]
    get_listening_enabled: Callable[[], bool]
    set_listening_enabled: Callable[[bool], None]
    get_audio: Callable[[], Any]
    save_mode: Callable[[str], None]
    broadcast: Callable[[str, Any], None]
    logger: Any


def load_voice_mode(
    path: Path,
    *,
    smooth_mode: str,
    classic_mode: str,
    logger: Any,
) -> str:
    """Read a persisted voice owner, falling back safely to Classic Voice."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        mode = str(raw.get("mode", "")).strip().lower()
        if mode in (smooth_mode, classic_mode):
            return mode
    except FileNotFoundError:
        pass
    except Exception:
        logger.warning("[VoiceMode] unreadable %s; defaulting to classic", path)
    return classic_mode


def save_voice_mode(path: Path, mode: str, logger: Any) -> None:
    """Atomically persist the selected microphone owner."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"mode": mode}, indent=2), encoding="utf-8")
        temporary.replace(path)
    except Exception:
        logger.warning("[VoiceMode] could not persist mode", exc_info=True)


def set_voice_mode(
    dependencies: VoiceModeDependencies,
    mode: str,
    reason: str,
    *,
    smooth_mode: str,
    classic_mode: str,
) -> None:
    """Select one microphone owner and stop Classic input when Smooth claims it."""

    mode = mode if mode in (smooth_mode, classic_mode) else classic_mode
    changed = mode != dependencies.get_mode()
    dependencies.set_mode(mode)
    dependencies.save_mode(mode)
    if changed:
        dependencies.logger.info(
            "[VoiceMode] %s owns the microphone (%s)", mode, reason
        )
        dependencies.broadcast("voice_mode", {"mode": mode, "reason": reason})
    if mode == smooth_mode and dependencies.get_listening_enabled():
        dependencies.logger.warning(
            "[VoiceMode] classic listener was running; stopping it"
        )
        dependencies.set_listening_enabled(False)
        audio = dependencies.get_audio()
        if audio:
            try:
                audio.stop()
            except Exception:
                dependencies.logger.debug(
                    "[VoiceMode] could not stop classic audio", exc_info=True
                )


def phase_claims_smooth_voice(
    phase: str,
    live_phases: Collection[str],
) -> bool:
    """Return whether a browser phase proves Smooth Voice currently owns the mic."""

    return (phase or "").strip().lower() in live_phases
