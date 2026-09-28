"""Memory behavior mixed into :class:`core.pipeline.ArgoPipeline`.

This module owns conversation-ledger recall, explicit and implicit memory
commands, durable turn storage, and the optional Mem0 bridge.  The mixin keeps
the established ArgoPipeline method surface while removing memory policy from
the STT/LLM/TTS orchestrator module.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from core.memory_command_parser import parse_memory_write
from core.memory_command_service import MemoryCommandService


class PipelineMemoryMixin:
    def _append_convo_ledger(self, speaker: str, text: str) -> None:
        if not text:
            return
        self._conversation_ledger.append({
            "speaker": speaker,
            "text": text,
            "timestamp": time.monotonic(),
        })
        self.logger.info(f"[CONVO] convo_ledger_size={len(self._conversation_ledger)}")

    def _get_previous_user_entry(self) -> str | None:
        if len(self._conversation_ledger) < 2:
            return None
        for entry in reversed(list(self._conversation_ledger)[:-1]):
            if entry.get("speaker") == "user":
                return entry.get("text")
        return None

    def _is_convo_recall_request(self, user_text: str) -> bool:
        text = (user_text or "").lower()
        phrases = {
            "previous question",
            "last question",
            "last thing i asked",
            "what did i ask you",
            "what was the previous question",
            "what did i just ask",
            "what did we just talk about",
            "before that",
        }
        return any(p in text for p in phrases)

    def _handle_convo_recall(self) -> str:
        previous = self._get_previous_user_entry()
        if not previous:
            self.logger.info("[CONVO] convo_recall_hit=false convo_recall_source=none")
            return "This is the first question in this session."
        self.logger.info("[CONVO] convo_recall_hit=true convo_recall_source=ledger")
        return f"You asked: '{previous}'"

    def _find_color_statement(self) -> str | None:
        color_pattern = re.compile(r"\b\w+\s+(is|are)\s+(yellow|green|red|blue|orange|purple|black|white|brown|pink)\b", re.IGNORECASE)
        for entry in reversed(self._conversation_ledger):
            text = entry.get("text") or ""
            if color_pattern.search(text):
                return text
        return None

    def _handle_contextual_followup(self, user_text: str) -> str | None:
        text = (user_text or "").lower()
        if "what color" in text and "fruit" in text:
            statement = self._find_color_statement()
            if statement:
                self.logger.info("[CONVO] convo_recall_hit=true convo_recall_source=ledger")
                return f"We said: '{statement}'"
            self.logger.info("[CONVO] convo_recall_hit=false convo_recall_source=none")
            return "We talked about fruit, but no specific fruit or color was mentioned."
        return None

    def _get_project_namespace(self) -> str:
        try:
            if self._config is not None:
                name = self._config.get("project.name")
                if name:
                    return str(name)
        except Exception:
            pass
        try:
            return Path.cwd().name
        except Exception:
            return "default"

    def _is_sensitive_memory(self, text: str) -> bool:
        if not text:
            return False
        patterns = [
            r"password",
            r"api\s*key",
            r"secret",
            r"token",
            r"private\s*key",
            r"-----BEGIN",
        ]
        return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)

    def _get_memory_context(self, interaction_id: str, user_text: str = "") -> str:
        """Pull smart memory context from brain (3-layer: facts + state + last exchange)."""
        blocks = []
        try:
            brain_context = self._brain.get_prompt_context(user_text)
            if brain_context:
                blocks.append(brain_context)
        except Exception as e:
            self.logger.warning(f"[BRAIN] Context load failed: {e}")
            self._record_timeline("MEMORY_CONTEXT_ERROR", stage="memory", interaction_id=interaction_id)
        try:
            mem0_memory = getattr(self, "_mem0_memory", None)
            if mem0_memory and getattr(mem0_memory, "enabled", False) and user_text:
                mem0_context = mem0_memory.format_context(user_text)
                if mem0_context:
                    blocks.append(mem0_context)
        except Exception as e:
            self.logger.warning(f"[MEM0] Context load failed: {e}")
            self._record_timeline("MEM0_CONTEXT_ERROR", stage="memory", interaction_id=interaction_id)
        try:
            search_turns = getattr(self._memory_store, "search_turns", None)
            if search_turns and user_text:
                turns = search_turns(user_text, limit=3)
                if turns:
                    lines = ["DURABLE CONVERSATION TURNS:"]
                    for turn in turns:
                        lines.append(f"User: {turn.user_text}")
                        lines.append(f"ARGO: {turn.assistant_text}")
                    blocks.append("\n".join(lines))
        except Exception as e:
            self.logger.warning(f"[MEMORY] Durable turn recall failed: {e}")
            self._record_timeline("DURABLE_MEMORY_CONTEXT_ERROR", stage="memory", interaction_id=interaction_id)
        return "\n\n".join(blocks)

    def _store_mem0_fact(
        self,
        category: str,
        subject: str,
        relation: str,
        value: str,
        source: str,
        interaction_id: str,
    ) -> bool:
        """Store a selected durable fact in Mem0 when the optional layer is enabled."""
        mem0_memory = getattr(self, "_mem0_memory", None)
        if not mem0_memory or not getattr(mem0_memory, "enabled", False):
            return False
        if self._is_sensitive_memory(subject) or self._is_sensitive_memory(value):
            return False
        try:
            stored = mem0_memory.remember_fact(category, subject, relation, value, source=source)
            if stored:
                self.logger.info("[MEM0] fact_stored category=%s source=%s", category, source)
            return bool(stored)
        except Exception as e:
            self.logger.warning(f"[MEM0] Fact store failed: {e}")
            self._record_timeline("MEM0_STORE_ERROR", stage="memory", interaction_id=interaction_id)
            return False

    def _delete_mem0_matching(self, query: str, interaction_id: str) -> int:
        mem0_memory = getattr(self, "_mem0_memory", None)
        if not query or not mem0_memory or not getattr(mem0_memory, "enabled", False):
            return 0
        try:
            removed = int(mem0_memory.delete_matching(query) or 0)
            if removed:
                self.logger.info("[MEM0] memories_deleted count=%s", removed)
            return removed
        except Exception as e:
            self.logger.warning(f"[MEM0] Delete failed: {e}")
            self._record_timeline("MEM0_DELETE_ERROR", stage="memory", interaction_id=interaction_id)
            return 0

    def _clear_mem0_user(self, interaction_id: str) -> bool:
        mem0_memory = getattr(self, "_mem0_memory", None)
        if not mem0_memory or not getattr(mem0_memory, "enabled", False):
            return False
        try:
            cleared = bool(mem0_memory.clear_user())
            if cleared:
                self.logger.info("[MEM0] user_memory_cleared")
            return cleared
        except Exception as e:
            self.logger.warning(f"[MEM0] Clear failed: {e}")
            self._record_timeline("MEM0_CLEAR_ERROR", stage="memory", interaction_id=interaction_id)
            return False

    def _store_durable_turn(self, user_text: str, assistant_text: str, intent: str, interaction_id: str) -> None:
        """Store a completed conversational turn if the configured backend supports it."""
        try:
            add_turn = getattr(self._memory_store, "add_turn", None)
            if add_turn:
                turn_id = add_turn(
                    user_text=(user_text or "")[:4000],
                    assistant_text=(assistant_text or "")[:4000],
                    source="llm",
                    intent=intent or None,
                    metadata={"interaction_id": interaction_id},
                )
                if turn_id and turn_id > 0:
                    self.logger.info(f"[MEMORY] durable_turn_stored id={turn_id}")
        except Exception as e:
            self.logger.warning(f"[MEMORY] Durable turn store failed: {e}")
            self._record_timeline("DURABLE_MEMORY_STORE_ERROR", stage="memory", interaction_id=interaction_id)
        try:
            mem0_memory = getattr(self, "_mem0_memory", None)
            if mem0_memory and getattr(mem0_memory, "enabled", False):
                mem0_memory.remember_turn(user_text, assistant_text, intent=intent, interaction_id=interaction_id)
        except Exception as e:
            self.logger.warning(f"[MEM0] Turn store failed: {e}")
            self._record_timeline("MEM0_TURN_STORE_ERROR", stage="memory", interaction_id=interaction_id)

    def _parse_memory_write(self, user_text: str) -> dict | None:
        """Compatibility facade for deterministic memory-write parsing."""
        return parse_memory_write(user_text)

    def _handle_memory_command(
        self,
        user_text: str,
        interaction_id: str,
        replay_mode: bool,
        overrides: dict | None,
    ) -> bool:
        """Compatibility facade for the composed memory command service."""
        service = getattr(self, "_memory_commands", None)
        if service is None:
            service = MemoryCommandService(self)
            self._memory_commands = service
        return service.handle(user_text, interaction_id, replay_mode, overrides)
