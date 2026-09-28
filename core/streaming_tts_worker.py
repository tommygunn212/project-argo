"""Lifecycle management for sentence-streaming TTS consumers."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Optional


class StreamingTTSWorker:
    """Own a sentence queue and bounded daemon-thread shutdown policy."""

    def __init__(
        self,
        consumer: Callable[[queue.Queue[Optional[str]], threading.Event, list], None],
        *,
        enabled: bool,
        thread_factory: Callable[..., Any] = threading.Thread,
    ) -> None:
        self.queue: queue.Queue[Optional[str]] = queue.Queue()
        self.started = threading.Event()
        self.errors: list[Any] = []
        self._enabled = enabled
        self._thread = thread_factory(target=self._consume, daemon=True)
        self._consumer = consumer

    def _consume(self) -> None:
        self._consumer(self.queue, self.started, self.errors)

    @property
    def is_alive(self) -> bool:
        return bool(self._thread.is_alive())

    def start(self) -> None:
        if self._enabled:
            self._thread.start()

    def enqueue(self, sentence: str) -> None:
        self.queue.put(sentence)

    def finish(
        self,
        *,
        stop_signal: Any,
        stop_tts: Callable[[], None],
        logger: Any,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        if stop_signal.is_set():
            while True:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break
        self.queue.put(None)
        if not self.is_alive:
            return

        join_started = time_fn()
        interrupt_seen_at = time_fn() if stop_signal.is_set() else None
        while self.is_alive:
            self._thread.join(timeout=0.1)
            if not self.is_alive:
                break
            if stop_signal.is_set():
                if interrupt_seen_at is None:
                    interrupt_seen_at = time_fn()
                if time_fn() - interrupt_seen_at >= 0.75:
                    logger.warning("[TTS-STREAM] TTS thread still unwinding after interrupt")
                    stop_tts()
                    break
            elif time_fn() - join_started >= 30:
                logger.warning("[TTS-STREAM] TTS thread did not finish within 30s")
                stop_tts()
                break
