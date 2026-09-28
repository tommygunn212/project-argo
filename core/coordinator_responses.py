"""Deterministic response formatting for :class:`core.coordinator.Coordinator`."""

from __future__ import annotations

import re
from typing import Optional

from core import system_response_formatter as system_format


class CoordinatorResponseMixin:
    def _build_count_response(self, text: str) -> str:
        target = self._parse_count_target(text)
        if target < 1:
            target = 1
        target = min(target, 50)
        return ", ".join(str(i) for i in range(1, target + 1))

    def _parse_count_target(self, text: str) -> int:
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

    def _format_system_health(self, health: dict) -> str:
        return system_format.format_system_health(health)

    def _format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        return system_format.format_system_memory_info(total_gb, used_pct, temps)

    def _format_temperature_response(self, temps: dict) -> str:
        return system_format.format_temperature_response(temps)

    def _format_system_full_report(self, report: dict) -> str:
        return system_format.format_system_full_report(report)

    def _format_size_gb(self, gb: float) -> str:
        return system_format.format_size_gb(gb)

    def _safe_speak(self, text: str, interaction_id: Optional[str] = None) -> None:
        if not text or not text.strip():
            return
        if not self.runtime_overrides.get("tts_enabled", True):
            return
        current_interaction_id = interaction_id or self.interaction_id
        if self._response_interaction_id != current_interaction_id:
            self._response_interaction_id = current_interaction_id
            self._response_committed = False
        if self._response_committed:
            self.logger.warning(
                "[Response] Duplicate response suppressed (interaction_id=%s)",
                current_interaction_id,
            )
            return
        self.logger.info(f"Argo: {text}")
        self._response_committed = True
        try:
            self.acquire_audio("TTS")
        except Exception as e:
            self.logger.warning(f"[TTS] Audio ownership denied: {e}")
            return
        try:
            self.sink.speak(text, interaction_id=interaction_id or self.interaction_id)
        finally:
            self.release_audio("TTS")
