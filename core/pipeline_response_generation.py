"""Non-streaming LLM response generation for the classic pipeline."""

from __future__ import annotations

import time
from typing import Any, Iterable, Protocol

from core.knowledge_answer_guard import enforce_knowledge_answer


class ResponseGenerationHost(Protocol):
    """Pipeline surface required for non-streaming response generation."""

    llm_enabled: bool
    llm_model_name: str
    logger: Any
    stop_signal: Any
    _conversation_buffer: Any
    _llm_router: Any

    def _resolve_personality_mode(self) -> str: ...
    def _is_serious(self, text: str) -> bool: ...
    def _build_llm_prompt(
        self,
        user_text: str,
        mode: str,
        serious_mode: bool,
        rag_context: str = "",
        memory_context: str = "",
        convo_context: str = "",
    ) -> str: ...
    def _get_system_message(self, mode: str, serious_mode: bool) -> str: ...
    def _stream_llm_text(self, **kwargs: Any) -> Iterable[str]: ...
    def _strip_prompt_artifacts(self, text: str) -> str: ...
    def _record_timeline(self, event: str, stage: str, interaction_id: str = "") -> None: ...
    def broadcast(self, event: str, payload: Any) -> None: ...


class PipelineResponseGenerationService:
    """Generate a complete response and enforce knowledge-answer policy."""

    def __init__(self, host: ResponseGenerationHost):
        self._host = host

    def generate(
        self,
        text: str,
        *,
        interaction_id: str = "",
        rag_context: str = "",
        memory_context: str = "",
        use_convo_buffer: bool = True,
        intent_type: str | None = None,
        confidence: float = 1.0,
    ) -> str:
        host = self._host
        if not host.llm_enabled:
            host.logger.info("LLM offline: skipping generation")
            return ""
        mode = host._resolve_personality_mode()
        serious_mode = host._is_serious(text)
        convo_messages = (
            host._conversation_buffer.as_messages() if use_convo_buffer else []
        )
        prompt = host._build_llm_prompt(
            text,
            mode,
            serious_mode,
            rag_context,
            memory_context,
            convo_context="",
        )
        host.logger.info(f"[LLM] Prompt: '{text}'")
        host.logger.debug(f"[LLM] Full prompt (first 500 chars): {prompt[:500]}")
        full_response = ""
        try:
            host._record_timeline(
                "LLM_REQUEST_START", stage="llm", interaction_id=interaction_id
            )
            start = time.perf_counter()
            first_token_ms = None
            system_message = host._get_system_message(mode, serious_mode)
            for part in host._stream_llm_text(
                prompt=prompt,
                system_message=system_message,
                convo_messages=convo_messages,
                temperature=0.7,
                max_tokens=1024,
                interaction_id=interaction_id,
            ):
                if host.stop_signal.is_set():
                    break
                if part and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                    host._record_timeline(
                        f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms",
                        stage="llm",
                        interaction_id=interaction_id,
                    )
                full_response += part

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
            full_response = host._strip_prompt_artifacts(full_response)
            default_model = host._llm_router.last_model or host.llm_model_name

            def retry_knowledge_answer(
                schema_instruction: str, model_override: str | None
            ) -> str:
                retry_prompt = host._build_llm_prompt(
                    text + "\n\n" + schema_instruction,
                    mode,
                    serious_mode,
                    rag_context,
                    memory_context,
                    convo_context="",
                )
                retry_response = ""
                try:
                    for chunk in host._stream_llm_text(
                        prompt=retry_prompt,
                        system_message=host._get_system_message(mode, serious_mode),
                        convo_messages=convo_messages,
                        temperature=0.7,
                        max_tokens=1024,
                        interaction_id=interaction_id,
                        model_override=model_override,
                    ):
                        if host.stop_signal.is_set():
                            break
                        retry_response += chunk
                    return host._strip_prompt_artifacts(retry_response)
                except Exception as error:
                    host.logger.error(f"[LLM] Retry Error: {error}")
                    return full_response

            guarded = enforce_knowledge_answer(
                initial_response=full_response,
                user_text=text,
                intent_type=intent_type,
                confidence=confidence,
                must_pass_phrases=getattr(host, "must_pass_phrases", None),
                retry=retry_knowledge_answer,
                default_model=default_model,
            )
            if guarded.outcome == "retry_pass":
                host.logger.info(
                    "[KNOWLEDGE GUARD] Principle section and domain keyword found on retry."
                )
            elif guarded.outcome == "must_pass_fallback":
                host.logger.warning(
                    f"[KNOWLEDGE GUARD] LLM failed schema for MUST_PASS "
                    f"{intent_type}. Using deterministic fallback."
                )
                host.logger.info(
                    "[KNOWLEDGE GUARD] knowledge_fallback_used = true"
                )
            elif guarded.outcome == "retry_weak":
                host.logger.warning(
                    "[KNOWLEDGE GUARD] Principle section or domain keyword still "
                    "missing after retry. Downgrading confidence."
                )
            else:
                host.logger.info(f"[LLM] Response: '{guarded.text[:60]}...'")
            return guarded.text
        except Exception as error:
            host.logger.error(f"[LLM] Error: {error}")
            host._record_timeline(
                "LLM_ERROR", stage="llm", interaction_id=interaction_id
            )
            return "[Error connecting to LLM]"
