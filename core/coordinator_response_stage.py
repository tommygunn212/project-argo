"""Post-generation delivery and bookkeeping for coordinator interactions."""

from __future__ import annotations

import time
from typing import Any, Protocol

from core.intent_models import IntentType
from core.policy import TTS_WATCHDOG_SECONDS
from core.watchdog import Watchdog


class CoordinatorResponseHost(Protocol):
    """Narrow coordinator surface required after response generation."""

    STOP_KEYWORDS: tuple[str, ...]
    _is_speaking: Any
    builder: Any
    current_probe: Any
    generator: Any
    interaction_count: int
    latency_stats: Any
    logger: Any
    memory: Any
    runtime_overrides: dict[str, Any]
    stop_requested: bool

    def _extract_code_block(self, response_text: str) -> str | None: ...

    def _infer_sandbox_filename(self, text: str, response_text: str) -> str: ...

    def _strip_code_blocks(self, response_text: str) -> str: ...

    def _speak_with_interrupt_detection(self, response_text: str) -> None: ...


def deliver_and_record_response(
    coordinator: CoordinatorResponseHost,
    *,
    intent: Any,
    user_text: str,
    response_text: str,
    overrides: dict[str, Any],
    output_produced: bool = False,
) -> bool:
    """Deliver a generated response and persist the completed interaction."""
    coordinator._last_response = response_text
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Response: '{response_text}'"
    )
    coordinator.last_response_text = response_text

    if intent.intent_type == IntentType.DEVELOP:
        code_block = coordinator._extract_code_block(response_text)
        if code_block:
            filename = coordinator._infer_sandbox_filename(user_text, response_text)
            coordinator.builder.write_script(filename, code_block)
            coordinator.builder.open_in_vscode(filename)
            coordinator._last_built_script = filename
            response_text = coordinator._strip_code_blocks(response_text)

    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Speaking response..."
    )
    coordinator.current_probe.mark("tts_start")

    if not coordinator.runtime_overrides.get("tts_enabled", True):
        coordinator.logger.info("[TTS] Disabled by runtime override")
    elif overrides.get("suppress_tts"):
        coordinator.logger.info("[TTS] Suppressed for next interaction override")
    elif response_text and response_text.strip():
        if bool(getattr(coordinator.generator, "_streamed_output", False)):
            coordinator.logger.debug("[TTS] Streaming enabled; skipping duplicate speak")
            output_produced = True
        else:
            coordinator._is_speaking.set()
            try:
                with Watchdog("TTS", TTS_WATCHDOG_SECONDS) as tts_watchdog:
                    coordinator._speak_with_interrupt_detection(response_text)
                if tts_watchdog.triggered:
                    coordinator.logger.warning("[WATCHDOG] TTS exceeded watchdog threshold")
                output_produced = True
            finally:
                coordinator._is_speaking.clear()
    else:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Response is empty, skipping TTS"
        )

    coordinator.current_probe.mark("tts_end")
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Response spoken"
    )
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Storing in memory..."
    )
    coordinator.memory.append(
        user_utterance=user_text,
        parsed_intent=intent.intent_type.value,
        generated_response=response_text,
    )
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Memory updated: {coordinator.memory}"
    )

    response_lower = response_text.lower()
    for keyword in coordinator.STOP_KEYWORDS:
        if keyword in response_lower:
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Stop keyword detected: '{keyword}'"
            )
            coordinator.stop_requested = True
            break

    coordinator.current_probe.log_summary()
    coordinator.latency_stats.add_probe(coordinator.current_probe)
    return output_produced
