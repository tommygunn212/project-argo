"""Response-output watchdog lifecycle for coordinator interactions."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from core.policy import RESPONSE_WATCHDOG_SECONDS, WATCHDOG_FALLBACK_RESPONSE
from core.watchdog import Watchdog


class ResponseGuardHost(Protocol):
    logger: Any
    stop_requested: bool
    _is_speaking: Any

    def _safe_speak(self, text: str) -> None: ...


class CoordinatorResponseGuard:
    """Track whether an interaction produced output and finalize once."""

    def __init__(
        self,
        host: ResponseGuardHost,
        *,
        watchdog_factory: Callable[[str, float], Any] = Watchdog,
        fallback_response: str = WATCHDOG_FALLBACK_RESPONSE,
    ) -> None:
        self._host = host
        self._fallback_response = fallback_response
        self._watchdog = watchdog_factory("RESPONSE", RESPONSE_WATCHDOG_SECONDS)
        self._watchdog.__enter__()
        self.output_produced = False
        self._finalized = False

    def mark_output(self) -> None:
        self.output_produced = True

    def set_output(self, produced: bool) -> None:
        self.output_produced = bool(produced)

    def finalize(self) -> None:
        if self._finalized:
            return
        self._watchdog.__exit__(None, None, None)
        self._finalized = True
        if not self._watchdog.triggered or self.output_produced:
            return
        self._host.logger.warning(
            "[WATCHDOG] NO_OUTPUT_DETECTED: elapsed=%.2fs",
            self._watchdog.elapsed_seconds,
        )
        if self._fallback_response:
            try:
                self._host._safe_speak(self._fallback_response)
                self.output_produced = True
            except Exception:
                pass
        self._host.stop_requested = False
        self._host._is_speaking.clear()
