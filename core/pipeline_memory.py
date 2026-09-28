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
        text = user_text.strip()
        original_lower = text.lower()
        lower = original_lower
        
        # Check for IMPLICIT identity statements (no trigger word required)
        # These are direct personal statements like "My name is Tommy"
        implicit_name = re.search(r"^my name is\s+([a-zA-Z][a-zA-Z\s'-]*)\.?$", lower)
        if implicit_name:
            name_value = implicit_name.group(1).strip().title()
            return {
                "type": "FACT",
                "key": "user.name",
                "value": name_value,
                "display": f"My name is {name_value}",
                "implicit": True,  # Flag for softer acknowledgment
            }
        
        implicit_call_me = re.search(r"^call me\s+([a-zA-Z][a-zA-Z\s'-]*)\.?$", lower)
        if implicit_call_me:
            name_value = implicit_call_me.group(1).strip().title()
            return {
                "type": "FACT",
                "key": "user.name",
                "value": name_value,
                "display": f"Call me {name_value}",
                "implicit": True,
            }

        implicit_preference = re.search(
            r"^i\s+(?:prefer|like)\s+(.+?)(?:\.|!|\?|$)",
            lower,
        )
        if implicit_preference:
            preference_value = implicit_preference.group(1).strip(" ,.-")
            if preference_value and 2 <= len(preference_value) <= 180:
                return {
                    "type": "PREFERENCE",
                    "key": "user.preference",
                    "value": preference_value,
                    "display": f"I prefer {preference_value}",
                    "implicit": True,
                }
        
        # Check for EXPLICIT memory writes (require trigger word)
        match = re.search(r"\b(remember that|remember this|remember|save this|don't forget|dont forget|store this|add this to memory)\b", lower)
        if not match:
            return None

        text = text[match.start():]
        lower = text.lower()

        if re.search(r"\bremember\s+everything\b", lower) or re.search(r"\bfrom now on\b", lower) and "remember" in lower and "everything" in lower:
            return {"reject": "bulk"}

        mem_type = "FACT"
        if re.search(r"\b(project|this project)\b", original_lower):
            mem_type = "PROJECT"
        if re.search(r"\b(preference|prefer)\b", original_lower):
            mem_type = "PREFERENCE"

        remainder = re.sub(r"^(please\s+)?(remember|save this|from now on)\b", "", text, flags=re.IGNORECASE).strip(" :,-")
        if not remainder:
            return {"type": mem_type, "key": None, "value": None}

        if mem_type == "EPHEMERAL":
            remainder = re.sub(r"^(for\s+this\s+session|this\s+session)\b", "", remainder, flags=re.IGNORECASE).strip(" :,-")

        like_match = re.search(r"^that\s+i\s+(like|love)\s+(.+)$", remainder, flags=re.IGNORECASE)
        if like_match:
            return {
                "type": mem_type,
                "key": "user.likes",
                "value": like_match.group(2).strip(),
                "display": f"I {like_match.group(1)} {like_match.group(2).strip()}",
            }

        call_match = re.search(r"\bcall me\s+(.+)$", remainder, flags=re.IGNORECASE)
        if call_match:
            return {
                "type": mem_type,
                "key": "user.name",
                "value": call_match.group(1).strip(),
                "display": f"My name is {call_match.group(1).strip()}",
            }

        name_match = re.search(r"\bmy name is\s+(.+)$", remainder, flags=re.IGNORECASE)
        if name_match:
            return {
                "type": mem_type,
                "key": "user.name",
                "value": name_match.group(1).strip(),
                "display": f"My name is {name_match.group(1).strip()}",
            }

        if ":" in remainder:
            key, value = remainder.split(":", 1)
            return {
                "type": mem_type,
                "key": key.strip(" .,!?:;"),
                "value": value.strip(),
                "display": remainder.strip(),
            }

        if " is " in remainder:
            key, value = remainder.split(" is ", 1)
            return {
                "type": mem_type,
                "key": key.strip(" .,!?:;"),
                "value": value.strip(),
                "display": remainder.strip(),
            }

        return {"type": mem_type, "key": None, "value": remainder.strip(), "display": remainder.strip()}

    def _handle_memory_command(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
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
