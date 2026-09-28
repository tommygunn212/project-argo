"""Audio-device routing status and control for the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.audio_routing import get_audio_routing_status, set_audio_routing


@dataclass(frozen=True)
class AudioRoutingDependencies:
    logger: Any
    minimum_confidence: Callable[[], float]
    deliver_response: Callable[..., bool]
    evaluate_gates: Callable[[str, str, str], tuple[bool, str]]


class PipelineAudioRoutingService:
    def __init__(self, dependencies: AudioRoutingDependencies) -> None:
        self._dependencies = dependencies

    @staticmethod
    def format_status(status: dict) -> str:
        output = status.get("default_output") or "Unknown"
        input_device = status.get("default_input") or "Unknown"
        outputs = status.get("output_devices") or []
        inputs = status.get("input_devices") or []
        parts = [f"Audio output is set to {output}.", f"Input is {input_device}."]
        if outputs:
            parts.append(f"Available outputs: {', '.join(outputs[:5])}.")
        if inputs:
            parts.append(f"Available inputs: {', '.join(inputs[:5])}.")
        return " ".join(parts)

    @staticmethod
    def is_status_text(text: str) -> bool:
        lowered = (text or "").lower()
        status_phrases = {
            "audio status",
            "what audio device am i using",
            "where is sound playing",
            "are my headphones active",
            "what speakers are active",
            "audio routing status",
        }
        return any(phrase in lowered for phrase in status_phrases) or (
            "audio" in lowered
            and any(term in lowered for term in {"status", "using", "playing", "active"})
        )

    @staticmethod
    def is_control_text(text: str) -> bool:
        lowered = (text or "").lower()
        return any(
            phrase in lowered
            for phrase in {
                "switch to",
                "use",
                "set audio output to",
                "set audio input to",
                "change audio device",
                "change audio output",
                "change audio input",
            }
        )

    def respond_status(
        self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        dependencies = self._dependencies
        if self.is_control_text(user_text):
            dependencies.logger.error("[CONTROL/STATUS VIOLATION] Audio routing STATUS attempted control")
            message = "Audio routing status cannot change devices. Say a control command explicitly."
            return dependencies.deliver_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        dependencies.logger.info("[AUDIO_ROUTING] mode=STATUS")
        return dependencies.deliver_response(
            self.format_status(get_audio_routing_status()),
            interaction_id,
            replay_mode,
            overrides,
            enforce_confidence=False,
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
        dependencies = self._dependencies
        if self.is_status_text(user_text) and not self.is_control_text(user_text):
            dependencies.logger.error("[CONTROL/STATUS VIOLATION] Audio routing CONTROL attempted status-only response")
            message = "Audio routing control requires an explicit command."
            return dependencies.deliver_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        if not self.is_control_text(user_text):
            message = "Audio routing control requires an explicit command."
            return dependencies.deliver_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        if stt_conf < dependencies.minimum_confidence():
            message = "Audio routing command unclear. Please repeat."
            return dependencies.deliver_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        target = getattr(intent, "target", None)
        dependencies.logger.info(f"[AUDIO_ROUTING] mode=CONTROL action=switch target={target}")
        allowed, reason = dependencies.evaluate_gates(
            "audio_routing_control", "audio_routing", interaction_id
        )
        if not allowed:
            message = f"Audio routing control blocked by policy ({reason})."
            return dependencies.deliver_response(
                message, interaction_id, replay_mode, overrides,
                enforce_confidence=False, force_tts=True,
            )
        action_target = target or user_text
        lowered = user_text.lower()
        is_input = "input" in lowered or "mic" in lowered or "microphone" in lowered
        _ok, message = set_audio_routing(action_target, is_input)
        return dependencies.deliver_response(
            message, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True,
        )
