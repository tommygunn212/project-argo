"""System-wide volume status and control for the classic pipeline."""

from __future__ import annotations

import re
from typing import Any, Protocol

from core.system_volume import (
    adjust_volume_percent,
    get_status,
    mute_volume,
    set_volume_percent,
    unmute_volume,
)


class SystemVolumeHost(Protocol):
    logger: Any

    def _deliver_canonical_response(self, *args, **kwargs) -> bool: ...

    def _evaluate_gates(
        self, capability_key: str, module_key: str, interaction_id: str
    ) -> tuple[bool, str]: ...


class PipelineSystemVolumeService:
    def __init__(self, host: SystemVolumeHost) -> None:
        self._host = host

    @staticmethod
    def is_system_volume_text(text: str) -> bool:
        lowered = (text or "").lower()
        if any(term in lowered for term in {"app volume", "application volume", "per app", "per-app"}):
            return False
        if any(term in lowered for term in {"headphones", "speaker", "speakers", "device", "monitor"}):
            return False
        if "music" in lowered or "song" in lowered:
            return False
        return any(term in lowered for term in {"volume", "mute", "unmute", "sound"})

    def respond_status(
        self, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        host = self._host
        allowed, reason = host._evaluate_gates(
            "system_volume", "system_volume", interaction_id
        )
        if not allowed:
            message = f"System volume status blocked by policy ({reason})."
        else:
            volume, muted = get_status()
            message = f"System volume is {volume}%. Muted: {'true' if muted else 'false'}."
        return host._deliver_canonical_response(
            message, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True,
        )

    def respond_control(
        self,
        user_text: str,
        interaction_id: str,
        replay_mode: bool,
        overrides: dict | None,
    ) -> bool:
        host = self._host
        if not self.is_system_volume_text(user_text):
            message = "System volume control requires a direct system volume command."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        allowed, reason = host._evaluate_gates(
            "system_volume", "system_volume", interaction_id
        )
        if not allowed:
            message = f"System volume control blocked by policy ({reason})."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        lowered = (user_text or "").lower()
        previous_volume, previous_muted = get_status()
        ok = False
        message = ""
        new_volume = previous_volume
        new_muted = previous_muted

        match = re.search(r"set volume to (\d{1,3})%?", lowered)
        if not match:
            match = re.search(r"\bvolume\s+(?:to\s+)?(\d{1,3})%?", lowered)
        if match:
            ok, message, previous_volume, new_volume, new_muted = set_volume_percent(
                int(match.group(1))
            )
        elif re.search(
            r"\bvolume up\b|\bturn volume up\b|\bincrease volume\b|\braise volume\b|"
            r"\braise the volume\b|\blouder\b",
            lowered,
        ):
            ok, message, previous_volume, new_volume, new_muted = adjust_volume_percent(5)
        elif re.search(
            r"\bvolume down\b|\bturn volume down\b|\bdecrease volume\b|\blower volume\b|"
            r"\blower the volume\b|\bquieter\b",
            lowered,
        ):
            ok, message, previous_volume, new_volume, new_muted = adjust_volume_percent(-5)
        elif re.search(r"\bmute\b", lowered):
            ok, message, previous_volume, new_volume, new_muted = mute_volume()
        elif re.search(r"\bunmute\b", lowered):
            ok, message, previous_volume, new_volume, new_muted = unmute_volume()
        else:
            message = "System volume control requires an explicit command."

        host.logger.info(
            f"[SYSTEM_VOLUME] prev={previous_volume} new={new_volume} muted={new_muted}"
        )
        if not ok and message:
            response = message
        elif ok and new_muted:
            response = "System volume muted."
        elif ok:
            response = f"System volume set to {new_volume}%."
        else:
            response = "System volume command failed."
        return host._deliver_canonical_response(
            response, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True,
        )
