
"""
ARGO Pipeline: STT -> LLM -> TTS

Synchronous, queue-based processing pipeline.
Uses faster-whisper, ollama, and Edge TTS.
"""

# ============================================================================
# 1) IMPORTS
# ============================================================================
import time
import logging
import numpy as np
import threading
import sys
import uuid
import json
import re
from faster_whisper import WhisperModel
import ollama
import subprocess
import shutil
import os
from pathlib import Path

from core.instrumentation import log_event
from core.config import get_runtime_overrides, get_config
from core.intent_parser import RuleBasedIntentParser, IntentType, normalize_system_text, is_system_keyword
from core.music_player import get_music_player
from core.music_status import query_music_status
from core.memory_store import get_memory_store
from core.conversation_buffer import ConversationBuffer
from core.registries import is_capability_enabled, is_permission_allowed, is_module_enabled
from core.runtime_constants import GATES_ORDER, Gate
from system_health import (
    get_system_health,
    get_memory_info,
    get_temperatures,
    get_temperature_health,
    get_disk_info,
    get_system_full_report,
)
from system_profile import get_system_profile, get_gpu_profile

# ============================================================================
# 2) PIPELINE ORCHESTRATOR
# ============================================================================
class ArgoPipeline:
    def __init__(self, audio_manager, websocket_broadcast):
        self.logger = logging.getLogger("ARGO.Pipeline")
        self.audio = audio_manager
        self.broadcast = websocket_broadcast
        self.stop_signal = threading.Event()
        self.is_speaking = False
        self.current_interaction_id = ""
        self.illegal_transition_details = None
        self.timeline_events = []
        self.runtime_overrides = get_runtime_overrides()
        try:
            self._config = get_config()
        except Exception:
            self._config = None
        self._intent_parser = RuleBasedIntentParser()
        self._last_stt_metrics = None
        self._low_conf_notice_given = False
        self._serious_mode_keywords = {
            "help", "urgent", "emergency", "panic", "stuck", "broken", "crash",
            "error", "fail", "failure", "frustrated", "angry", "upset",
            "deadline", "production", "incident", "outage",
        }
        self.llm_enabled = True

        # State machine
        self._state_lock = threading.Lock()
        self.current_state = "IDLE"
        self.illegal_transition = False
        self.ALLOWED_TRANSITIONS = {
            "IDLE": {"LISTENING"},
            "LISTENING": {"TRANSCRIBING"},
            "TRANSCRIBING": {"THINKING", "LISTENING", "IDLE"},
            "THINKING": {"SPEAKING", "IDLE"},
            "SPEAKING": {"LISTENING", "IDLE"},
        }
        
        # Concurrency Lock
        self.processing_lock = threading.Lock()
        
        # Models
        self.stt_model = None
        self.tts_process = None
        self.stt_model_name = "unknown"
        self.llm_model_name = "unknown"
        
        # Default voice (mapped to Edge TTS voices)
        self.voices = {
            "ryan": "en-GB-RyanNeural",
            "libby": "en-GB-LibbyNeural",
            "natasha": "en-AU-NatashaNeural",
            "abeo": "en-NG-AbeoNeural",
        }
        self.current_voice_key = "ryan"
        self._edge_tts = None
        self._memory_store = get_memory_store()
        self._ephemeral_memory = {}
        convo_size = 8
        try:
            if self._config is not None:
                convo_size = int(self._config.get("conversation.buffer_size", 8))
        except Exception:
            convo_size = 8
        self._conversation_buffer = ConversationBuffer(max_turns=convo_size)
        self._stt_prompt_profile = "general"
        self._stt_initial_prompt = ""
        self._stt_min_rms_threshold = 0.005
        self._stt_silence_ratio_threshold = 0.90
        try:
            if self._config is not None:
                self._stt_prompt_profile = str(self._config.get("speech_to_text.prompt_profile", "general"))
                self._stt_min_rms_threshold = float(self._config.get("speech_to_text.min_rms_threshold", 0.005))
                self._stt_silence_ratio_threshold = float(self._config.get("speech_to_text.silence_ratio_threshold", 0.90))
                profiles = self._config.get("speech_to_text.initial_prompt_profiles", {}) or {}
                self._stt_initial_prompt = str(profiles.get(self._stt_prompt_profile, ""))
        except Exception:
            pass

    def set_voice(self, voice_key):
        """Switch the TTS voice model."""
        if voice_key in self.voices:
            self.current_voice_key = voice_key
            if self._edge_tts is not None:
                try:
                    self._edge_tts.voice = self.voices[voice_key]
                except Exception:
                    pass
            self.logger.info(f"Voice switched to {voice_key}: {self.voices[voice_key]}")
            self.broadcast("log", f"System: Voice profile switched to {voice_key.upper()}")
            return True
        return False

    def _sanitize_tts_text(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        cleaned = text
        # Remove system diagnostics from spoken output
        cleaned = re.sub(r"\b(VAD|STT|LLM|TTS|AUDIO|THREAD|DEBUG)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(interaction_id|rms|peak|silence|threshold)\b", "", cleaned, flags=re.IGNORECASE)
        # Strip markdown emphasis and inline code markers
        cleaned = re.sub(r"[`*_#]+", "", cleaned)
        # Convert markdown links: [text](url) -> text
        cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)
        # Remove list bullets
        cleaned = re.sub(r"^\s*[-*•]\s+", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    def warmup(self):
        self.logger.info("Warming up models...")
        self.broadcast("status", "WARMING_UP")
        if self._stt_prompt_profile:
            self.logger.info(f"[STT] Prompt profile: {self._stt_prompt_profile}")
        
        try:
            cache_dir = Path(__file__).resolve().parent.parent / ".hf_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("HF_HOME", str(cache_dir))
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache_dir / "hub"))

            self.stt_model_name = "base.en"
            self.logger.info("Loading Whisper Model: base.en...")
            try:
                self.stt_model = WhisperModel("base.en", device="cuda", compute_type="float16")
            except Exception as cuda_error:
                self.logger.warning(f"STT CUDA init failed, falling back to CPU: {cuda_error}")
                self.stt_model = WhisperModel("base.en", device="cpu", compute_type="int8")
            # Run a dummy transcription to load into VRAM
            self.stt_model.transcribe(np.zeros(16000, dtype='float32'), beam_size=1)
            self.logger.info("STT model warmed up")
        except Exception as e:
            self.logger.error(f"STT Warmup Error: {e}")
        
        if self.llm_enabled:
            try:
                model_name = "qwen:latest"
                if self._config is not None:
                    model_name = self._config.get("llm.model", model_name)
                self.llm_model_name = model_name
                client = ollama.Client(host='http://127.0.0.1:11434')
                client.generate(model=model_name, prompt='hi', stream=False)
                self.logger.info("LLM model warmed up")
            except Exception as e:
                self.logger.warning(f"LLM Warmup Warning: {e}")
        
        self.broadcast("status", "READY")

    def _record_timeline(self, event: str, stage: str, interaction_id: str = ""):
        ts = int(time.monotonic() * 1000)
        self.timeline_events.append({
            "t": ts,
            "id": interaction_id,
            "stage": stage,
            "event": event,
        })
        log_event(event, stage=stage, interaction_id=interaction_id)

    def transition_state(self, new_state: str, interaction_id: str = "", source: str = "audio") -> bool:
        with self._state_lock:
            old_state = self.current_state
            if new_state == old_state:
                return True
            allowed = new_state in self.ALLOWED_TRANSITIONS.get(old_state, set())
            if not allowed:
                self.illegal_transition = True
                payload = {
                    "from": old_state,
                    "to": new_state,
                    "allowed": list(self.ALLOWED_TRANSITIONS.get(old_state, set())),
                    "source": source,
                    "interaction_id": interaction_id,
                }
                self.illegal_transition_details = payload
                self._record_timeline(
                    f"ILLEGAL_TRANSITION {old_state}->{new_state} source={source}",
                    stage="state",
                    interaction_id=interaction_id,
                )
                self.broadcast("illegal_transition", payload)
                self.broadcast("status", "ERROR")
                self.broadcast("log", f"ILLEGAL TRANSITION: {old_state} → {new_state}")
                if self.is_speaking:
                    try:
                        self.stop_signal.set()
                        self.audio.force_release_audio("ILLEGAL_TRANSITION", interaction_id=interaction_id)
                        self.audio.stop_playback()
                    except Exception:
                        pass
                return False
            self.current_state = new_state
            self._record_timeline(
                f"STATE {old_state}->{new_state}",
                stage="state",
                interaction_id=interaction_id,
            )
            self.broadcast("status", new_state)
            return True

    def force_state(self, new_state: str, interaction_id: str = "", source: str = "BARGE_IN"):
        with self._state_lock:
            old_state = self.current_state
            self.current_state = new_state
            self._record_timeline(
                f"STATE {old_state}->{new_state} (forced, source={source})",
                stage="state",
                interaction_id=interaction_id,
            )
            self.broadcast("status", new_state)

    def reset_interaction(self):
        self.stop_signal.set()
        self.is_speaking = False
        self.illegal_transition = False
        self.illegal_transition_details = None
        self.transition_state("LISTENING", source="ui")

    def stop_tts(self) -> None:
        """Force stop Edge TTS playback if active."""
        try:
            if self._edge_tts is not None:
                self._edge_tts.stop_sync()
        except Exception:
            pass

    def _classify_request_type(self, user_text: str, intent) -> str:
        if not user_text or not user_text.strip():
            return "UNKNOWN"
        text = user_text.strip().lower()
        tokens = re.findall(r"\w+", text)
        token_set = set(tokens)

        starts_question = bool(re.match(r"^(what|why|how|when|where|who)\b", text))
        ends_question = text.endswith("?")
        has_question_cue = bool(re.search(r"\b(what|why|how|who|when|where|explain|describe|define|tell|show|what's|whats|why's|hows)\b", text))

        hedging = {"maybe", "might", "could", "would", "should", "perhaps", "possibly", "guess", "think", "can", "could", "would", "should"}
        has_hedge = bool(token_set & hedging) or text.startswith("can you") or text.startswith("could you") or text.startswith("would you")

        action_verbs = {
            "open", "delete", "run", "start", "stop", "enable", "disable",
            "install", "remove", "play", "pause", "resume", "next", "skip",
            "set", "change", "turn", "launch",
        }
        has_action = bool(token_set & action_verbs)

        concept_tokens = {
            "system", "file", "pipeline", "manager", "audio", "tts", "stt", "rag",
            "index", "config", "logs", "llm", "model", "voice", "argo",
        }
        mentions_concept = bool(token_set & concept_tokens)

        # Strict command: clear action + target + no hedging + not framed as a question
        has_target = len(tokens) >= 2
        looks_question = starts_question or ends_question or has_question_cue or has_hedge
        is_command = has_action and has_target and not looks_question

        if intent is not None:
            if intent.intent_type in {
                IntentType.MUSIC,
                IntentType.MUSIC_STOP,
                IntentType.MUSIC_NEXT,
                IntentType.MUSIC_STATUS,
            }:
                if is_command:
                    return "COMMAND"
            if intent.intent_type in {IntentType.SYSTEM_HEALTH, IntentType.SYSTEM_INFO, IntentType.COUNT}:
                return "QUESTION"

        if is_command:
            return "COMMAND"

        # Loose question detection
        if starts_question or ends_question or has_question_cue:
            return "QUESTION"
        if mentions_concept and not has_action:
            return "QUESTION"
        if len(tokens) <= 4 and not has_action:
            return "QUESTION"

        # Safe default: ambiguous -> QUESTION
        return "QUESTION"

    def _is_executable_command(self, user_text: str) -> bool:
        if not user_text:
            return False
        text = user_text.strip().lower()
        tokens = re.findall(r"\w+", text)
        if not tokens:
            return False
        action_verbs = {
            "open", "delete", "run", "start", "stop", "enable", "disable",
            "install", "remove", "play", "pause", "resume", "next", "skip",
            "set", "change", "turn", "launch",
        }
        first = tokens[0]
        if first not in action_verbs:
            return False
        if text.endswith("?"):
            return False
        if re.search(r"\b(what|why|how|who|when|where|explain|describe|define)\b", text):
            return False
        if re.search(r"\b(would|could|can|should|might|maybe|perhaps|possibly)\b", text):
            return False
        if re.search(r"\bwhat happens if\b|\bwhat if\b", text):
            return False
        return True

    def _should_reject_audio(self, rms: float, silence_ratio: float) -> tuple[bool, str]:
        if rms < self._stt_min_rms_threshold:
            return True, "below_rms_threshold"
        if silence_ratio >= self._stt_silence_ratio_threshold:
            return True, "silence_detected"
        return False, ""

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

    def _parse_memory_write(self, user_text: str) -> dict | None:
        text = user_text.strip()
        original_lower = text.lower()
        lower = original_lower
        match = re.search(r"\b(remember|save this|from now on)\b", lower)
        if not match:
            return None

        text = text[match.start():]
        lower = text.lower()

        if re.search(r"\bremember\s+everything\b", lower) or re.search(r"\bfrom now on\b", lower) and "remember" in lower and "everything" in lower:
            return {"reject": "bulk"}

        mem_type = "FACT"
        if re.search(r"\b(project|this project)\b", original_lower):
            mem_type = "PROJECT"
        if re.search(r"\b(session|this session|temporary|temp)\b", original_lower):
            mem_type = "EPHEMERAL"

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
                "overwrite": "overwrite" in original_lower or "replace" in original_lower,
            }

        call_match = re.search(r"\bcall me\s+(.+)$", remainder, flags=re.IGNORECASE)
        if call_match:
            return {"type": mem_type, "key": "user.name", "value": call_match.group(1).strip()}

        name_match = re.search(r"\bmy name is\s+(.+)$", remainder, flags=re.IGNORECASE)
        if name_match:
            return {"type": mem_type, "key": "user.name", "value": name_match.group(1).strip()}

        if ":" in remainder:
            key, value = remainder.split(":", 1)
            return {
                "type": mem_type,
                "key": key.strip(" .,!?:;"),
                "value": value.strip(),
                "overwrite": "overwrite" in original_lower or "replace" in original_lower,
            }

        if " is " in remainder:
            key, value = remainder.split(" is ", 1)
            return {
                "type": mem_type,
                "key": key.strip(" .,!?:;"),
                "value": value.strip(),
                "overwrite": "overwrite" in original_lower or "replace" in original_lower,
            }

        return {"type": mem_type, "key": None, "value": remainder.strip()}

    def _handle_memory_command(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        lower = user_text.lower().strip()
        project_ns = self._get_project_namespace()

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
            if not facts and not projects and not ephemerals:
                response = "No memory stored."
            else:
                parts = []
                if facts:
                    parts.append("FACT: " + "; ".join([f"{m.key} = {m.value}" for m in facts[:20]]))
                if projects:
                    parts.append("PROJECT: " + "; ".join([f"{m.key} = {m.value}" for m in projects[:20]]))
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
            except Exception as e:
                self.logger.warning(f"[MEMORY] Stats failed: {e}")
                response = "Memory store unavailable."
            else:
                response = f"Memory stats: FACT={fact_count}, PROJECT({project_ns})={project_count}, EPHEMERAL={len(self._ephemeral_memory)}."
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
                except Exception as e:
                    self.logger.warning(f"[MEMORY] Explain failed: {e}")
                    response = "Memory store unavailable."
                else:
                    parts = []
                    for m in facts:
                        parts.append(f"FACT {m.key} = {m.value} (source={m.source}, ts={m.timestamp})")
                    for m in projects:
                        parts.append(f"PROJECT[{m.namespace}] {m.key} = {m.value} (source={m.source}, ts={m.timestamp})")
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
            mem_type = write.get("type")
            key = write.get("key")
            value = write.get("value")
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

            if mem_type == "EPHEMERAL":
                self._ephemeral_memory[key] = value
                response = f"Okay. I will remember for this session: {key} = {value}."
            else:
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
                try:
                    existing = self._memory_store.get_by_key(key, mem_type=mem_type, namespace=namespace)
                except Exception as e:
                    self.logger.warning(f"[MEMORY] Lookup failed: {e}")
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
                if existing and not write.get("overwrite"):
                    response = f"Memory key '{key}' already exists. Say 'overwrite' to replace it."
                else:
                    try:
                        if existing and write.get("overwrite"):
                            self._memory_store.delete_memory(key, mem_type=mem_type, namespace=namespace)
                        self._memory_store.add_memory(mem_type, key, value, source="user", namespace=namespace)
                        response = f"Stored {mem_type} memory: {key} = {value}."
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

        return False

    def _log_gate(self, gate: Gate, allowed: bool, reason: str, interaction_id: str) -> None:
        verdict = "PASS" if allowed else "FAIL"
        suffix = f" reason={reason}" if reason else ""
        self.logger.info(f"[GATE] {gate.value} {verdict}{suffix}")
        self._record_timeline(
            f"GATE {gate.value} {verdict}{suffix}",
            stage="gate",
            interaction_id=interaction_id,
        )

    def _evaluate_gates(self, capability_key: str, module_key: str, interaction_id: str) -> tuple[bool, str]:
        for gate in GATES_ORDER:
            allowed = True
            reason = ""
            if gate == Gate.VALIDATION:
                if not is_capability_enabled(capability_key):
                    allowed = False
                    reason = f"capability:{capability_key}"
                elif not is_module_enabled(module_key):
                    allowed = False
                    reason = f"module:{module_key}"
            elif gate == Gate.PERMISSION:
                if not is_permission_allowed(capability_key):
                    allowed = False
                    reason = f"permission:{capability_key}"
            elif gate == Gate.SAFETY:
                allowed = True
            elif gate == Gate.RESOURCE:
                if capability_key == "music_playback" and not self.runtime_overrides.get("music_enabled", True):
                    allowed = False
                    reason = "music_disabled"
            elif gate == Gate.AUDIT:
                allowed = True
            self._log_gate(gate, allowed, reason, interaction_id)
            if not allowed:
                return False, f"{gate.value}:{reason}".rstrip(":")
        return True, ""

    def _get_rag_context(self, user_text: str, interaction_id: str) -> str:
        if not is_capability_enabled("rag_query"):
            return ""
        if not is_permission_allowed("rag_query"):
            return ""
        if not is_module_enabled("rag"):
            return ""
        try:
            from tools.argo_rag import query_index
            results = query_index(user_text, limit=5)
        except Exception as e:
            self.logger.warning(f"[RAG] Query failed: {e}")
            self._record_timeline("RAG_QUERY_ERROR", stage="rag", interaction_id=interaction_id)
            return ""
        if not results:
            self._record_timeline("RAG_QUERY_EMPTY", stage="rag", interaction_id=interaction_id)
            return ""
        parts = []
        for idx, chunk in enumerate(results, 1):
            parts.append(f"Source {idx}: {chunk.path}:{chunk.start_line}-{chunk.end_line}\n{chunk.text}")
        self._record_timeline(f"RAG_QUERY_HITS {len(parts)}", stage="rag", interaction_id=interaction_id)
        return "\n\n".join(parts)


    def transcribe(self, audio_data, interaction_id: str = ""):
        if self.stt_model is None:
            self.logger.error("[STT] Model not initialized")
            return ""
        self.logger.info(f"[STT] Starting transcription... Audio len: {len(audio_data)}")
        self._record_timeline("STT_START", stage="stt", interaction_id=interaction_id)
        start = time.perf_counter()
        try:
            # Basic audio metrics
            duration_s = len(audio_data) / 16000.0 if len(audio_data) else 0
            rms = float(np.sqrt(np.mean(audio_data ** 2))) if len(audio_data) else 0.0
            peak = float(np.max(np.abs(audio_data))) if len(audio_data) else 0.0
            silence_ratio = float(np.mean(np.abs(audio_data) < 0.01)) if len(audio_data) else 1.0

            reject, reason = self._should_reject_audio(rms, silence_ratio)
            if reject:
                self.logger.info(f"[STT] Discarded audio: {reason}")
                self._record_timeline(f"STT_DISCARD {reason}", stage="stt", interaction_id=interaction_id)
                return ""

            # Clamp normalization: avoid noise amplification
            if peak > 1.0:
                audio_data = audio_data / peak

            segments, info = self.stt_model.transcribe(
                audio_data, 
                beam_size=5, 
                language="en",
                condition_on_previous_text=False,
                initial_prompt=self._stt_initial_prompt or None,
            )
            segments_list = list(segments)
            text = " ".join([s.text for s in segments_list]).strip()
            
            for i, seg in enumerate(segments_list):
                confidence = np.exp(seg.avg_logprob)
                self.logger.info(f"  Seg {i}: '{seg.text}' ({confidence:.2f})")
            
            duration = (time.perf_counter() - start) * 1000
            self.logger.info(f"[STT] Done in {duration:.0f}ms: '{text}'")
            confidence_proxy = 0.0
            if duration_s > 0:
                confidence_proxy = min(1.0, (len(text) / max(1.0, duration_s * 10)) * (1.0 - silence_ratio))
            self._record_timeline(
                f"STT_DONE len={len(text)} rms={rms:.4f} peak={peak:.4f} silence={silence_ratio:.2f} conf={confidence_proxy:.2f}",
                stage="stt",
                interaction_id=interaction_id,
            )
            self.broadcast("stt_metrics", {
                "interaction_id": interaction_id,
                "text_len": len(text),
                "duration_s": duration_s,
                "rms": rms,
                "peak": peak,
                "silence_ratio": silence_ratio,
                "confidence": confidence_proxy,
            })
            self._last_stt_metrics = {
                "text_len": len(text),
                "duration_s": duration_s,
                "rms": rms,
                "peak": peak,
                "silence_ratio": silence_ratio,
                "confidence": confidence_proxy,
            }
            return text
        except Exception as e:
            self.logger.error(f"[STT] Failed: {e}", exc_info=True)
            self._record_timeline("STT_ERROR", stage="stt", interaction_id=interaction_id)
            return ""

    def generate_response(self, text, interaction_id: str = "", rag_context: str = ""):
        if not self.llm_enabled:
            self.logger.info("LLM offline: skipping generation")
            return ""
        mode = self._resolve_personality_mode()
        serious_mode = self._is_serious(text)
        convo_context = self._conversation_buffer.as_context_block()
        prompt = self._build_llm_prompt(text, mode, serious_mode, rag_context, convo_context)
        self.logger.info(f"[LLM] Prompt: '{text}'")
        full_response = ""
        try:
            model_name = "qwen:latest"
            if self._config is not None:
                model_name = self._config.get("llm.model", model_name)
            client = ollama.Client(host='http://127.0.0.1:11434')
            self._record_timeline("LLM_REQUEST_START", stage="llm", interaction_id=interaction_id)
            start = time.perf_counter()
            first_token_ms = None
            stream = client.generate(model=model_name, prompt=prompt, stream=True)
            
            for chunk in stream:
                if self.stop_signal.is_set():
                    break
                part = chunk.get('response', '')
                if part and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                    self._record_timeline(
                        f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms",
                        stage="llm",
                        interaction_id=interaction_id,
                    )
                full_response += part
            total_ms = (time.perf_counter() - start) * 1000
            self._record_timeline(
                f"LLM_DONE {total_ms:.0f}ms",
                stage="llm",
                interaction_id=interaction_id,
            )
            self.broadcast("llm_metrics", {
                "interaction_id": interaction_id,
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
            })
            full_response = self._strip_prompt_artifacts(full_response)
            self.logger.info(f"[LLM] Response: '{full_response[:60]}...'")
            return full_response
        except Exception as e:
            self.logger.error(f"[LLM] Error: {e}")
            self._record_timeline("LLM_ERROR", stage="llm", interaction_id=interaction_id)
            return "[Error connecting to LLM]"

    def set_llm_enabled(self, enabled: bool) -> None:
        self.llm_enabled = bool(enabled)

    def _resolve_personality_mode(self) -> str:
        try:
            mode = self.runtime_overrides.get("personality_mode")
            if not mode and self._config is not None:
                mode = self._config.get("personality.mode", "mild")
        except Exception:
            mode = "mild"
        return mode or "mild"

    def _is_serious(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        return any(kw in lower for kw in self._serious_mode_keywords)

    def _build_llm_prompt(self, user_text: str, mode: str, serious_mode: bool, rag_context: str = "", convo_context: str = "") -> str:
        critical = "CRITICAL: Never use numbered lists or bullet points. Use plain conversational prose only.\n"
        rag_block = ""
        if rag_context:
            rag_block = (
                "RAG CONTEXT (read-only). Use only this context. If it is insufficient, say you do not know.\n"
                f"{rag_context}\n"
            )
        convo_block = ""
        if convo_context:
            convo_block = f"{convo_context}\n"
        if serious_mode:
            persona = (
                "You are ARGO in SERIOUS_MODE.\n"
                "Tone: clean, calm, surgical. No jokes. No sarcasm.\n"
                "Give a direct answer, then a brief explanation.\n"
                "No fluff. No theatrics. No filler.\n"
            )
        elif mode == "tommy_gunn":
            persona = (
                "You are ARGO in TOMMY GUNN MODE (Dry, Smart, Amused).\n"
                "Tone: sharp, well-read adult. Dry and observational. Calm confidence.\n"
                "Required flow: Dry hook (1 sentence) → Direct factual correction → Plain explanation → Wry observation on myth origin → Authority close.\n"
                "No greetings. No questions at the end unless user explicitly asked for follow-ups.\n"
                "Humor: one dry jab max, must not add new info. If in doubt, remove it.\n"
                "Metaphors optional, brief, grounded. No stacked metaphors.\n"
                "SERIOUS_MODE: drop humor entirely, skip dry hook, deliver facts cleanly and directly.\n"
                "Do NOT output section labels (e.g., 'Dry hook:', 'Direct factual correction:', 'Plain explanation:', 'Wry observation:', 'Authority close:').\n"
                "Do NOT repeat system instructions or flags like SERIOUS_MODE or CRITICAL.\n"
                "No corporate filler. No therapy talk. No 'as an AI' phrasing.\n"
                "Never include system diagnostics in responses.\n"
            )
        else:
            persona = (
                "You are ARGO, a veteran mentor.\n"
                "You speak clearly, confidently, and with quiet humor.\n"
                "Start with a direct observation or conclusion.\n"
                "Explain only what matters.\n"
                "End with a line that adds perspective or a small smile.\n"
                "Do not perform, hype, or explain yourself.\n"
            )
        return f"{persona}{critical}{rag_block}{convo_block}User: {user_text}\nResponse:"

    def _strip_prompt_artifacts(self, text: str) -> str:
        if not text:
            return text
        text = re.sub(r"\bSERIOUS_MODE\b[:\s\S]*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCRITICAL\b[:\s\S]*$", "", text, flags=re.IGNORECASE)
        labels = [
            r"dry hook",
            r"direct factual correction",
            r"plain explanation",
            r"wry observation",
            r"authority close",
        ]
        for label in labels:
            text = re.sub(rf"\b{label}\b\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text

    def _build_count_response(self, text: str) -> str:
        target = self._parse_count_target(text)
        if target < 1:
            target = 1
        target = min(target, 50)
        return ", ".join(str(i) for i in range(1, target + 1))

    def _parse_count_target(self, text: str) -> int:
        if not text:
            return 5
        match = re.search(r"\b(\d+)\b", text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return 5
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
        }
        for word, value in words.items():
            if re.search(rf"\b{word}\b", text, flags=re.IGNORECASE):
                return value
        return 5

    def _format_system_health(self, health: dict) -> str:
        return (
            f"CPU at {health.get('cpu_percent')} percent. "
            f"Memory at {health.get('ram_percent')} percent. "
            f"Disk {health.get('disk_percent')} percent full."
        )

    def _format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        text = (
            f"Your system has {total_gb} gigabytes of memory installed. "
            f"Currently using about {used_pct} percent."
        )
        cpu_temp = temps.get("cpu")
        gpu_temp = temps.get("gpu")
        if cpu_temp is not None:
            text += f" CPU temperature is {cpu_temp} degrees."
        if gpu_temp is not None:
            text += f" GPU temperature is {gpu_temp} degrees."
        return text

    def _format_temperature_response(self, temps: dict) -> str:
        parts = []
        cpu_temp = temps.get("cpu")
        gpu_temp = temps.get("gpu")
        if cpu_temp is not None:
            parts.append(f"CPU temperature is {cpu_temp} degrees.")
        if gpu_temp is not None:
            parts.append(f"GPU temperature is {gpu_temp} degrees.")
        if not parts:
            return "Temperature sensors are not available on this system."
        return " ".join(parts) + " Normal."

    def _format_system_full_report(self, report: dict) -> str:
        health = report.get("health", {}) or {}
        disks = report.get("disks", {}) or {}
        uptime_seconds = report.get("uptime_seconds", 0) or 0
        network = report.get("network", []) or []
        battery = report.get("battery")
        fans = report.get("fans")

        parts = []
        cpu_pct = health.get("cpu_percent")
        ram_pct = health.get("ram_percent")
        disk_pct = health.get("disk_percent")
        gpu_pct = health.get("gpu_percent")
        gpu_mem = health.get("gpu_mem_percent")
        if cpu_pct is not None and ram_pct is not None and disk_pct is not None:
            parts.append(f"CPU is {cpu_pct} percent. Memory is {ram_pct} percent. Disk usage is {disk_pct} percent.")
        if gpu_pct is not None:
            if gpu_mem is not None:
                parts.append(f"GPU usage is {gpu_pct} percent, with VRAM at {gpu_mem} percent.")
            else:
                parts.append(f"GPU usage is {gpu_pct} percent.")

        cpu_temp = health.get("cpu_temp")
        gpu_temp = health.get("gpu_temp")
        if cpu_temp is not None or gpu_temp is not None:
            temp_bits = []
            if cpu_temp is not None:
                temp_bits.append(f"CPU {cpu_temp}°C")
            if gpu_temp is not None:
                temp_bits.append(f"GPU {gpu_temp}°C")
            parts.append("Temperatures: " + ", ".join(temp_bits) + ".")

        if uptime_seconds:
            hours = round(uptime_seconds / 3600, 1)
            parts.append(f"Uptime is {hours} hours.")

        if disks:
            disk_bits = []
            for label, info in sorted(disks.items()):
                drive_label = label.replace(":", "")
                free_text = self._format_size_gb(info["free_gb"])
                total_text = self._format_size_gb(info["total_gb"])
                disk_bits.append(
                    f"{drive_label} drive is {info['percent']} percent full, with {free_text} free out of {total_text}."
                )
            parts.append("Drives: " + " ".join(disk_bits))

        if network:
            net_bits = []
            for nic in network:
                label = nic.get("name")
                ip = nic.get("ip")
                speed = nic.get("speed_mbps")
                seg = label or "Network"
                if ip:
                    seg += f" {ip}"
                if speed:
                    seg += f" {speed}Mbps"
                net_bits.append(seg)
            parts.append("Network: " + ", ".join(net_bits) + ".")

        if battery:
            pct = battery.get("percent")
            plugged = battery.get("plugged")
            if pct is not None:
                status = "plugged in" if plugged else "on battery"
                parts.append(f"Battery is {pct} percent, {status}.")

        if fans:
            fan_bits = [f"{f['label']} {f['rpm']}RPM" for f in fans if f.get("rpm") is not None]
            if fan_bits:
                parts.append("Fans: " + ", ".join(fan_bits) + ".")

        if not parts:
            return "Hardware information unavailable."

        return "System status. " + " ".join(parts)

    def _format_size_gb(self, gb: float) -> str:
        try:
            if gb >= 1024:
                tb = round(gb / 1024, 2)
                return f"{tb} terabytes"
            gigs = int(gb)
            megs = int(round((gb - gigs) * 1024))
            if gigs > 0 and megs > 0:
                return f"{gigs} gigs {megs} megs"
            if gigs > 0:
                return f"{gigs} gigs"
            return f"{megs} megs"
        except Exception:
            return f"{gb} gigs"

    def _strip_disallowed_phrases(self, text: str) -> str:
        if not text:
            return text
        phrases = [
            "I'm sorry",
            "I cannot provide",
            "you may want to consult",
        ]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        filtered = [s for s in sentences if not any(p.lower() in s.lower() for p in phrases)]
        cleaned = " ".join(filtered).strip()
        return cleaned

    def speak(self, text, interaction_id: str = ""):
        if not self.runtime_overrides.get("tts_enabled", True):
            self.logger.info("[TTS] Disabled by runtime override")
            return
        self.logger.info(f"[TTS] Speaking with {self.current_voice_key}...")
        if self.current_state == "TRANSCRIBING":
            self.transition_state("THINKING", interaction_id=interaction_id, source="tts")
        self.transition_state("SPEAKING", interaction_id=interaction_id, source="tts")
        self.stop_signal.clear()
        self.is_speaking = True
        self._record_timeline("TTS_START", stage="tts", interaction_id=interaction_id)
        try:
            try:
                self.audio.acquire_audio("TTS", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[TTS] Audio ownership error: {e}")
                log_event("TTS_AUDIO_CONTESTED", stage="audio", interaction_id=interaction_id)
                return

            if self._edge_tts is None:
                from core.output_sink import EdgeTTSOutputSink
                self._edge_tts = EdgeTTSOutputSink(voice=self.voices.get(self.current_voice_key, "en-US-AriaNeural"))

            # Edge TTS playback (blocking)
            self._edge_tts.speak(text)
        except Exception as e:
            self.logger.error(f"[TTS] Error: {e}")
        finally:
            try:
                self.audio.release_audio("TTS", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[TTS] Exception during audio.release_audio: {e}")
            self.is_speaking = False
            self._record_timeline("TTS_DONE", stage="tts", interaction_id=interaction_id)


    def _classify_canonical_topic(self, user_text):
        """
        Deterministically classify user_text into canonical topic buckets.
        Returns (topic, matched_keywords) or (None, set())
        """
        from core.intent_parser import (
            detect_system_health,
            detect_disk_query,
            detect_temperature_query,
            HARDWARE_KEYWORDS,
            SYSTEM_OS_QUERIES,
            SYSTEM_MEMORY_QUERIES,
            SYSTEM_CPU_QUERIES,
            SYSTEM_GPU_QUERIES,
            SYSTEM_MOTHERBOARD_QUERIES,
        )
        text = user_text.lower() if user_text else ""
        tokens = set(re.findall(r"\w+", text))

        # SYSTEM_HEALTH short-circuit (must be evaluated before SELF_IDENTITY)
        health_matches = set()
        if detect_system_health(text):
            health_matches.add("system_health")
        if detect_disk_query(text):
            health_matches.add("disk")
        if detect_temperature_query(text):
            health_matches.add("temperature")
        for kw in HARDWARE_KEYWORDS:
            if kw in text:
                health_matches.add(kw)
        for q in SYSTEM_OS_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_MEMORY_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_CPU_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_GPU_QUERIES:
            if q in text:
                health_matches.add(q)
        for q in SYSTEM_MOTHERBOARD_QUERIES:
            if q in text:
                health_matches.add(q)
        if tokens & {"cpu", "ram", "memory", "disk", "drive", "gpu", "temperature", "temp", "health"}:
            health_matches |= (tokens & {"cpu", "ram", "memory", "disk", "drive", "gpu", "temperature", "temp", "health"})
        if health_matches:
            return "SYSTEM_HEALTH", health_matches

        # COUNT short-circuit (numeric/utility before other canonical topics)
        count_number_tokens = {
            "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
        }
        if ("count" in tokens and ("to" in tokens or tokens & count_number_tokens or re.search(r"\b\d+\b", text))):
            return "COUNT", {"count"}
        topic_keywords = {
            "LAW": {"law", "laws", "rule", "rules", "constraint", "constraints", "policy", "policies", "govern", "governing"},
            "GATES": {"gate", "gates", "permission", "permissions", "barrier", "barriers", "check", "checks"},
            # Removed 'system' from ARCHITECTURE keywords to allow 'system health' etc. to route to normal logic
            "ARCHITECTURE": {"architecture", "design", "pipeline", "structure", "modules", "components", "layout", "engine"},
            "SELF_IDENTITY": {"identity", "yourself", "argo", "agent", "assistant", "name"},
            "CAPABILITIES": {"capability", "capabilities", "can", "able", "features", "do", "function", "functions", "limit", "limits", "limitation", "limitations", "cannot", "not", "support", "supported"},
            "CODEBASE_STATS": set(),
        }
        # Priority order: LAW, GATES, ARCHITECTURE
        for topic in ["LAW", "GATES", "ARCHITECTURE"]:
            keywords = topic_keywords[topic]
            matched = tokens & keywords
            if matched:
                return topic, matched

        # CODEBASE_STATS explicit phrase matching only (avoid count-only triggers)
        codebase_phrases = {
            "codebase",
            "code base",
            "codebase stats",
            "repo stats",
            "repository stats",
            "workspace stats",
            "project stats",
            "workspace size",
            "repo size",
            "repository size",
            "lines of code",
            "python files",
            "file count",
            "files in workspace",
            "files in the workspace",
        }
        matched_codebase = {p for p in codebase_phrases if p in text}
        if matched_codebase:
            return "CODEBASE_STATS", matched_codebase

        # CAPABILITIES before SELF_IDENTITY fallback
        keywords = topic_keywords["CAPABILITIES"]
        matched = tokens & keywords
        if matched:
            return "CAPABILITIES", matched

        # SELF_IDENTITY fallback (tightened)
        keywords = topic_keywords["SELF_IDENTITY"]
        matched = tokens & keywords
        identity_phrases = {
            "who are you",
            "what are you",
            "who is argo",
            "what is argo",
            "what is your name",
            "what's your name",
            "whats your name",
            "tell me about yourself",
            "tell me about you",
            "identify yourself",
            "who am i talking to",
            "who am i speaking to",
        }
        if any(p in text for p in identity_phrases):
            return "SELF_IDENTITY", {p for p in identity_phrases if p in text}
        identity_specific = tokens & {"argo", "yourself", "identity", "assistant", "agent", "name"}
        question_cue = tokens & {"who", "what"}
        if identity_specific and question_cue:
            return "SELF_IDENTITY", (identity_specific | question_cue)
        return None, set()

    def run_interaction(self, audio_data, interaction_id: str = "", replay_mode: bool = False, overrides: dict | None = None):
        # THREAD SAFETY: Prevent overlapping runs which can crash models
        if not self.processing_lock.acquire(blocking=False):
            self.logger.warning("[PIPELINE] Ignored input - System busy processing previous request")
            return

        try:
            # Reset any prior barge-in state
            self.stop_signal.clear()
            self.timeline_events = []
            if not interaction_id:
                interaction_id = str(uuid.uuid4())
            self.current_interaction_id = interaction_id
            self.logger.info(f"--- Starting Interaction ({len(audio_data)} samples) ---")
            self._record_timeline("INTERACTION_START", stage="pipeline", interaction_id=interaction_id)
            self.transition_state("TRANSCRIBING", interaction_id=interaction_id, source="audio")
            
            # Print to stdout just in case logger fails
            print(f"DEBUG: Processing audio... {audio_data.shape}")

            try:
                self.audio.acquire_audio("STT", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[STT] Audio ownership error: {e}")
                self._record_timeline("STT_AUDIO_CONTESTED", stage="audio", interaction_id=interaction_id)
                return

            user_text = self.transcribe(audio_data, interaction_id=interaction_id)
            self.audio.release_audio("STT", interaction_id=interaction_id)
            if not user_text:
                self.logger.warning("No speech recognized.")
                self.broadcast("log", "User: [No speech recognized]")
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return
            user_text = normalize_system_text(user_text)
            self.broadcast("log", f"User: {user_text}")
            self._conversation_buffer.add("User", user_text)

            # CANONICAL INTERCEPTION: Classify and intercept before any LLM routing
            from core.canonical_answers import get_canonical_answer
            topic, matched = self._classify_canonical_topic(user_text)
            if topic == "SYSTEM_HEALTH":
                self.logger.info(f"[CANONICAL] SYSTEM_HEALTH matched keywords: {sorted(matched)} | LLM BYPASSED")
                topic = None
            if topic == "COUNT":
                response = self._build_count_response(user_text)
                self.logger.info(f"[CANONICAL] Intercepted topic: COUNT | Matched: {sorted(matched)} | LLM BYPASSED")
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return
            if topic:
                answer = get_canonical_answer(topic)
                self.logger.info(f"[CANONICAL] Intercepted topic: {topic} | Matched: {sorted(matched)} | LLM BYPASSED")
                self.broadcast("log", f"Argo: {answer}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(answer or "")
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            stop_terms = {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
            user_text_lower = user_text.lower()
            if any(term in user_text_lower for term in stop_terms):
                music_player = get_music_player()
                if music_player.is_playing():
                    self.logger.info("[ARGO] Active music detected")
                    music_player.stop()
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return
            stt_conf = 0.0
            try:
                stt_conf = float((self._last_stt_metrics or {}).get("confidence", 0.0))
            except Exception:
                stt_conf = 0.0
            if stt_conf < 0.35 or not user_text.strip():
                if is_system_keyword(user_text):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but whitelisted system intent: {user_text}")
                elif re.search(r"\bcount\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but count detected; continuing")
                elif re.search(r"\bvolume\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but volume intent detected; continuing")
                elif re.search(r"\b(remember|save this|from now on|memory|forget)\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but memory intent detected; continuing")
                elif any(term in user_text_lower for term in stop_terms):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but stop intent detected; continuing")
                elif stt_conf < 0.15 or not user_text.strip():
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) or empty text; skipping")
                    if not self._low_conf_notice_given and self.runtime_overrides.get("tts_enabled", True):
                        self.speak("I didn’t catch that clearly. Try saying it as a full sentence.", interaction_id=interaction_id)
                        self._low_conf_notice_given = True
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

            if self._handle_memory_command(user_text, interaction_id, replay_mode, overrides):
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            intent = None
            try:
                intent = self._intent_parser.parse(user_text)
            except Exception:
                intent = None

            request_kind = self._classify_request_type(user_text, intent)
            self.logger.info(f"[CANONICAL] classification={request_kind}")
            self._record_timeline(
                f"CLASSIFY {request_kind}",
                stage="pipeline",
                interaction_id=interaction_id,
            )
            if request_kind == "COMMAND" and intent is None:
                request_kind = "QUESTION"

            # --- MUSIC VOLUME CONTROL (voice) ---
            # Recognize patterns like 'music volume 75%', 'set volume to 50%', 'volume up', 'volume down'
            from core.music_player import set_volume_percent, adjust_volume_percent, get_volume_percent
            volume_patterns = [
                (r"(?:music )?volume (\d{1,3})%?", lambda m: set_volume_percent(int(m.group(1)))),
                (r"set volume to (\d{1,3})%?", lambda m: set_volume_percent(int(m.group(1)))),
                (r"volume up (\d{1,3})%?", lambda m: adjust_volume_percent(int(m.group(1)))),
                (r"volume down (\d{1,3})%?", lambda m: adjust_volume_percent(-int(m.group(1)))),
                (r"volume up", lambda m: adjust_volume_percent(10)),
                (r"volume down", lambda m: adjust_volume_percent(-10)),
                (r"what is the volume", lambda m: None),
                (r"current volume", lambda m: None),
            ]
            user_text_lower = user_text.lower().strip()
            user_text_clean = re.sub(r"[^\w\s%]", " ", user_text_lower)
            user_text_clean = re.sub(r"\s+", " ", user_text_clean).strip()
            is_imperative_volume = bool(re.match(r"^(music\s+)?volume\b", user_text_clean))
            if user_text_lower.endswith("?"):
                is_imperative_volume = False
            if re.search(r"\b(would|could|can|should|might|maybe|perhaps|possibly)\b", user_text_clean):
                is_imperative_volume = False
            if re.search(r"\bwhat happens if\b|\bwhat if\b", user_text_clean):
                is_imperative_volume = False
            for pat, action in volume_patterns:
                m = re.fullmatch(pat, user_text_clean)
                if m:
                    is_status_query = pat in ["what is the volume", "current volume"]
                    if is_imperative_volume:
                        request_kind = "COMMAND"
                    if request_kind != "COMMAND" and not is_status_query:
                        response = "I can adjust volume. Say it as a command to execute."
                        self.broadcast("log", f"Argo: {response}")
                        if not self.stop_signal.is_set() and not replay_mode:
                            tts_text = self._sanitize_tts_text(response)
                            tts_override = (overrides or {}).get("suppress_tts", False)
                            if tts_override:
                                self.logger.info("[TTS] Suppressed for next interaction override")
                            elif tts_text:
                                self.speak(tts_text, interaction_id=interaction_id)
                        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                        self.logger.info("--- Interaction Complete ---")
                        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                        return
                    if not is_status_query and not (self._is_executable_command(user_text) or is_imperative_volume):
                        response = "I can adjust volume. Say it as a direct command."
                        self.broadcast("log", f"Argo: {response}")
                        if not self.stop_signal.is_set() and not replay_mode:
                            tts_text = self._sanitize_tts_text(response)
                            tts_override = (overrides or {}).get("suppress_tts", False)
                            if tts_override:
                                self.logger.info("[TTS] Suppressed for next interaction override")
                            elif tts_text:
                                self.speak(tts_text, interaction_id=interaction_id)
                        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                        self.logger.info("--- Interaction Complete ---")
                        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                        return
                    allowed, reason = self._evaluate_gates("music_playback", "music_player", interaction_id)
                    if not allowed:
                        response = f"Action blocked by policy ({reason})."
                        self.logger.info(f"[GATE] {response}")
                        self.broadcast("log", f"Argo: {response}")
                        if not self.stop_signal.is_set() and not replay_mode:
                            tts_text = self._sanitize_tts_text(response)
                            tts_override = (overrides or {}).get("suppress_tts", False)
                            if tts_override:
                                self.logger.info("[TTS] Suppressed for next interaction override")
                            elif tts_text:
                                self.speak(tts_text, interaction_id=interaction_id)
                        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                        self.logger.info("--- Interaction Complete ---")
                        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                        return
                    if pat in ["what is the volume", "current volume"]:
                        vol = get_volume_percent()
                        response = f"Music volume: {vol}%"
                    else:
                        action(m)
                        vol = get_volume_percent()
                        response = f"Music volume set to {vol}%"
                    self.logger.info(f"[ARGO] {response}")
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response)
                        tts_override = (overrides or {}).get("suppress_tts", False)
                        if tts_override:
                            self.logger.info("[TTS] Suppressed for next interaction override")
                        elif tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    self.logger.info("--- Interaction Complete ---")
                    self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                    return

            if intent and intent.intent_type in {
                IntentType.MUSIC,
                IntentType.MUSIC_STOP,
                IntentType.MUSIC_NEXT,
                IntentType.MUSIC_STATUS,
            }:
                if request_kind != "COMMAND" and intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
                    response = "I can do that. Say it as a command to execute."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response)
                        tts_override = (overrides or {}).get("suppress_tts", False)
                        if tts_override:
                            self.logger.info("[TTS] Suppressed for next interaction override")
                        elif tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    self.logger.info("--- Interaction Complete ---")
                    self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                    return
                if intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
                    if not self._is_executable_command(user_text):
                        response = "I can do that. Say it as a direct command."
                        self.broadcast("log", f"Argo: {response}")
                        if not self.stop_signal.is_set() and not replay_mode:
                            tts_text = self._sanitize_tts_text(response)
                            tts_override = (overrides or {}).get("suppress_tts", False)
                            if tts_override:
                                self.logger.info("[TTS] Suppressed for next interaction override")
                            elif tts_text:
                                self.speak(tts_text, interaction_id=interaction_id)
                        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                        self.logger.info("--- Interaction Complete ---")
                        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                        return
                allowed, reason = self._evaluate_gates("music_playback", "music_player", interaction_id)
                if not allowed:
                    response = f"Action blocked by policy ({reason})."
                    self.logger.info(f"[GATE] {response}")
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak(response, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return
                if not self.runtime_overrides.get("music_enabled", True):
                    msg = "Music is disabled."
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak(msg, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                music_player = get_music_player()
                blocked = music_player.preflight()
                if blocked:
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak("Music library not indexed yet.", interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return
                playback_started = False
                error_message = ""

                if intent.intent_type == IntentType.MUSIC_STOP:
                    music_player.stop()
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak("Stopped.", interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                if intent.intent_type == IntentType.MUSIC_NEXT:
                    playback_started = music_player.play_next(None)
                    if not playback_started:
                        error_message = "No music playing."

                elif intent.intent_type == IntentType.MUSIC_STATUS:
                    status = query_music_status()
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak(status, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                else:
                    artist = getattr(intent, "artist", None)
                    title = getattr(intent, "title", None)
                    do_not_try_genre_lookup = bool(title)
                    explicit_genre = bool(getattr(intent, "explicit_genre", False))
                    if getattr(intent, "is_generic_play", False) and not artist and not title and not getattr(intent, "keyword", None):
                        playback_started = music_player.play_random(None)
                        if not playback_started:
                            error_message = "Your music library is empty or unavailable."
                        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                        return
                    if title:
                        playback_started = music_player.play_by_song(title, None)
                        if not playback_started and not artist:
                            playback_started = music_player.play_by_artist(title, None)
                    if not playback_started and artist:
                        playback_started = music_player.play_by_artist(artist, None)
                    if not playback_started and getattr(intent, "keyword", None):
                        keyword = intent.keyword
                        if explicit_genre and not do_not_try_genre_lookup:
                            playback_started = music_player.play_by_genre(keyword, None)
                        if not playback_started:
                            playback_started = music_player.play_by_keyword(keyword, None)
                        if not playback_started:
                            error_message = f"No music found for '{keyword}'."
                    if not playback_started and not artist and not title and not getattr(intent, "keyword", None):
                        playback_started = music_player.play_random(None)
                        if not playback_started:
                            error_message = "No music available."

                if intent.intent_type == IntentType.MUSIC and not playback_started and title:
                    setattr(intent, "unresolved", True)
                    if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                        self.speak("I can’t find that track in your library.", interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

                if error_message and self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                    self.speak(error_message, interaction_id=interaction_id)

                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return

            if intent and intent.intent_type == IntentType.COUNT:
                response = self._build_count_response(user_text)
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            if intent and intent.intent_type == IntentType.SYSTEM_HEALTH:
                allowed, reason = self._evaluate_gates("system_health", "system_health", interaction_id)
                if not allowed:
                    response = f"System health access blocked by policy ({reason})."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response)
                        tts_override = (overrides or {}).get("suppress_tts", False)
                        if tts_override:
                            self.logger.info("[TTS] Suppressed for next interaction override")
                        elif tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    self.logger.info("--- Interaction Complete ---")
                    self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                    return
                subintent = getattr(intent, "subintent", None)
                raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
                if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
                    disks = get_disk_info()
                    if not disks:
                        response = "Hardware information unavailable."
                    else:
                        drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
                        if not drive_match:
                            drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
                        if drive_match:
                            letter = drive_match.group(1).upper()
                            key = f"{letter}:"
                            info = disks.get(key) or disks.get(letter)
                            if info:
                                response = (
                                    f"{letter} drive is {info['percent']} percent full, "
                                    f"with {info['free_gb']} gigabytes free."
                                )
                            else:
                                response = "Hardware information unavailable."
                        elif "fullest" in raw_text_lower or "most used" in raw_text_lower:
                            disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
                            response = f"{disk} is the fullest drive at {info['percent']} percent used."
                        elif "most free" in raw_text_lower or "most space" in raw_text_lower:
                            disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
                            response = f"{disk} has the most free space at {info['free_gb']} gigabytes free."
                        else:
                            total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
                            response = f"You have {total_free} gigabytes free across {len(disks)} drives."
                elif subintent == "full":
                    report = get_system_full_report()
                    response = self._format_system_full_report(report)
                elif subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
                    profile = get_system_profile()
                    gpus = get_gpu_profile()
                    raw_text_lower = (getattr(intent, "raw_text", "") or "").lower()
                    wants_specs = "spec" in raw_text_lower or "detail" in raw_text_lower
                    if subintent == "memory":
                        ram_gb = profile.get("ram_gb") if profile else None
                        if wants_specs and profile:
                            speed = profile.get("memory_speed_mhz")
                            modules = profile.get("memory_modules")
                            extra = []
                            if speed:
                                extra.append(f"{speed}MHz")
                            if modules:
                                extra.append(f"{modules} modules")
                            extra_text = f" ({', '.join(extra)})" if extra else ""
                            response = f"Your system has {ram_gb} gigabytes of memory{extra_text}."
                            self.broadcast("log", f"Argo: {response}")
                            if not self.stop_signal.is_set() and not replay_mode:
                                tts_text = self._sanitize_tts_text(response)
                                tts_override = (overrides or {}).get("suppress_tts", False)
                                if tts_override:
                                    self.logger.info("[TTS] Suppressed for next interaction override")
                                elif tts_text:
                                    self.speak(tts_text, interaction_id=interaction_id)
                            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                            self.logger.info("--- Interaction Complete ---")
                            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                            return
                        response = (
                            f"Your system has {ram_gb} gigabytes of memory."
                            if ram_gb is not None
                            else "Hardware information unavailable."
                        )
                    elif subintent == "cpu":
                        cpu_name = profile.get("cpu") if profile else None
                        if wants_specs and profile:
                            cores = profile.get("cpu_cores")
                            threads = profile.get("cpu_threads")
                            mhz = profile.get("cpu_max_mhz")
                            maker = profile.get("cpu_manufacturer")
                            bits = []
                            if maker:
                                bits.append(maker)
                            if cores:
                                bits.append(f"{cores} cores")
                            if threads:
                                bits.append(f"{threads} threads")
                            if mhz:
                                bits.append(f"{mhz} MHz max")
                            detail = f" ({', '.join(bits)})" if bits else ""
                            response = f"Your CPU is a {cpu_name}{detail}." if cpu_name else "Hardware information unavailable."
                            self.broadcast("log", f"Argo: {response}")
                            if not self.stop_signal.is_set() and not replay_mode:
                                tts_text = self._sanitize_tts_text(response)
                                tts_override = (overrides or {}).get("suppress_tts", False)
                                if tts_override:
                                    self.logger.info("[TTS] Suppressed for next interaction override")
                                elif tts_text:
                                    self.speak(tts_text, interaction_id=interaction_id)
                            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                            self.logger.info("--- Interaction Complete ---")
                            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                            return
                        response = (
                            f"Your CPU is a {cpu_name}."
                            if cpu_name
                            else "Hardware information unavailable."
                        )
                    elif subintent == "gpu":
                        if gpus:
                            if wants_specs:
                                gpu_bits = []
                                for gpu in gpus:
                                    name = gpu.get("name")
                                    vram = gpu.get("vram_mb")
                                    dv = gpu.get("driver_version")
                                    detail = []
                                    if vram:
                                        detail.append(f"{vram}MB VRAM")
                                    if dv:
                                        detail.append(f"driver {dv}")
                                    gpu_bits.append(f"{name} ({', '.join(detail)})" if detail else f"{name}")
                                response = "Your GPU(s): " + "; ".join(gpu_bits) + "."
                                self.broadcast("log", f"Argo: {response}")
                                if not self.stop_signal.is_set() and not replay_mode:
                                    tts_text = self._sanitize_tts_text(response)
                                    tts_override = (overrides or {}).get("suppress_tts", False)
                                    if tts_override:
                                        self.logger.info("[TTS] Suppressed for next interaction override")
                                    elif tts_text:
                                        self.speak(tts_text, interaction_id=interaction_id)
                                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                                self.logger.info("--- Interaction Complete ---")
                                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                                return
                            response = f"Your GPU is {gpus[0].get('name')}."
                        else:
                            response = "No GPU detected."
                    elif subintent == "os":
                        os_name = profile.get("os") if profile else None
                        response = (
                            f"You are running {os_name}."
                            if os_name
                            else "Hardware information unavailable."
                        )
                    elif subintent == "motherboard":
                        board = profile.get("motherboard") if profile else None
                        if wants_specs and profile:
                            bios = profile.get("bios_version")
                            sys_maker = profile.get("system_manufacturer")
                            sys_model = profile.get("system_model")
                            parts = []
                            if sys_maker or sys_model:
                                parts.append(" ".join(p for p in [sys_maker, sys_model] if p))
                            if bios:
                                parts.append(f"BIOS {bios}")
                            extra = f" ({', '.join(parts)})" if parts else ""
                            response = f"Your motherboard is {board}{extra}." if board else "Hardware information unavailable."
                            self.broadcast("log", f"Argo: {response}")
                            if not self.stop_signal.is_set() and not replay_mode:
                                tts_text = self._sanitize_tts_text(response)
                                tts_override = (overrides or {}).get("suppress_tts", False)
                                if tts_override:
                                    self.logger.info("[TTS] Suppressed for next interaction override")
                                elif tts_text:
                                    self.speak(tts_text, interaction_id=interaction_id)
                            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                            self.logger.info("--- Interaction Complete ---")
                            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                            return
                        response = (
                            f"Your motherboard is {board}."
                            if board
                            else "Hardware information unavailable."
                        )
                    else:
                        cpu_name = profile.get("cpu") if profile else None
                        ram_gb = profile.get("ram_gb") if profile else None
                        gpu_name = gpus[0].get("name") if gpus else None
                        if not cpu_name or ram_gb is None:
                            response = "Hardware information unavailable."
                        else:
                            response = (
                                f"Your CPU is a {cpu_name}. "
                                f"You have {ram_gb} gigabytes of memory."
                            )
                            if gpu_name:
                                response += f" Your GPU is {gpu_name}."
                            if wants_specs and profile:
                                drives = profile.get("storage_drives") or []
                                if drives:
                                    drive_bits = []
                                    for d in drives:
                                        name = d.get("model") or "Drive"
                                        size = d.get("size_gb")
                                        iface = d.get("interface")
                                        detail = []
                                        if size:
                                            detail.append(f"{size}GB")
                                        if iface:
                                            detail.append(iface)
                                        drive_bits.append(f"{name} ({', '.join(detail)})" if detail else name)
                                    response += " Storage: " + "; ".join(drive_bits) + "."
                elif subintent == "temperature":
                    temps = get_temperature_health()
                    if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
                        response = "Temperature sensors are not available on this system."
                    else:
                        response = self._format_temperature_response(temps)
                else:
                    health = get_system_health()
                    self.logger.info(
                        "[SYSTEM] cpu=%s ram=%s disk=%s",
                        health.get("cpu_percent"),
                        health.get("ram_percent"),
                        health.get("disk_percent"),
                    )
                    response = self._format_system_health(health)
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            if intent and intent.intent_type == IntentType.SYSTEM_INFO:
                allowed, reason = self._evaluate_gates("system_health", "system_health", interaction_id)
                if not allowed:
                    response = f"System information access blocked by policy ({reason})."
                    self.broadcast("log", f"Argo: {response}")
                    if not self.stop_signal.is_set() and not replay_mode:
                        tts_text = self._sanitize_tts_text(response)
                        tts_override = (overrides or {}).get("suppress_tts", False)
                        if tts_override:
                            self.logger.info("[TTS] Suppressed for next interaction override")
                        elif tts_text:
                            self.speak(tts_text, interaction_id=interaction_id)
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    self.logger.info("--- Interaction Complete ---")
                    self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                    return
                profile = get_system_profile()
                gpus = get_gpu_profile()
                subintent = getattr(intent, "subintent", None)
                if subintent == "memory":
                    ram_gb = profile.get("ram_gb") if profile else None
                    response = (
                        f"Your system has {ram_gb} gigabytes of memory."
                        if ram_gb is not None
                        else "Hardware information unavailable."
                    )
                elif subintent == "cpu":
                    cpu_name = profile.get("cpu") if profile else None
                    response = (
                        f"Your CPU is a {cpu_name}."
                        if cpu_name
                        else "Hardware information unavailable."
                    )
                elif subintent == "gpu":
                    if gpus:
                        response = f"Your GPU is {gpus[0].get('name')}."
                    else:
                        response = "No GPU detected."
                elif subintent == "os":
                    os_name = profile.get("os") if profile else None
                    response = (
                        f"You are running {os_name}."
                        if os_name
                        else "Hardware information unavailable."
                    )
                elif subintent == "motherboard":
                    board = profile.get("motherboard") if profile else None
                    response = (
                        f"Your motherboard is {board}."
                        if board
                        else "Hardware information unavailable."
                    )
                else:
                    response = "Hardware information unavailable."
                self.broadcast("log", f"Argo: {response}")
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return

            rag_context = ""
            if request_kind == "QUESTION":
                rag_context = self._get_rag_context(user_text, interaction_id)
            self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
            ai_text = self.generate_response(user_text, interaction_id=interaction_id, rag_context=rag_context)
            ai_text = re.sub(r"[^\x00-\x7F]+", "", ai_text or "")
            ai_text = self._strip_disallowed_phrases(ai_text)
            if not ai_text.strip():
                self.logger.warning("[LLM] Empty response")
                self.broadcast("log", "Argo: [No response]")
                return
            self.broadcast("log", f"Argo: {ai_text}")
            self._conversation_buffer.add("Assistant", ai_text)

            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(ai_text)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
                else:
                    self.logger.warning("[TTS] Sanitized response is empty, skipping TTS")
            
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            self.logger.info("--- Interaction Complete ---")
            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)

            if not replay_mode:
                self._save_replay(
                    interaction_id=interaction_id,
                    audio_data=audio_data,
                    user_text=user_text,
                    ai_text=ai_text,
                )
            
        except Exception as e:
            self.logger.error(f"Pipeline Error: {e}", exc_info=True)
            self.broadcast("status", "ERROR")
            self._record_timeline("PIPELINE_ERROR", stage="pipeline", interaction_id=interaction_id)
        finally:
            self.processing_lock.release()

    def _save_replay(self, interaction_id: str, audio_data, user_text: str, ai_text: str):
        try:
            replay_dir = Path("runtime") / "replays"
            replay_dir.mkdir(parents=True, exist_ok=True)
            audio_path = replay_dir / f"{interaction_id}.npy"
            np.save(audio_path, audio_data)
            payload = {
                "interaction_id": interaction_id,
                "created_at": time.time(),
                "audio_path": str(audio_path),
                "stt_text": user_text,
                "intent": "direct",
                "llm_prompt": user_text,
                "llm_response": ai_text,
                "timeline_events": list(self.timeline_events),
            }
            json_path = replay_dir / f"{interaction_id}.json"
            json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self.broadcast("replay_saved", {
                "interaction_id": interaction_id,
                "created_at": payload["created_at"],
            })
        except Exception as e:
            self.logger.warning(f"Replay save failed: {e}")

    def replay_interaction(self, interaction_id: str):
        replay_dir = Path("runtime") / "replays"
        json_path = replay_dir / f"{interaction_id}.json"
        audio_path = replay_dir / f"{interaction_id}.npy"
        if not json_path.exists() or not audio_path.exists():
            self.logger.warning(f"Replay not found for {interaction_id}")
            return
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            log_event("REPLAY_START", stage="replay", interaction_id=interaction_id)
            self.broadcast("status", "TRANSCRIBING")
            self.broadcast("log", f"User: {payload.get('stt_text', '')}")
            self.broadcast("status", "THINKING")
            self.broadcast("log", f"Argo: {payload.get('llm_response', '')}")
            self.broadcast("status", "LISTENING")
            log_event("REPLAY_END", stage="replay", interaction_id=interaction_id)
        except Exception as e:
            self.logger.error(f"Replay error: {e}")
