"""Pure state for turning streamed model text into bounded TTS chunks."""

from __future__ import annotations

from typing import Callable


class StreamedTextCollector:
    def __init__(
        self,
        *,
        pop_chunk: Callable[[str, bool], tuple[str, str]],
        sanitize: Callable[[str], str],
        enqueue: Callable[[str], None],
        tts_is_alive: Callable[[], bool],
        max_sentences: int,
    ) -> None:
        self._pop_chunk = pop_chunk
        self._sanitize = sanitize
        self._enqueue = enqueue
        self._tts_is_alive = tts_is_alive
        self._max_sentences = max_sentences
        self.full_response = ""
        self.buffer = ""
        self.queued_chunks = 0
        self.truncated = False

    def accept(self, text: str) -> None:
        self.full_response += text
        self.buffer += text
        while True:
            complete, self.buffer = self._pop_chunk(
                self.buffer,
                self.queued_chunks == 0,
            )
            if not complete:
                return
            if self._tts_is_alive():
                spoken = self._sanitize(complete)
                if spoken:
                    self._enqueue(spoken)
                    self.queued_chunks += 1
                    if self.queued_chunks >= self._max_sentences:
                        self.truncated = True
                        self.buffer = ""
                        return

    def flush(self) -> None:
        remainder = self.buffer.strip()
        if not remainder or self.truncated or not self._tts_is_alive():
            return
        spoken = self._sanitize(remainder)
        if spoken:
            self._enqueue(spoken)
