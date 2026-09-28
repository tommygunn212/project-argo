"""Echo-resistant barge-in detection for the classic voice loop."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BargeInDecision:
    """Result of evaluating one audio frame for a classic voice interruption."""

    pending: bool
    triggered: bool
    effective_threshold: float


class ClassicBargeInGate:
    """Require sustained speech before allowing TTS to be interrupted.

    A loud single frame is commonly speaker echo or a click. The gate keeps
    that timing policy separate from the main audio loop while leaving all
    interruption and recording side effects with the caller.
    """

    def __init__(self, *, hold_seconds: float = 0.18, speaking_multiplier: float = 3.5) -> None:
        if hold_seconds < 0:
            raise ValueError("hold_seconds must be non-negative")
        if speaking_multiplier <= 0:
            raise ValueError("speaking_multiplier must be positive")
        self.hold_seconds = hold_seconds
        self.speaking_multiplier = speaking_multiplier
        self._candidate_started_at: float | None = None

    def evaluate(
        self,
        *,
        now: float,
        is_speaking: bool,
        volume: float,
        threshold: float,
        enabled: bool,
        suppressed: bool,
    ) -> BargeInDecision:
        effective_threshold = threshold * self.speaking_multiplier if is_speaking else threshold
        is_candidate = is_speaking and volume >= effective_threshold and enabled and not suppressed

        if not is_candidate:
            self._candidate_started_at = None
            return BargeInDecision(False, False, effective_threshold)

        if self._candidate_started_at is None:
            self._candidate_started_at = now

        if now - self._candidate_started_at < self.hold_seconds:
            return BargeInDecision(True, False, effective_threshold)

        self._candidate_started_at = None
        return BargeInDecision(False, True, effective_threshold)
