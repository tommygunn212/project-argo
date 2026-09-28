"""Streaming LLM-to-TTS response orchestration for the classic pipeline."""

from __future__ import annotations

import time
from typing import Any, Iterable, Protocol

from core.streamed_text_collector import StreamedTextCollector
from core.streaming_tts_worker import StreamingTTSWorker
from personas import ResponseType, apply_persona


class StreamingResponseHost(Protocol):
    """Only the pipeline surface needed by the streaming response stage."""

    llm_enabled: bool
    logger: Any
    stop_signal: Any
    _conversation_buffer: Any
    _tts_engine: str

    def _resolve_personality_mode(self) -> str: ...
    def _is_serious(self, text: str) -> bool: ...
    def _get_spoken_response_controls(self) -> dict[str, Any]: ...
    def _chinese_lesson_variant(self, user_text: str) -> str | None: ...
    def _build_llm_prompt(
        self,
        user_text: str,
        mode: str,
        serious_mode: bool,
        rag_context: str = "",
        memory_context: str = "",
        convo_context: str = "",
    ) -> str: ...
    def _build_spoken_style_block(self, user_text: str, controls: dict[str, Any]) -> str: ...
    def _get_system_message(self, mode: str, serious_mode: bool) -> str: ...
    def _stream_llm_text(self, **kwargs: Any) -> Iterable[str]: ...
    def _pop_stream_chunk(self, buffer: str, allow_soft_split: bool = False) -> tuple[str, str]: ...
    def _sanitize_tts_text(
        self,
        text: str,
        enforce_confidence: bool = True,
        deterministic: bool = False,
    ) -> str: ...
    def _record_timeline(self, event: str, stage: str, interaction_id: str = "") -> None: ...
    def _strip_prompt_artifacts(self, text: str) -> str: ...
    def _strip_disallowed_phrases(self, text: str) -> str: ...
    def broadcast(self, event: str, payload: Any) -> None: ...
    def stop_tts(self) -> None: ...


class PipelineStreamingResponseService:
    """Generate an answer while feeding complete chunks to the TTS worker."""

    def __init__(self, host: StreamingResponseHost):
        self._host = host

    def generate_and_speak(
        self,
        user_text: str,
        interaction_id: str = "",
        rag_context: str = "",
        memory_context: str = "",
        use_convo_buffer: bool = True,
        replay_mode: bool = False,
        overrides: dict | None = None,
    ) -> str:
        host = self._host
        if not host.llm_enabled:
            host.logger.info("LLM offline: skipping generation")
            return ""

        mode = host._resolve_personality_mode()
        serious_mode = host._is_serious(user_text)
        convo_messages = host._conversation_buffer.as_messages() if use_convo_buffer else []
        response_controls = host._get_spoken_response_controls()
        chinese_lesson = host._chinese_lesson_variant(user_text)
        prompt = host._build_llm_prompt(
            user_text,
            mode,
            serious_mode,
            rag_context,
            memory_context,
            convo_context="",
        )
        prompt = "\n---\n".join(
            [host._build_spoken_style_block(user_text, response_controls), prompt]
        )
        tts_engine = host._tts_engine

        def tts_consumer(sentence_queue, started, errors):
            from core.streaming_tts import consume_tts_sentences

            consume_tts_sentences(
                host,
                sentence_queue,
                interaction_id=interaction_id,
                tts_engine=tts_engine,
                chinese_lesson=chinese_lesson,
                tts_started=started,
                tts_errors=errors,
            )

        tts_worker = StreamingTTSWorker(
            tts_consumer,
            enabled=not replay_mode and not (overrides or {}).get("suppress_tts", False),
        )
        host._record_timeline("LLM_REQUEST_START", stage="llm", interaction_id=interaction_id)
        start = time.perf_counter()
        first_token_ms = None
        tts_worker.start()
        collector = StreamedTextCollector(
            pop_chunk=lambda buffer, soft: host._pop_stream_chunk(
                buffer, allow_soft_split=soft
            ),
            sanitize=lambda text: host._sanitize_tts_text(
                text, enforce_confidence=False
            ),
            enqueue=tts_worker.enqueue,
            tts_is_alive=lambda: tts_worker.is_alive,
            max_sentences=response_controls["max_sentences"],
        )

        try:
            system_message = host._get_system_message(mode, serious_mode)
            for part in host._stream_llm_text(
                prompt=prompt,
                system_message=system_message,
                convo_messages=convo_messages,
                temperature=response_controls["temperature"],
                max_tokens=response_controls["max_tokens"],
                interaction_id=interaction_id,
            ):
                if host.stop_signal.is_set():
                    break
                if not part:
                    continue
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                    host._record_timeline(
                        f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms",
                        stage="llm",
                        interaction_id=interaction_id,
                    )
                collector.accept(part)
                if collector.truncated:
                    break
            collector.flush()
        except Exception as error:
            host.logger.error(f"[LLM-STREAM] Error: {error}", exc_info=True)
        finally:
            total_ms = (time.perf_counter() - start) * 1000
            host._record_timeline(
                f"LLM_DONE {total_ms:.0f}ms", stage="llm", interaction_id=interaction_id
            )
            host.broadcast(
                "llm_metrics",
                {
                    "interaction_id": interaction_id,
                    "first_token_ms": first_token_ms,
                    "total_ms": total_ms,
                },
            )

        full_response = host._strip_prompt_artifacts(collector.full_response)
        display = host._strip_disallowed_phrases(full_response or "")
        display = apply_persona(
            display,
            ResponseType.ANSWER,
            host._resolve_personality_mode(),
        )
        if display.strip():
            host.broadcast("log", f"Argo: {display}")

        tts_worker.finish(
            stop_signal=host.stop_signal,
            stop_tts=host.stop_tts,
            logger=host.logger,
        )
        return full_response
