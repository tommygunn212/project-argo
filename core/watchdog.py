"""
Watchdog Utility

Simple, synchronous watchdog for timing long-running operations.
No threading. No async. No side effects beyond logging.
"""

import time
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WatchdogResult:
    block: str
    elapsed_seconds: float
    threshold_seconds: float
    triggered: bool


class Watchdog:
    """Context manager that measures elapsed time for a block."""

    def __init__(self, block: str, threshold_seconds: float):
        self.block = block
        self.threshold_seconds = threshold_seconds
        self._start = 0.0
        self.elapsed_seconds = 0.0
        self.triggered = False

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.elapsed_seconds = time.monotonic() - self._start
        if self.threshold_seconds is not None and self.elapsed_seconds > self.threshold_seconds:
            self.triggered = True
            logger.warning(
                "[WATCHDOG] %s exceeded threshold: %.2fs > %.2fs",
                self.block,
                self.elapsed_seconds,
                self.threshold_seconds,
            )
        return False

    def result(self) -> WatchdogResult:
        return WatchdogResult(
            block=self.block,
            elapsed_seconds=self.elapsed_seconds,
            threshold_seconds=self.threshold_seconds,
            triggered=self.triggered,
        )
