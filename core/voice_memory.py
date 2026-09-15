"""Durable memory for the Smooth Voice path.

ARGO already had memory - facts, preferences and a searchable history of every
conversation turn - but all of it was wired to the classic pipeline. When Smooth
Voice became the canonical path it inherited her voice and none of her memory,
which is why she meets Tommy fresh every session. This module is the bridge.

Two deliberate choices:

Durable facts are injected at session start; past conversations are NOT. Facts
are a handful of short lines and they change what she says. Dumping conversation
history into the instructions would blow the context and drown the personality
directives that took a rewrite to get working. History is reached by search,
when he actually asks for it.

Nothing here may block or break the live audio loop. Every store call is
wrapped, writes happen on a background thread, and any failure degrades to a
voice session with no memory rather than no voice session.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("ARGO.VoiceMemory")

# A spoken fragment shorter than this is a cough, not a turn worth keeping.
MIN_TURN_CHARS = 2
MAX_TURN_CHARS = 4000

# Facts are injected into every session's instructions, so this stays small.
MAX_FACTS = 12
MAX_FACT_CHARS = 90

TURN_SOURCE = "smooth_voice"


def _clean(text: Any) -> str:
    return (str(text or "")).strip()


def _store():
    """The durable store, or None if it cannot be reached."""
    try:
        from core.memory_store import get_memory_store

        return get_memory_store()
    except Exception:
        logger.warning("[VoiceMemory] durable store unavailable", exc_info=True)
        return None


def _mem0():
    """The optional Mem0 layer, or None when it is disabled or missing."""
    try:
        from core.mem0_memory import get_mem0_memory

        layer = get_mem0_memory()
        return layer if getattr(layer, "enabled", False) else None
    except Exception:
        logger.debug("[VoiceMemory] mem0 unavailable", exc_info=True)
        return None


@dataclass
class VoiceMemory:
    """Remembers a live voice session, and what came before it."""

    session_id: str = ""
    enabled: bool = True
    _pending_user: Optional[str] = None
    _last_pair: tuple[str, str] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _writes: int = 0
    _failures: int = 0

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def note(self, role: str, text: str) -> None:
        """Record one conversation item as it is committed by the session.

        The realtime API emits the user's item and the agent's item separately,
        so a turn is only durable once both halves have arrived.
        """
        if not self.enabled:
            return
        body = _clean(text)
        if len(body) < MIN_TURN_CHARS:
            return
        role_name = _clean(role).lower()

        with self._lock:
            if role_name.startswith("user"):
                # Two user items in a row means he spoke twice without a reply.
                # Keep the newer one; the older was interrupted or ignored.
                self._pending_user = body[:MAX_TURN_CHARS]
                return

            if not role_name.startswith("assistant"):
                return

            user_text = self._pending_user
            self._pending_user = None
            if not user_text:
                # She spoke unprompted - a greeting, or a continuation. There is
                # no exchange to store.
                return

            pair = (user_text, body[:MAX_TURN_CHARS])
            if pair == self._last_pair:
                # The same item can arrive twice; do not write it twice.
                return
            self._last_pair = pair

        self._persist_async(*pair)

    def _persist_async(self, user_text: str, assistant_text: str) -> None:
        thread = threading.Thread(
            target=self._persist,
            args=(user_text, assistant_text),
            name="voice-memory-write",
            daemon=True,
        )
        thread.start()

    def _persist(self, user_text: str, assistant_text: str) -> None:
        store = _store()
        if store is not None:
            try:
                add_turn = getattr(store, "add_turn", None)
                if add_turn:
                    turn_id = add_turn(
                        user_text=user_text,
                        assistant_text=assistant_text,
                        source=TURN_SOURCE,
                        intent=None,
                        metadata={"session_id": self.session_id} if self.session_id else None,
                    )
                    if turn_id and int(turn_id) > 0:
                        self._writes += 1
                        logger.info("[VoiceMemory] turn_stored id=%s", turn_id)
            except Exception:
                self._failures += 1
                logger.warning("[VoiceMemory] durable turn store failed", exc_info=True)

        layer = _mem0()
        if layer is not None:
            try:
                layer.remember_turn(
                    user_text, assistant_text, intent="", interaction_id=self.session_id or ""
                )
            except Exception:
                logger.warning("[VoiceMemory] mem0 turn store failed", exc_info=True)

    def flush(self) -> None:
        """Drop any half-turn left over when the session ends."""
        with self._lock:
            self._pending_user = None

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def opening_context(self) -> str:
        """Durable facts about Tommy, as a short block for session instructions.

        Returns an empty string when there is nothing worth saying, so callers
        can append unconditionally without producing a dangling header.
        """
        if not self.enabled:
            return ""
        store = _store()
        if store is None:
            return ""

        lines: list[str] = []
        seen: set[str] = set()
        for kind in ("FACT", "PREFERENCE"):
            try:
                rows = store.list_memory(kind) or []
            except Exception:
                logger.debug("[VoiceMemory] could not list %s", kind, exc_info=True)
                continue
            for row in rows:
                key = _clean(getattr(row, "key", ""))
                value = _clean(getattr(row, "value", ""))
                if not key or not value:
                    continue
                fact = f"{key}: {value}"[:MAX_FACT_CHARS]
                # The store has accumulated duplicates over time; say each once.
                fingerprint = fact.lower()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                lines.append(fact)
                if len(lines) >= MAX_FACTS:
                    break
            if len(lines) >= MAX_FACTS:
                break

        if not lines:
            return ""
        body = "\n".join(f"- {line}" for line in lines)
        return (
            "WHAT YOU ALREADY KNOW ABOUT HIM:\n"
            f"{body}\n"
            "Use these when they change your answer. Do not recite them back at him."
        )

    def recall(self, query: str, limit: int = 3) -> str:
        """Search past conversations. Returns plain text ARGO can speak from."""
        question = _clean(query)
        if not question:
            return "I need something to look for."
        store = _store()
        if store is None:
            return "I can't reach my memory right now."

        turns = []
        try:
            search = getattr(store, "search_turns", None)
            if search:
                turns = search(question, limit=max(1, min(int(limit), 8))) or []
        except Exception:
            logger.warning("[VoiceMemory] turn search failed", exc_info=True)
            return "Something went wrong searching my memory."

        layer = _mem0()
        extra = ""
        if layer is not None:
            try:
                extra = _clean(layer.format_context(question))
            except Exception:
                logger.debug("[VoiceMemory] mem0 context failed", exc_info=True)

        if not turns and not extra:
            return f"Nothing in my memory about {question}."

        parts: list[str] = []
        if turns:
            parts.append(f"Past conversations about {question}:")
            for turn in turns:
                user_text = _clean(getattr(turn, "user_text", ""))[:300]
                assistant_text = _clean(getattr(turn, "assistant_text", ""))[:300]
                if user_text or assistant_text:
                    parts.append(f"He said: {user_text}\nYou said: {assistant_text}")
        if extra:
            parts.append(extra)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        store = _store()
        return {
            "enabled": self.enabled,
            "session_id": self.session_id,
            "backend": getattr(store, "backend_name", None) if store else None,
            "mem0": _mem0() is not None,
            "turns_written": self._writes,
            "write_failures": self._failures,
            "half_turn_pending": self._pending_user is not None,
        }


def memory_status() -> dict:
    """Safe summary of the durable memory backend, for the UI and logs."""
    store = _store()
    counts: dict[str, int] = {}
    if store is not None:
        for kind in ("FACT", "PREFERENCE", "PROJECT"):
            try:
                counts[kind.lower()] = len(store.list_memory(kind) or [])
            except Exception:
                counts[kind.lower()] = -1
    return {
        "available": store is not None,
        "backend": getattr(store, "backend_name", None) if store else None,
        "mem0_enabled": _mem0() is not None,
        "counts": counts,
    }
