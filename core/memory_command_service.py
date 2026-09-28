"""Stateful execution of explicit memory commands."""

from __future__ import annotations

import re
from typing import Any, Protocol


class MemoryCommandHost(Protocol):
    logger: Any
    stop_signal: Any
    _memory_store: Any
    _brain: Any
    _ephemeral_memory: dict[str, Any]
    _last_stt_metrics: dict[str, Any] | None
    _pending_memory_write: dict[str, Any] | None

    def broadcast(self, event: str, payload: Any) -> Any: ...
    def speak(self, text: str, **kwargs: Any) -> Any: ...
    def _sanitize_tts_text(self, text: str, **kwargs: Any) -> str: ...
    def _get_project_namespace(self) -> str: ...
    def _clear_mem0_user(self, interaction_id: str) -> bool: ...
    def _delete_mem0_matching(self, query: str, interaction_id: str) -> int: ...
    def _store_mem0_fact(self, *args: Any, **kwargs: Any) -> bool: ...
    def _parse_memory_write(self, user_text: str) -> dict[str, Any] | None: ...
    def _is_sensitive_memory(self, text: str) -> bool: ...
    def _evaluate_gates(self, *args: Any, **kwargs: Any) -> tuple[bool, str]: ...


class MemoryCommandService:
    """Execute memory commands against a narrowly declared pipeline host."""

    def __init__(self, host: MemoryCommandHost):
        self._host = host

    @property
    def logger(self) -> Any:
        return self._host.logger

    @property
    def stop_signal(self) -> Any:
        return self._host.stop_signal

    @property
    def _memory_store(self) -> Any:
        return self._host._memory_store

    @property
    def _brain(self) -> Any:
        return self._host._brain

    @property
    def _ephemeral_memory(self) -> dict[str, Any]:
        return self._host._ephemeral_memory

    @property
    def _last_stt_metrics(self) -> dict[str, Any] | None:
        return self._host._last_stt_metrics

    @property
    def _pending_memory_write(self) -> dict[str, Any] | None:
        return self._host._pending_memory_write

    @_pending_memory_write.setter
    def _pending_memory_write(self, value: dict[str, Any] | None) -> None:
        self._host._pending_memory_write = value

    def broadcast(self, event: str, payload: Any) -> Any:
        return self._host.broadcast(event, payload)

    def speak(self, text: str, **kwargs: Any) -> Any:
        return self._host.speak(text, **kwargs)

    def _sanitize_tts_text(self, text: str, **kwargs: Any) -> str:
        return self._host._sanitize_tts_text(text, **kwargs)

    def _get_project_namespace(self) -> str:
        return self._host._get_project_namespace()

    def _clear_mem0_user(self, interaction_id: str) -> bool:
        return self._host._clear_mem0_user(interaction_id)

    def _delete_mem0_matching(self, query: str, interaction_id: str) -> int:
        return self._host._delete_mem0_matching(query, interaction_id)

    def _store_mem0_fact(self, *args: Any, **kwargs: Any) -> bool:
        return self._host._store_mem0_fact(*args, **kwargs)

    def _parse_memory_write(self, user_text: str) -> dict[str, Any] | None:
        return self._host._parse_memory_write(user_text)

    def _is_sensitive_memory(self, text: str) -> bool:
        return self._host._is_sensitive_memory(text)

    def _evaluate_gates(self, *args: Any, **kwargs: Any) -> tuple[bool, str]:
        return self._host._evaluate_gates(*args, **kwargs)

    def handle(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        lower = user_text.lower().strip()
        project_ns = self._get_project_namespace()

        if self._pending_memory_write is not None:
            confirm_terms = {"yes", "correct", "confirm", "that's right", "thats right"}
            if lower in confirm_terms:
                pending = self._pending_memory_write
                self._pending_memory_write = None
                mem_type = pending.get("type") or "FACT"
                key = pending.get("key")
                value = pending.get("value")
                namespace = pending.get("namespace")
                if not key or not value:
                    response = "Memory write canceled."
                    self.logger.info("[MEMORY] memory_write_canceled")
                else:
                    try:
                        self._memory_store.add_memory(mem_type, key, value, source="explicit_user_request", namespace=namespace)
                        self._store_mem0_fact(
                            mem_type.lower(),
                            key,
                            "is",
                            value,
                            "explicit_user_request",
                            interaction_id,
                        )
                        response = "Memory stored."
                        self.logger.info(f"[MEMORY] memory_write_confirmed memory_write_type={mem_type}")
                    except Exception as e:
                        self.logger.warning(f"[MEMORY] Write failed: {e}")
                        response = "Memory store unavailable."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True

            self._pending_memory_write = None
            self.logger.info("[MEMORY] memory_write_canceled")
            response = "Memory write canceled."
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        if re.search(r"\b(clear|wipe)\s+all\s+memory\b", lower):
            if "confirm" not in lower:
                response = "Confirm by saying: confirm clear all memory."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True
            try:
                count = self._memory_store.clear_all()
            except Exception as e:
                self.logger.warning(f"[MEMORY] Clear all failed: {e}")
                response = "Memory store unavailable."
            else:
                self._ephemeral_memory.clear()
                self._clear_mem0_user(interaction_id)
                response = f"Cleared all memory ({count} records)."
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        if re.search(r"\b(list|show|display)\s+memory\b", lower) or re.search(r"\bwhat do you remember\b", lower):
            try:
                facts = self._memory_store.list_memory("FACT")
                projects = self._memory_store.list_memory("PROJECT", namespace=project_ns)
                preferences = self._memory_store.list_memory("PREFERENCE")
            except Exception as e:
                self.logger.warning(f"[MEMORY] List failed: {e}")
                response = "Memory store unavailable."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True
            ephemerals = self._ephemeral_memory
            if not facts and not projects and not ephemerals and not preferences:
                response = "No memory stored."
            else:
                parts = []
                if facts:
                    parts.append("FACT: " + "; ".join([f"{m.key} = {m.value}" for m in facts[:20]]))
                if projects:
                    parts.append("PROJECT: " + "; ".join([f"{m.key} = {m.value}" for m in projects[:20]]))
                if preferences:
                    parts.append("PREFERENCE: " + "; ".join([f"{m.key} = {m.value}" for m in preferences[:20]]))
                if ephemerals:
                    parts.append("EPHEMERAL: " + "; ".join([f"{k} = {v}" for k, v in list(ephemerals.items())[:20]]))
                response = "Memory: " + " | ".join(parts)
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        if re.search(r"\bmemory\s+stats\b", lower) or re.search(r"\bstats\s+memory\b", lower):
            try:
                fact_count = len(self._memory_store.list_memory("FACT"))
                project_count = len(self._memory_store.list_memory("PROJECT", namespace=project_ns))
                pref_count = len(self._memory_store.list_memory("PREFERENCE"))
            except Exception as e:
                self.logger.warning(f"[MEMORY] Stats failed: {e}")
                response = "Memory store unavailable."
            else:
                response = f"Memory stats: FACT={fact_count}, PROJECT({project_ns})={project_count}, PREFERENCE={pref_count}, EPHEMERAL={len(self._ephemeral_memory)}."
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        explain_match = re.search(r"\bexplain\s+memory\s+(?P<key>.+)$", lower)
        if explain_match:
            key = explain_match.group("key").strip().strip(" .,!?:;")
            if not key:
                response = "Tell me which memory key to explain."
            else:
                try:
                    facts = self._memory_store.get_by_key(key, mem_type="FACT")
                    projects = self._memory_store.get_by_key(key, mem_type="PROJECT", namespace=project_ns)
                    prefs = self._memory_store.get_by_key(key, mem_type="PREFERENCE")
                except Exception as e:
                    self.logger.warning(f"[MEMORY] Explain failed: {e}")
                    response = "Memory store unavailable."
                else:
                    parts = []
                    for m in facts:
                        parts.append(f"FACT {m.key} = {m.value} (source={m.source}, ts={m.timestamp})")
                    for m in projects:
                        parts.append(f"PROJECT[{m.namespace}] {m.key} = {m.value} (source={m.source}, ts={m.timestamp})")
                    for m in prefs:
                        parts.append(f"PREFERENCE {m.key} = {m.value} (source={m.source}, ts={m.timestamp})")
                    if key in self._ephemeral_memory:
                        parts.append(f"EPHEMERAL {key} = {self._ephemeral_memory[key]}")
                    response = " | ".join(parts) if parts else f"No memory found for '{key}'."
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        project_match = re.search(r"\bclear\s+memory\s+for\s+(.+?)\s+project\b", lower)
        if re.search(r"\b(clear|wipe)\s+project\s+memory\b", lower) or project_match:
            namespace = project_ns
            if project_match:
                namespace = project_match.group(1).strip().lower()
            try:
                count = self._memory_store.clear_project(namespace)
            except Exception as e:
                self.logger.warning(f"[MEMORY] Clear project failed: {e}")
                response = "Memory store unavailable."
            else:
                response = f"Cleared project memory ({count} records) for {namespace}."
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        delete_match = re.search(r"\b(delete|forget|remove)\s+memory\s+(?P<key>.+)$", lower)
        if not delete_match:
            delete_match = re.search(r"\b(forget|delete|remove)\s+(?P<key>.+)$", lower)
        if delete_match:
            key = delete_match.group("key").strip().strip(" .,!?:;")
            if not key:
                response = "Tell me which memory key to delete."
            else:
                removed = 0
                if key in self._ephemeral_memory:
                    del self._ephemeral_memory[key]
                    removed += 1
                try:
                    removed += self._memory_store.delete_memory(key)
                except Exception as e:
                    self.logger.warning(f"[MEMORY] Delete failed: {e}")
                    response = "Memory store unavailable."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response)
                        tts_override = (overrides or {}).get("suppress_tts", False)
                        if tts_override:
                            self.logger.info("[TTS] Suppressed for next interaction override")
                        elif tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    return True
                removed += self._delete_mem0_matching(key, interaction_id)
                response = f"Deleted memory for '{key}'." if removed else f"No memory found for '{key}'."
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        write = self._parse_memory_write(user_text)
        if write is not None:
            # ── Brain memory write path ──
            brain_cmd = self._brain.parse_memory_command(user_text)
            if brain_cmd:
                action = brain_cmd.get("action")
                
                if action == "recall_all":
                    response = self._brain.format_all_facts_for_speech()
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response, enforce_confidence=False, deterministic=True)
                        if tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    return True
                
                if action == "recall_subject":
                    subject = brain_cmd.get("subject", "")
                    facts = self._brain.retrieve_relevant_facts(subject, limit=5)
                    if facts:
                        lines = [f"{f.subject} {f.relation} {f.value}" for f in facts]
                        response = "Here's what I know. " + ". ".join(lines) + "."
                    else:
                        response = f"I don't have anything stored about {subject}."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response, enforce_confidence=False, deterministic=True)
                        if tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    return True
                
                if action == "forget":
                    subject = brain_cmd.get("subject", "")
                    # Try to delete any fact with this subject
                    all_facts = self._brain.get_all_facts()
                    deleted = False
                    for f in all_facts:
                        if subject.lower() in f.subject.lower() or subject.lower() in f.value.lower():
                            self._brain.delete_fact(f.subject, f.relation)
                            deleted = True
                    deleted = bool(self._delete_mem0_matching(subject, interaction_id)) or deleted
                    response = f"Done, I've forgotten about {subject}." if deleted else f"I didn't have anything stored about {subject}."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response, enforce_confidence=False, deterministic=True)
                        if tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    return True
                
                if action == "store":
                    category = brain_cmd.get("category", "general")
                    subject = brain_cmd.get("subject", "")
                    relation = brain_cmd.get("relation", "is")
                    value = brain_cmd.get("value", "")
                    if subject and value:
                        if self._is_sensitive_memory(value) or self._is_sensitive_memory(subject):
                            response = "I can't store sensitive data."
                        else:
                            self._brain.store_fact(category, subject, relation, value)
                            # Also store in legacy memory_store for backward compat
                            try:
                                self._memory_store.add_memory("FACT", f"{subject}.{relation}", value, source="brain")
                            except Exception:
                                pass
                            self._store_mem0_fact(category, subject, relation, value, "brain", interaction_id)
                            display = f"{subject} {relation} {value}"
                            response = f"Got it. I'll remember that."
                            self.logger.info(f"[BRAIN] Stored: {display}")
                    else:
                        response = "What should I remember? Tell me something specific."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response, enforce_confidence=False, deterministic=True)
                        if tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    return True
            
            # ── Legacy memory write path (fallback) ──
            stt_conf = 0.0
            try:
                stt_conf = float((self._last_stt_metrics or {}).get("confidence", 0.0))
            except Exception:
                stt_conf = 0.0
            if write.get("reject") == "bulk":
                response = "I can't store everything. Tell me one specific fact to remember."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True
            mem_type = write.get("type") or "FACT"
            key = write.get("key")
            value = write.get("value")
            display = write.get("display") or value
            if not key or not value:
                response = "What should I remember? Provide a key and value."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True

            if self._is_sensitive_memory(value) or self._is_sensitive_memory(key):
                response = "I can't store sensitive data."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True

            if stt_conf < 0.35:
                response = "I won’t store that unless you ask me to remember it clearly."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True

            allowed, reason = self._evaluate_gates("memory_write", "memory", interaction_id)
            if not allowed:
                response = f"Memory write blocked by policy ({reason})."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True

            namespace = project_ns if mem_type == "PROJECT" else None
            
            # IMPLICIT WRITES: Direct personal statements like "My name is Tommy"
            # Store immediately with natural acknowledgment (no confirmation needed)
            if write.get("implicit"):
                stored = False
                try:
                    self._memory_store.add_memory(mem_type, key, value, source="implicit", namespace=namespace)
                    self._store_mem0_fact(mem_type.lower(), key, "is", value, "implicit", interaction_id)
                    self.logger.info(f"[MEMORY] memory_write_implicit key={key} value={value}")
                    stored = True
                except Exception as e:
                    self.logger.warning(f"[MEMORY] Implicit write failed: {e}")

                # Telling ARGO your name is addressed TO it, so it answers.
                # Mentioning that you like jazz is conversation: remember it,
                # then talk about it. Answering "Noted." and closing the turn
                # is how a memory feature eats a conversation. Returning False
                # hands the turn back to the normal reply path, fact saved.
                if key != "user.name":
                    self.logger.info(
                        "[MEMORY] implicit_fact_captured_conversation_continues key=%s stored=%s",
                        key, stored,
                    )
                    return False

                response = f"Got it, {value}." if stored else "I couldn't save that."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response, enforce_confidence=False, deterministic=True)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                return True
            
            # EXPLICIT WRITES: Require confirmation
            self._pending_memory_write = {
                "type": mem_type,
                "key": key,
                "value": value,
                "namespace": namespace,
                "display": display,
            }
            response = f"You want me to remember: '{display}'. Is that correct?"
            self.logger.info(f"[MEMORY] memory_write_proposed memory_write_type={mem_type}")
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            return True

        return False

