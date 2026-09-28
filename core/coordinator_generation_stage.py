"""Response-source selection for coordinator interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from core.coordinator_music_stage import dispatch_music_stage
from core.policy import LLM_WATCHDOG_SECONDS, WATCHDOG_FALLBACK_RESPONSE
from core.watchdog import Watchdog


class GenerationHost(Protocol):
    current_probe: Any
    generator: Any
    interaction_count: int
    logger: Any
    memory: Any


@dataclass(frozen=True)
class GenerationStageResult:
    response_text: str
    output_produced: bool
    is_music_iteration: bool
    return_interaction: bool = False
    interaction_result: bool = False


def generate_interaction_response(
    host: GenerationHost,
    intent: Any,
    mark_output: Callable[[], None],
    finalize_watchdog: Callable[[], None],
    *,
    watchdog_factory: Callable[[str, float], Any] = Watchdog,
) -> GenerationStageResult:
    """Route music intents or generate the normal watchdog-protected response."""
    host.logger.info(f"[Iteration {host.interaction_count}] Generating response...")
    host.current_probe.mark("llm_start")
    music = dispatch_music_stage(host, intent, mark_output, finalize_watchdog)
    if music.routed:
        return GenerationStageResult(
            response_text=music.response_text,
            output_produced=music.output_produced,
            is_music_iteration=music.is_music_iteration,
            return_interaction=music.return_interaction,
            interaction_result=music.interaction_result,
        )

    with watchdog_factory("LLM", LLM_WATCHDOG_SECONDS) as llm_watchdog:
        response_text = host.generator.generate(intent, host.memory)
    if llm_watchdog.triggered:
        host.logger.warning("[WATCHDOG] LLM exceeded watchdog; using fallback response")
        response_text = WATCHDOG_FALLBACK_RESPONSE
    host.current_probe.mark("llm_end")
    return GenerationStageResult(response_text, False, False)
