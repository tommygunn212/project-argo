"""Bluetooth status and control responses for the classic pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from core.bluetooth import (
    connect_device,
    disconnect_device,
    get_bluetooth_status,
    pair_device,
    set_bluetooth_enabled,
)


class BluetoothHost(Protocol):
    logger: Any
    _personal_mode_min_confidence: float

    def _deliver_canonical_response(self, *args, **kwargs) -> bool: ...

    def _evaluate_gates(
        self, capability_key: str, module_key: str, interaction_id: str
    ) -> tuple[bool, str]: ...


class PipelineBluetoothService:
    def __init__(self, host: BluetoothHost) -> None:
        self._host = host

    @staticmethod
    def format_status(status: dict) -> str:
        if not status.get("adapter_present"):
            return "Bluetooth adapter not detected."
        enabled = status.get("adapter_enabled")
        paired = status.get("paired_devices") or []
        connected = status.get("connected_devices") or []
        audio_active = status.get("audio_device_active")
        parts = ["Bluetooth is on." if enabled else "Bluetooth is off."]
        parts.append(f"Paired devices: {len(paired)}.")
        if connected:
            parts.append("Connected devices: " + ", ".join(connected) + ".")
        else:
            parts.append("No devices are connected.")
        if audio_active is True:
            parts.append("Audio device active: yes.")
        elif audio_active is False:
            parts.append("Audio device active: no.")
        return " ".join(parts)

    @staticmethod
    def is_status_text(text: str) -> bool:
        lowered = (text or "").lower()
        if "bluetooth" in lowered or "bt" in lowered:
            return any(
                term in lowered
                for term in {"status", "on", "off", "connected", "paired", "devices", "adapter"}
            )
        return "connected" in lowered and any(
            term in lowered
            for term in {"headset", "headphones", "earbuds", "speaker", "keyboard", "mouse"}
        )

    @staticmethod
    def is_control_text(text: str) -> bool:
        lowered = (text or "").lower()
        if any(
            term in lowered
            for term in {"turn", "enable", "disable", "connect", "disconnect", "pair"}
        ):
            return "bluetooth" in lowered or "bt" in lowered or any(
                term in lowered
                for term in {"headset", "headphones", "earbuds", "speaker", "keyboard", "mouse"}
            )
        return False

    def respond_status(
        self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        host = self._host
        if self.is_control_text(user_text):
            host.logger.error("[CONTROL/STATUS VIOLATION] Bluetooth status attempted control")
            message = "Bluetooth status cannot change device state. Say a control command explicitly."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        host.logger.info("[BLUETOOTH] mode=STATUS")
        return host._deliver_canonical_response(
            self.format_status(get_bluetooth_status()),
            interaction_id,
            replay_mode,
            overrides,
            enforce_confidence=False,
            deterministic=True,
            force_tts=True,
        )

    def respond_control(
        self,
        intent,
        user_text: str,
        stt_conf: float,
        interaction_id: str,
        replay_mode: bool,
        overrides: dict | None,
    ) -> bool:
        host = self._host
        if self.is_status_text(user_text) and not self.is_control_text(user_text):
            host.logger.error("[CONTROL/STATUS VIOLATION] Bluetooth control attempted status-only response")
            message = "Bluetooth control requires an explicit command."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        if not self.is_control_text(user_text):
            message = "Bluetooth control requires an explicit command."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        if stt_conf < host._personal_mode_min_confidence:
            message = "Bluetooth command unclear. Please repeat."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        action = getattr(intent, "action", None)
        target = getattr(intent, "target", None)
        host.logger.info(f"[BLUETOOTH] mode=CONTROL action={action} target={target}")
        allowed, reason = host._evaluate_gates(
            "bluetooth_control", "bluetooth", interaction_id
        )
        if not allowed:
            message = f"Bluetooth control blocked by policy ({reason})."
            return host._deliver_canonical_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        if action == "on":
            _ok, message = set_bluetooth_enabled(True)
        elif action == "off":
            _ok, message = set_bluetooth_enabled(False)
        elif action == "connect":
            _ok, message = connect_device(target or "")
        elif action == "disconnect":
            _ok, message = disconnect_device(target or "")
        elif action == "pair":
            _ok, message = pair_device(target)
        else:
            _ok, message = False, "Bluetooth control requires an explicit command."
        return host._deliver_canonical_response(
            message, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True,
        )
