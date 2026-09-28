"""Gated retrieval context for the classic LLM path."""

import re
from dataclasses import dataclass
from typing import Any, Callable


_TECHNICAL_RAG_TERMS = (
    "argo",
    "home assistant",
    "jellyfin",
    "server",
    "config",
    "log",
    "error",
    "code",
    "repo",
    "repository",
    "file",
    "database",
    "api",
    "livekit",
    "tts",
    "stt",
    "whisper",
    "piper",
    "plugin",
    "deploy",
    "test",
    "debug",
)


@dataclass(frozen=True)
class RagContextDependencies:
    capability_enabled: Callable[[str], bool]
    permission_allowed: Callable[[str], bool]
    module_enabled: Callable[[str], bool]
    should_use_context: Callable[[str], bool]
    logger: Any
    record_timeline: Callable[..., None]


def should_use_rag_context(user_text: str) -> bool:
    """Keep project retrieval out of ordinary free-form conversation."""

    text = (user_text or "").lower()
    return any(term in text for term in _TECHNICAL_RAG_TERMS)


def retrieve_rag_context(
    dependencies: RagContextDependencies,
    *,
    user_text: str,
    interaction_id: str,
    config: dict,
) -> str:
    """Return sanitized, formatted knowledge context when every gate allows it."""

    if not dependencies.capability_enabled("rag_query"):
        return ""
    if not dependencies.permission_allowed("rag_query"):
        return ""
    if not dependencies.module_enabled("rag"):
        return ""
    if not dependencies.should_use_context(user_text):
        dependencies.logger.info("[RAG] skipped for conversational turn")
        dependencies.record_timeline(
            "RAG_SKIPPED_CONVERSATIONAL",
            stage="rag",
            interaction_id=interaction_id,
        )
        return ""

    safe_query = " ".join(re.findall(r"[a-z0-9]+", (user_text or "").lower()))
    safe_query = re.sub(r"\s+", " ", safe_query).strip()
    token_count = len(safe_query.split()) if safe_query else 0
    dependencies.logger.info(
        f"[RAG] sanitized_rag_query='{safe_query}' tokens={token_count}"
    )
    if token_count < 2:
        return ""

    try:
        from core.knowledge_service import format_prompt_context, query_knowledge

        result = query_knowledge(safe_query, config=config)
    except Exception as exc:
        dependencies.logger.warning(f"[RAG] Query failed: {exc}")
        dependencies.record_timeline(
            "RAG_QUERY_ERROR", stage="rag", interaction_id=interaction_id
        )
        return ""

    context = format_prompt_context(result)
    if not context:
        error = result.get("error", "empty") if isinstance(result, dict) else "invalid_result"
        dependencies.logger.info(
            "[RAG] Knowledge service returned no context: %s", error
        )
        dependencies.record_timeline(
            "RAG_QUERY_EMPTY", stage="rag", interaction_id=interaction_id
        )
        return ""

    dependencies.record_timeline(
        "RAG_QUERY_HIT anythingllm", stage="rag", interaction_id=interaction_id
    )
    return context
