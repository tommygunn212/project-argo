"""Lazy, failure-cached Silero VAD construction for the coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SpeechGateDependencies:
    sample_rate: int
    threshold: float
    get_cached_gate: Callable[[], Any]
    cache_gate: Callable[[Any], None]
    has_failed: Callable[[], bool]
    mark_failed: Callable[[], None]
    gate_factory: Callable[..., Any]
    logger: Any


def get_speech_gate(dependencies: SpeechGateDependencies) -> Any:
    """Return one cached Silero gate, never retrying a failed initialization."""
    gate = dependencies.get_cached_gate()
    if gate is not None:
        return gate
    if dependencies.has_failed():
        return None
    try:
        gate = dependencies.gate_factory(
            sample_rate=dependencies.sample_rate,
            threshold=dependencies.threshold,
        )
    except Exception:
        dependencies.logger.exception(
            "[Record] Silero gate could not be created; using energy detection"
        )
        dependencies.mark_failed()
        return None
    if not gate.available:
        dependencies.mark_failed()
        return None
    dependencies.cache_gate(gate)
    return gate
