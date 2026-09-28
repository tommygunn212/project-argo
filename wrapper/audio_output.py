"""Non-blocking audio output bridge for the synchronous wrapper runtime."""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
from collections.abc import Callable
from typing import Any


MAX_VOICE_CHARS = 150


class AudioOutputBridge:
    def __init__(
        self,
        get_sink: Callable[[], Any] | None,
        *,
        enabled: bool,
        piper_enabled: bool,
        logger,
        max_chars: int = MAX_VOICE_CHARS,
    ) -> None:
        self._get_sink = get_sink
        self._enabled = enabled
        self._piper_enabled = piper_enabled
        self._logger = logger
        self._max_chars = max_chars
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._get_sink is not None and self._enabled and self._piper_enabled

    def _worker(self) -> None:
        sink = None
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while True:
                text = self._queue.get()
                if text is None:
                    break
                if sink is None:
                    try:
                        sink = self._get_sink() if self._get_sink is not None else None
                    except Exception as exc:
                        print(f"⚠ Audio output error: {exc}", file=sys.stderr)
                        sink = None
                if sink is None:
                    continue
                try:
                    loop.run_until_complete(sink.send(text))
                except Exception as exc:
                    print(f"⚠ Audio output error: {exc}", file=sys.stderr)
        finally:
            loop.stop()
            loop.close()

    def _start(self) -> None:
        if not self.available or (self._thread and self._thread.is_alive()):
            return
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name="ArgoOutputSink",
                daemon=True,
            )
            self._thread.start()

    def send(self, text: str) -> None:
        if not self.available:
            return
        spoken_text = text[: self._max_chars]
        if len(text) > self._max_chars:
            self._logger.debug(
                "Capping voice output: %s → %s chars", len(text), self._max_chars
            )
        self._start()
        self._queue.put(spoken_text)
