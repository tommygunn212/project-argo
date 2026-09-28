"""Deterministic response formatting for :class:`core.coordinator.Coordinator`."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from core import system_response_formatter as system_format


@dataclass(frozen=True)
class ResponseDeliveryDependencies:
    tts_enabled: bool
    interaction_id: Any
    response_interaction_id: Any
    response_committed: bool
    logger: Any
    acquire_audio: Callable[[str], None]
    release_audio: Callable[[str], None]
    speak: Callable[..., None]
    set_response_guard: Callable[[Any, bool], None]


class CoordinatorResponseService:
    """Deterministic response helpers with explicit delivery dependencies."""

    def build_count_response(self, text: str) -> str:
        target = self.parse_count_target(text)
        if target < 1:
            target = 1
        target = min(target, 50)
        return ", ".join(str(i) for i in range(1, target + 1))

    def parse_count_target(self, text: str) -> int:
        if not text:
            return 5
        match = re.search(r"\b(\d+)\b", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 5
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }
        for word, value in words.items():
            if re.search(rf"\b{word}\b", text, flags=re.IGNORECASE):
                return value
        return 5

    def format_system_health(self, health: dict) -> str:
        return system_format.format_system_health(health)

    def format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        return system_format.format_system_memory_info(total_gb, used_pct, temps)

    def format_temperature_response(self, temps: dict) -> str:
        return system_format.format_temperature_response(temps)

    def format_system_full_report(self, report: dict) -> str:
        return system_format.format_system_full_report(report)

    def format_size_gb(self, gb: float) -> str:
        return system_format.format_size_gb(gb)

    def safe_speak(
        self,
        dependencies: ResponseDeliveryDependencies,
        text: str,
    ) -> None:
        if not text or not text.strip():
            return
        if not dependencies.tts_enabled:
            return
        current_interaction_id = dependencies.interaction_id
        committed = dependencies.response_committed
        if dependencies.response_interaction_id != current_interaction_id:
            dependencies.set_response_guard(current_interaction_id, False)
            committed = False
        if committed:
            dependencies.logger.warning(
                "[Response] Duplicate response suppressed (interaction_id=%s)",
                current_interaction_id,
            )
            return
        dependencies.logger.info(f"Argo: {text}")
        dependencies.set_response_guard(current_interaction_id, True)
        try:
            dependencies.acquire_audio("TTS")
        except Exception as exc:
            dependencies.logger.warning(f"[TTS] Audio ownership denied: {exc}")
            return
        try:
            dependencies.speak(text, interaction_id=current_interaction_id)
        finally:
            dependencies.release_audio("TTS")
