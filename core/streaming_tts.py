"""Sentence-queue playback for the classic streaming response path."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import queue
import time
from typing import Any, Protocol


class StreamingTTSHost(Protocol):
    """The small pipeline surface required to play streamed sentences."""

    audio: Any
    broadcast: Any
    current_interaction_id: str
    current_voice_key: str
    is_speaking: bool
    logger: Any
    openai_voices: dict[str, str]
    stop_signal: Any
    tts_finished_at: float
    voices: dict[str, str]
    _edge_tts: Any
    _openai_tts: Any
    _tts_model: str
    _TTS_INSTRUCTIONS: str

    def transition_state(self, state: str, **kwargs: Any) -> Any: ...

    def _record_timeline(self, event: str, **kwargs: Any) -> Any: ...


def consume_tts_sentences(
    host: StreamingTTSHost,
    sentence_queue: Any,
    *,
    interaction_id: str,
    tts_engine: str,
    chinese_lesson: bool,
    tts_started: Any,
    tts_errors: list[Exception],
) -> None:
    """Drain queued sentences and preserve audio ownership on every exit path."""
    first_sentence = True
    prefetched = None
    prefetch_exec = None
    tts_generation = None
    try:
        while True:
            if prefetched is not None:
                sentence, pcm_data = prefetched
                prefetched = None
            else:
                try:
                    sentence = sentence_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if sentence is None:
                    break
                if host.stop_signal.is_set():
                    break
                pcm_data = None

            if first_sentence:
                first_sentence = False
                try:
                    host.audio.acquire_audio("TTS", interaction_id=interaction_id)
                except Exception as exc:
                    host.logger.error(f"[TTS-STREAM] Audio ownership error: {exc}")
                    break
                host.transition_state("SPEAKING", interaction_id=interaction_id, source="tts")
                host.is_speaking = True
                host._record_timeline("TTS_START", stage="tts", interaction_id=interaction_id)
                tts_started.set()

            if host.stop_signal.is_set():
                break

            host.logger.info(f"[TTS-STREAM] Speaking sentence ({len(sentence)} chars)")
            try:
                if tts_engine == "openai":
                    if host._openai_tts is None:
                        from core.openai_tts import OpenAIRealtimeTTS

                        voice = host.openai_voices.get(host.current_voice_key, "nova")
                        host._openai_tts = OpenAIRealtimeTTS(
                            voice=voice,
                            model=host._tts_model,
                            output_device=getattr(host.audio, "_output_device_index", None),
                            on_audio_level=lambda level: host.broadcast(
                                "tts_audio_level", {"rms": level}
                            ),
                        )
                        host._openai_tts._instructions = host._TTS_INSTRUCTIONS
                    if tts_generation is None:
                        if chinese_lesson:
                            host._openai_tts.suppress_interrupt(3.0)
                        tts_generation = host._openai_tts.begin_response()
                    elif host._openai_tts.is_cancelled(tts_generation):
                        break

                    from core.sentence_prefetch import prefetch_next

                    if prefetch_exec is None:
                        prefetch_exec = ThreadPoolExecutor(
                            max_workers=1, thread_name_prefix="tts-prefetch"
                        )
                    prefetch_future = prefetch_exec.submit(
                        prefetch_next,
                        sentence_queue,
                        host._openai_tts,
                        tts_generation,
                        host.stop_signal,
                        host.logger,
                    )
                    if pcm_data is None:
                        host._openai_tts.speak(sentence, generation=tts_generation)
                    else:
                        host._openai_tts.play_pcm(pcm_data, generation=tts_generation)
                    if host.stop_signal.is_set() or host._openai_tts.is_cancelled(tts_generation):
                        prefetch_future.cancel()
                        break
                    deadline = time.monotonic() + 30
                    while True:
                        if host.stop_signal.is_set() or host._openai_tts.is_cancelled(tts_generation):
                            prefetch_future.cancel()
                            prefetched = None
                            break
                        try:
                            prefetched = prefetch_future.result(timeout=0.05)
                            break
                        except FutureTimeout:
                            if time.monotonic() >= deadline:
                                host.logger.warning(
                                    "[TTS-STREAM] Prefetch exceeded turn deadline; cancelling speech"
                                )
                                host._openai_tts.stop()
                                prefetch_future.cancel()
                                prefetched = None
                                break
                    if prefetched is None:
                        break
                else:
                    if host._edge_tts is None:
                        from core.output_sink import EdgeTTSOutputSink

                        host._edge_tts = EdgeTTSOutputSink(
                            voice=host.voices.get(host.current_voice_key, "en-US-AriaNeural")
                        )
                    host._edge_tts.speak(sentence)
            except Exception as exc:
                host.logger.error(f"[TTS-STREAM] Sentence TTS error: {exc}")
                tts_errors.append(exc)
                if tts_engine == "openai" and host._openai_tts is not None:
                    host._openai_tts.stop()
                break
    finally:
        if prefetch_exec is not None:
            try:
                prefetch_exec.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                prefetch_exec.shutdown(wait=False)
        if tts_started.is_set():
            if host.current_interaction_id != interaction_id:
                host.logger.info(
                    f"[TTS-STREAM] Skipping stale cleanup for {interaction_id}; "
                    f"current={host.current_interaction_id}"
                )
            else:
                try:
                    host.audio.release_audio("TTS", interaction_id=interaction_id)
                except Exception as exc:
                    host.logger.error(f"[TTS-STREAM] release_audio error: {exc}")
                host.is_speaking = False
                host.tts_finished_at = time.time()
                host._record_timeline("TTS_DONE", stage="tts", interaction_id=interaction_id)
