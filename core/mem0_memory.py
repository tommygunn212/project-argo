"""Optional Mem0 long-term memory adapter for ARGO.

Mem0 is treated as a companion memory layer, not the source of truth.
SQLite/PostgreSQL keep local transcripts and audit data; Mem0 stores selected
durable facts and preferences for semantic recall.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
import re
from typing import Any, Callable, Optional


logger = logging.getLogger("ARGO.Mem0")


def _env_bool(name: str) -> Optional[bool]:
    value = os.getenv(name)
    if value is None:
        return None
    return _bool_value(value)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_value(value: Any, default: int, min_value: int = 1, max_value: int = 20) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(min_value, min(parsed, max_value))


def _clean_user_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", (value or "").strip())
    return cleaned.strip("-") or "tommy"


def _extract_result_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "memories", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _memory_text(item: dict[str, Any]) -> str:
    for key in ("memory", "text", "content", "value"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _memory_id(item: dict[str, Any]) -> str:
    for key in ("memory_id", "id"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


@dataclass(frozen=True)
class Mem0MemoryConfig:
    enabled: bool
    api_key: str = field(default="", repr=False)
    user_id: str = "tommy"
    search_limit: int = 5
    context_char_limit: int = 1200
    auto_store_turns: bool = False


def get_mem0_config(config: Any = None) -> Mem0MemoryConfig:
    api_key = os.getenv("MEM0_API_KEY", "")
    enabled = _env_bool("ARGO_MEM0_ENABLED")
    user_id = os.getenv("ARGO_MEM0_USER_ID")
    search_limit = os.getenv("ARGO_MEM0_SEARCH_LIMIT")
    context_char_limit = os.getenv("ARGO_MEM0_CONTEXT_CHARS")
    auto_store_turns = _env_bool("ARGO_MEM0_AUTO_STORE_TURNS")

    if config is None:
        try:
            from core.config import get_config

            config = get_config()
        except Exception:
            config = None

    if config is not None:
        api_key = api_key or str(config.get("memory.mem0.api_key", "") or "")
        if enabled is None:
            configured_enabled = config.get("memory.mem0.enabled", None)
            if configured_enabled is not None:
                enabled = _bool_value(configured_enabled)
        user_id = user_id or str(config.get("memory.mem0.user_id", "") or "")
        search_limit = search_limit or config.get("memory.mem0.search_limit", None)
        context_char_limit = context_char_limit or config.get("memory.mem0.context_char_limit", None)
        if auto_store_turns is None:
            configured_auto_store = config.get("memory.mem0.auto_store_turns", None)
            if configured_auto_store is not None:
                auto_store_turns = _bool_value(configured_auto_store)

    # With an API key present, Mem0 is enabled unless explicitly disabled.
    if enabled is None:
        enabled = bool(api_key)

    return Mem0MemoryConfig(
        enabled=bool(enabled and api_key),
        api_key=api_key,
        user_id=_clean_user_id(user_id or "tommy"),
        search_limit=_int_value(search_limit, default=5, min_value=1, max_value=10),
        context_char_limit=_int_value(context_char_limit, default=1200, min_value=200, max_value=4000),
        auto_store_turns=bool(auto_store_turns),
    )


class Mem0Memory:
    def __init__(
        self,
        config: Optional[Mem0MemoryConfig] = None,
        client_factory: Optional[Callable[[str], Any]] = None,
    ):
        self.config = config or get_mem0_config()
        self._client_factory = client_factory
        self._client = None
        self._client_error_logged = False

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def _get_client(self):
        if not self.config.enabled:
            return None
        if self._client is not None:
            return self._client
        try:
            if self._client_factory is not None:
                self._client = self._client_factory(self.config.api_key)
            else:
                from mem0 import MemoryClient

                self._client = MemoryClient(api_key=self.config.api_key)
            logger.info("[MEM0] client_ready user_id=%s", self.config.user_id)
            return self._client
        except Exception as exc:
            if not self._client_error_logged:
                logger.warning("[MEM0] client unavailable: %s", exc)
                self._client_error_logged = True
            return None

    def _user_filter(self) -> dict[str, str]:
        return {"user_id": self.config.user_id}

    def remember_text(self, content: str, metadata: Optional[dict[str, Any]] = None) -> bool:
        content = (content or "").strip()
        if not content or not self.config.enabled:
            return False
        client = self._get_client()
        if client is None:
            return False
        try:
            client.add(
                [{"role": "user", "content": content}],
                user_id=self.config.user_id,
                metadata=metadata or {},
            )
            logger.info("[MEM0] memory_add_queued")
            return True
        except Exception as exc:
            logger.warning("[MEM0] add failed: %s", exc)
            return False

    def remember_fact(
        self,
        category: str,
        subject: str,
        relation: str,
        value: str,
        source: str = "argo",
    ) -> bool:
        subject = (subject or "").strip()
        relation = (relation or "is").strip()
        value = (value or "").strip()
        if not subject or not value:
            return False
        text = f"Remember this about Tommy and ARGO: {subject} {relation} {value}."
        return self.remember_text(
            text,
            metadata={
                "source": source,
                "category": category or "general",
                "subject": subject,
                "relation": relation,
                "kind": "fact",
            },
        )

    def remember_turn(
        self,
        user_text: str,
        assistant_text: str,
        intent: str = "",
        interaction_id: str = "",
    ) -> bool:
        if not self.config.auto_store_turns:
            return False
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if not user_text or not assistant_text:
            return False
        return self.remember_text(
            f"User said: {user_text}\nARGO replied: {assistant_text}",
            metadata={
                "source": "conversation_turn",
                "intent": intent or "",
                "interaction_id": interaction_id or "",
                "kind": "turn",
            },
        )

    def search(self, query: str, limit: Optional[int] = None) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query or not self.config.enabled:
            return []
        client = self._get_client()
        if client is None:
            return []
        top_k = _int_value(limit or self.config.search_limit, self.config.search_limit)
        try:
            payload = client.search(query, filters=self._user_filter(), top_k=top_k)
        except Exception as exc:
            logger.warning("[MEM0] search failed: %s", exc)
            return []
        return _extract_result_items(payload)[:top_k]

    def format_context(self, query: str) -> str:
        items = self.search(query, limit=self.config.search_limit)
        lines: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = _memory_text(item)
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            lines.append(f"- {text[:300]}")
        if not lines:
            return ""
        block = "MEM0 LONG-TERM MEMORY:\n" + "\n".join(lines)
        return block[: self.config.context_char_limit]

    def delete_matching(self, query: str, limit: int = 10) -> int:
        if not self.config.enabled:
            return 0
        client = self._get_client()
        if client is None:
            return 0
        deleted = 0
        for item in self.search(query, limit=limit):
            memory_id = _memory_id(item)
            if not memory_id:
                continue
            try:
                client.delete(memory_id=memory_id)
                deleted += 1
            except Exception as exc:
                logger.warning("[MEM0] delete failed id=%s: %s", memory_id, exc)
        if deleted:
            logger.info("[MEM0] delete_matching count=%s", deleted)
        return deleted

    def clear_user(self) -> bool:
        if not self.config.enabled:
            return False
        client = self._get_client()
        if client is None:
            return False
        try:
            client.delete_all(user_id=self.config.user_id)
            logger.info("[MEM0] clear_user user_id=%s", self.config.user_id)
            return True
        except Exception as exc:
            logger.warning("[MEM0] clear user failed: %s", exc)
            return False


_mem0_memory_instance: Optional[Mem0Memory] = None


def get_mem0_memory() -> Mem0Memory:
    global _mem0_memory_instance
    if _mem0_memory_instance is None:
        _mem0_memory_instance = Mem0Memory()
    return _mem0_memory_instance


def reset_mem0_memory_for_tests() -> None:
    global _mem0_memory_instance
    _mem0_memory_instance = None
