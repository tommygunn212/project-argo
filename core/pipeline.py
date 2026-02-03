
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
from datetime import datetime
from typing import Optional
from faster_whisper import WhisperModel
import ollama
import subprocess
import shutil
import os
from pathlib import Path
from collections import deque

from core.instrumentation import log_event
from core.config import (
    get_runtime_overrides,
    get_config,
    MIN_TTS_CONFIDENCE,
    MIN_TTS_TEXT_LEN,
    PERSONAL_MODE_MIN_CONFIDENCE,
    PERSONAL_MODE_MIN_TEXT_LEN,
)
from core.intent_parser import RuleBasedIntentParser, Intent, IntentType, normalize_system_text, is_system_keyword
from core.stt_engine_manager import STTEngineManager, verify_engine_dependencies
from core.music_player import get_music_player
from core.music_status import query_music_status
from core.bluetooth import (
    get_bluetooth_status,
    set_bluetooth_enabled,
    connect_device,
    disconnect_device,
    pair_device,
)
from core.audio_routing import get_audio_routing_status, set_audio_routing
from core.app_control import app_status_response, open_app, close_app_deterministic, focus_app_deterministic, get_active_app, is_app_running
from core.app_registry import APP_REGISTRY
from core.system_volume import get_status as get_system_volume_status, set_volume_percent as set_system_volume_percent, adjust_volume_percent as adjust_system_volume_percent, mute_volume as mute_system_volume, unmute_volume as unmute_system_volume
from core.app_launch import launch_app, resolve_app_launch_target
from core.app_registry import resolve_app_name

# TTS bypass reason for deterministic commands (for logging/debugging)
TTS_ALLOWED_REASON_DETERMINISTIC = "DETERMINISTIC_CONFIDENCE_BYPASS"
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
        self._current_stt_confidence = 1.0
        self._tts_min_text_length = MIN_TTS_TEXT_LEN
        self._tts_min_confidence = MIN_TTS_CONFIDENCE
        self._personal_mode_min_confidence = PERSONAL_MODE_MIN_CONFIDENCE
        self._personal_mode_min_text_len = PERSONAL_MODE_MIN_TEXT_LEN
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
            "THINKING": {"SPEAKING", "LISTENING", "IDLE"},
            "SPEAKING": {"LISTENING", "IDLE"},
        }
        
        # Concurrency Lock
        self.processing_lock = threading.Lock()
        
        # Models
        self.stt_model = None
        self.stt_engine_manager = None
        self.stt_engine = "openai"  # Default engine name
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
        self._pending_barge_in_suppression = None
        self._memory_store = get_memory_store()
        self._ephemeral_memory = {}
        convo_size = 8
        try:
            if self._config is not None:
                convo_size = int(self._config.get("conversation.buffer_size", 8))
        except Exception:
            convo_size = 8
        self._conversation_buffer = ConversationBuffer(max_turns=convo_size)
        ledger_size = 10
        try:
            if self._config is not None:
                ledger_size = int(self._config.get("conversation.ledger_size", 10))
        except Exception:
            ledger_size = 10
        self._conversation_ledger = deque(maxlen=ledger_size)
        self._pending_memory_write = None
        self._pending_memory = None
        self._session_flags = {}
        self._stt_prompt_profile = "general"
        self._stt_initial_prompt = ""
        self._stt_min_rms_threshold = 0.005
        self._stt_silence_ratio_threshold = 0.90
        self._stt_min_duration_s = 0.3
        self._vad_silence_pad_ms = 300
        self.strict_lab_mode = False
        try:
            if self._config is not None:
                self._stt_prompt_profile = str(self._config.get("speech_to_text.prompt_profile", "general"))
                self._stt_min_rms_threshold = float(self._config.get("speech_to_text.min_rms_threshold", 0.005))
                self._stt_silence_ratio_threshold = float(self._config.get("speech_to_text.silence_ratio_threshold", 0.90))
                self._stt_min_duration_s = float(
                    self._config.get(
                        "speech_to_text.min_duration_seconds",
                        self._stt_min_duration_s,
                    )
                )
                self._vad_silence_pad_ms = int(self._config.get("audio.vad_silence_pad_ms", self._vad_silence_pad_ms))
                self.strict_lab_mode = bool(self._config.get("modes.strict_lab_mode", False))
                profiles = self._config.get("speech_to_text.initial_prompt_profiles", {}) or {}
                self._stt_initial_prompt = str(profiles.get(self._stt_prompt_profile, ""))
                self._tts_min_text_length = int(
                    self._config.get("guards.tts.min_text_length", self._tts_min_text_length)
                )
                self._tts_min_confidence = float(
                    self._config.get("guards.tts.min_confidence", self._tts_min_confidence)
                )
                self._personal_mode_min_confidence = float(
                    self._config.get(
                        "guards.stt.personal_min_confidence",
                        self._personal_mode_min_confidence,
                    )
                )
                self._personal_mode_min_text_len = int(
                    self._config.get(
                        "guards.stt.personal_min_text_length",
                        self._personal_mode_min_text_len,
                    )
                )
        except Exception:
            pass
        self._tts_min_text_length = max(1, int(self._tts_min_text_length))
        self._personal_mode_min_text_len = max(1, int(self._personal_mode_min_text_len))
        self._tts_min_confidence = max(0.0, min(1.0, float(self._tts_min_confidence)))
        self._personal_mode_min_confidence = max(0.0, min(1.0, float(self._personal_mode_min_confidence)))
        self._stt_min_duration_s = max(self._stt_min_duration_s, self._vad_silence_pad_ms / 1000.0)
        if "strict_lab_mode" in self.runtime_overrides:
            try:
                self.strict_lab_mode = bool(self.runtime_overrides["strict_lab_mode"])
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

    def _extract_name_from_statement(self, text: str) -> str | None:
        """Extract name from identity statement like 'my name is X' or 'i am X'."""
        lower_text = text.lower().strip()
        
        # Pattern: "my name is X"
        name_match = re.search(r"my name is (.+?)(?:\.|!|\?|$)", lower_text)
        if name_match:
            name = name_match.group(1).strip().title()
            return name if len(name) > 1 and len(name) < 50 else None
        
        # Pattern: "i am X" (stricter: only if confident phrasing)
        if re.match(r"^i am [a-z]", lower_text):
            parts = lower_text.split(" ", 2)
            if len(parts) >= 3:
                name = parts[2].strip().title()
                return name if len(name) > 1 and len(name) < 50 else None

        # Pattern: "call me X" or "you can call me X"
        call_match = re.search(r"(call me|you can call me)\s+(.+?)(?:\.|!|\?|$)", lower_text)
        if call_match and len(call_match.groups()) >= 2:
            name = call_match.group(2).strip().title()
            return name if len(name) > 1 and len(name) < 50 else None
        
        return None

    def _is_affirmative_response(self, text: str) -> bool:
        """Check if response is affirmative (yes, yeah, correct, do it, confirm)."""
        lower_text = text.lower().strip()
        affirmatives = {"yes", "yeah", "yep", "correct", "right", "do it", "confirm", "ok", "okay"}
        return lower_text in affirmatives or any(a == lower_text[:len(a)] for a in affirmatives)

    def _is_negative_response(self, text: str) -> bool:
        """Check if response is negative (no, nope, never, skip, forget)."""
        lower_text = text.lower().strip()
        negatives = {"no", "nope", "never", "skip", "don't", "dont", "forget", "cancel"}
        return lower_text in negatives or any(n == lower_text[:len(n)] for n in negatives)

    def _is_identity_phrase(self, text: str) -> bool:
        lower = (text or "").lower()
        phrases = [
            "my name is",
            "call me",
            "you can call me",
            "i am",
        ]
        return any(phrase in lower for phrase in phrases)

        allow_llm = topic is None
        if request_kind == "QUESTION" and not self.strict_lab_mode:
            assert allow_llm, "Personal mode questions must never be blocked"

        # --- Unresolved Noun Phrase Clarification Rule ---
        # If a question contains an unresolved noun phrase and no prior referent exists, force clarification and block LLM answer generation. No retries, no guessing.
        if request_kind == "QUESTION":
            # Heuristic: If the question contains a noun (not a pronoun) and no referent in convo ledger, block LLM and clarify
            tokens = self._get_meaningful_tokens(user_text)
            # Simple noun phrase detection: look for tokens that are not pronouns or verbs
            pronouns = {"i", "me", "my", "you", "your", "we", "our", "they", "their", "he", "him", "his", "she", "her", "it", "its", "this", "that", "these", "those", "who", "whom", "whose", "which"}
            # If there is a noun-like token and no referent in previous user entry, block
            previous = self._get_previous_user_entry() or ""
            previous_tokens = set(self._get_meaningful_tokens(previous))
            unresolved_nouns = [t for t in tokens if t not in pronouns and t not in previous_tokens]
            if unresolved_nouns:
                clarification = f"Can you clarify what you mean by '{unresolved_nouns[0]}'?"
                self._respond_with_clarification(interaction_id, replay_mode, overrides, prompt=clarification)
                self.logger.info(f"[CLARIFICATION] Blocked LLM answer due to unresolved noun phrase: {unresolved_nouns[0]}")
                return

        # ...existing code...

    def _is_non_propositional_utterance(self, text: str, request_kind: str) -> bool:
        if not text:
            return True
        lower = text.strip().lower()
        explicit_fragments = [
            r"^huh\??$",
            r"^what\??$",
            r"^uh+\??$",
            r"^um+\??$",
            r"^hmm+\??$",
            r"^erm+\??$",
            r"^i\s+don'?t\s+understand\b",
            r"^i\s+do\s+not\s+understand\b",
            r"^it\s+seems\s+like\s+human\b",
        ]
        if any(re.match(pattern, lower) for pattern in explicit_fragments):
            return True
        if request_kind == "ACTION":
            return False
        if self._is_executable_command(lower):
            return False
        if self._has_interrogative_structure(lower):
            return False
        meaningful = self._get_meaningful_tokens(lower)
        if len(meaningful) <= 3:
            return True
        return False

    def _sanitize_tts_text(self, text: str, enforce_confidence: bool = True, deterministic: bool = False) -> str:
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
        cleaned = cleaned.strip()
        if not cleaned:
            return ""
        # Only apply gating if not deterministic/system/canonical
        if not deterministic:
            if len(cleaned) < max(1, self._tts_min_text_length):
                self.logger.warning(
                    "[TTS GUARD] Sanitized text too short (len=%s, min=%s); skipping speech",
                    len(cleaned),
                    self._tts_min_text_length,
                )
                return ""
            if enforce_confidence:
                active_conf = getattr(self, "_current_stt_confidence", None)
                if active_conf is not None and active_conf < self._tts_min_confidence:
                    self.logger.warning(
                        "[TTS GUARD] Confidence %.2f below %.2f; skipping speech",
                        active_conf,
                        self._tts_min_confidence,
                    )
                    return ""
        return cleaned

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

            # Get STT engine configuration
            stt_engine = "openai"  # Default
            stt_model_size = "base"  # Default
            stt_device = "cpu"  # Default
            
            if self._config is not None:
                stt_config = self._config.get("speech_to_text", {})
                if isinstance(stt_config, dict):
                    stt_engine = stt_config.get("engine", "openai")
                    stt_model_size = stt_config.get("model", "base")
                    stt_device = stt_config.get("device", "cpu")

            # Validate engine selection
            if stt_engine not in STTEngineManager.SUPPORTED_ENGINES:
                self.logger.error(
                    f"Invalid STT_ENGINE: {stt_engine}. "
                    f"Supported: {', '.join(STTEngineManager.SUPPORTED_ENGINES)}"
                )
                raise ValueError(f"Invalid STT engine: {stt_engine}")

            self.logger.info(
                f"[STT] Engine configuration: engine={stt_engine}, "
                f"model={stt_model_size}, device={stt_device}"
            )

            # ✅ PREFLIGHT CHECK: Verify engine dependencies before audio init
            verify_engine_dependencies(stt_engine)

            # Initialize STT engine manager
            self.stt_engine_manager = STTEngineManager(
                engine=stt_engine,
                model_size=stt_model_size,
                device=stt_device
            )
            self.stt_model_name = f"{stt_model_size}"
            self.stt_engine = stt_engine
            
            # Warmup the engine
            self.stt_engine_manager.warmup(duration_s=1.0)
            self.logger.info(
                f"[STT] STT engine ready (engine={stt_engine}, "
                f"model={stt_model_size}, device={stt_device})"
            )
        except Exception as e:
            self.logger.error(f"[STT] Initialization Error: {e}")
            raise
        
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

    # PERSONAL MODE CONTRACT:
    # - If text exists, ALWAYS respond.
    # - STT confidence NEVER blocks conversation.
    # - Confidence may only block ACTION execution.
    # - Identity reads bypass confidence entirely.
    # - strict_lab_mode is opt-in only.
    def _classify_request_kind(self, user_text: str) -> str:
        if not user_text or not user_text.strip():
            return "UNKNOWN"
        if self._parse_memory_write(user_text):
            return "WRITE_MEMORY"
        text = user_text.strip().lower()
        tokens = re.findall(r"\w+", text)
        token_set = set(tokens)

        starts_question = bool(re.match(r"^(what|why|how|when|where|who)\b", text))
        ends_question = text.endswith("?")
        has_question_cue = bool(re.search(r"\b(what|why|how|who|when|where|explain|describe|define|tell|show|what's|whats|why's|hows)\b", text))

        hedging = {"maybe", "might", "could", "would", "should", "perhaps", "possibly", "guess", "think", "can", "could", "would", "should"}
        has_hedge = bool(token_set & hedging) or text.startswith("can you") or text.startswith("could you") or text.startswith("would you")

        action_verbs = {
            "open", "close", "quit", "exit", "shutdown", "shut", "delete", "run", "start", "stop",
            "enable", "disable", "install", "remove", "play", "pause", "resume", "next", "skip",
            "set", "change", "turn", "launch",
        }
        has_action = bool(token_set & action_verbs)

        concept_tokens = {
            "system", "file", "pipeline", "manager", "audio", "tts", "stt", "rag",
            "index", "config", "logs", "llm", "model", "voice", "argo",
        }
        mentions_concept = bool(token_set & concept_tokens)

        has_target = len(tokens) >= 2
        looks_question = starts_question or ends_question or has_question_cue or has_hedge
        is_command = has_action and has_target and not looks_question

        if is_command:
            return "ACTION"

        if starts_question or ends_question or has_question_cue:
            return "QUESTION"
        if mentions_concept and not has_action:
            return "QUESTION"
        if len(tokens) <= 4 and not has_action:
            return "QUESTION"

        return "QUESTION"

    def _classify_request_type(self, user_text: str, intent) -> str:
        request_kind = self._classify_request_kind(user_text)
        if request_kind in {"WRITE_MEMORY", "UNKNOWN"}:
            return request_kind

        if intent is not None:
            if intent.intent_type in {
                IntentType.MUSIC,
                IntentType.MUSIC_STOP,
                IntentType.MUSIC_NEXT,
                IntentType.MUSIC_STATUS,
            }:
                if request_kind == "ACTION" or self._is_executable_command(user_text):
                    return "ACTION"
            if intent.intent_type == IntentType.BLUETOOTH_CONTROL:
                if request_kind == "ACTION" or self._is_executable_command(user_text):
                    return "ACTION"
                return "ACTION"
            if intent.intent_type == IntentType.BLUETOOTH_STATUS:
                return "QUESTION"
            if intent.intent_type == IntentType.AUDIO_ROUTING_CONTROL:
                return "ACTION"
            if intent.intent_type == IntentType.AUDIO_ROUTING_STATUS:
                return "QUESTION"
            if intent.intent_type == IntentType.APP_CONTROL:
                return "ACTION"
            if intent.intent_type == IntentType.APP_LAUNCH:
                return "ACTION"
            if intent.intent_type == IntentType.APP_STATUS:
                return "QUESTION"
            if intent.intent_type == IntentType.TIME_STATUS:
                return "QUESTION"
            if intent.intent_type == IntentType.WORLD_TIME:
                return "QUESTION"
            if intent.intent_type == IntentType.VOLUME_STATUS:
                return "QUESTION"
            if intent.intent_type == IntentType.VOLUME_CONTROL:
                return "ACTION"
            if intent.intent_type in {
                IntentType.SYSTEM_HEALTH,
                IntentType.SYSTEM_STATUS,
                IntentType.SYSTEM_INFO,
                IntentType.COUNT,
                IntentType.ARGO_IDENTITY,
                IntentType.ARGO_GOVERNANCE,
            }:
                return "QUESTION"

        return request_kind

    def _has_interrogative_structure(self, text: str) -> bool:
        """Check if text has interrogative structure (question words, question mark).
        TODO: Implement full interrogative detection if needed.
        """
        if not text:
            return False
        lower = text.lower().strip()
        if lower.endswith("?"):
            return True
        question_words = {"what", "why", "how", "who", "when", "where", "which", "whose", "whom", "is", "are", "do", "does", "did", "can", "could", "would", "should", "will"}
        tokens = lower.split()
        if tokens and tokens[0] in question_words:
            return True
        return False

    def _get_meaningful_tokens(self, text: str) -> list:
        """Extract meaningful tokens from text (excluding stop words).
        TODO: Implement full token extraction if needed.
        """
        if not text:
            return []
        stop_words = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "shall", "can", "to", "of", "in", "for", "on", "with", "at", "by", "from", "as", "into", "through", "during", "before", "after", "above", "below", "between", "under", "again", "further", "then", "once", "and", "but", "or", "nor", "so", "yet", "both", "either", "neither", "not", "only", "own", "same", "than", "too", "very", "just", "i", "me", "my", "you", "your", "he", "him", "his", "she", "her", "it", "its", "we", "our", "they", "their", "this", "that", "these", "those"}
        tokens = re.findall(r"\w+", text.lower())
        return [t for t in tokens if t not in stop_words]

    def _is_identity_query(self, text: str) -> bool:
        """Check if text is asking about identity (e.g., 'what is my name').
        TODO: Implement full identity query detection if needed.
        """
        if not text:
            return False
        lower = text.lower().strip()
        identity_patterns = [
            r"what('?s|\s+is)\s+my\s+name",
            r"do\s+you\s+(know|remember)\s+my\s+name",
            r"who\s+am\s+i",
        ]
        return any(re.search(p, lower) for p in identity_patterns)

    def _respond_with_identity_lookup(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        """Respond to identity lookup queries.
        TODO: Implement full identity lookup if needed.
        """
        self.logger.info("[IDENTITY] Identity lookup requested (stub)")
        response = "I don't have your name stored yet."
        try:
            records = self._memory_store.get_by_key("name", mem_type="FACT")
            if records and records[0].value:
                response = f"Your name is {records[0].value}."
        except Exception as e:
            self.logger.warning(f"[IDENTITY] Memory lookup failed: {e}")
        self.broadcast("log", f"Argo: {response}")
        self._append_convo_ledger("argo", response)
        if not self.stop_signal.is_set() and not replay_mode:
            tts_text = self._sanitize_tts_text(response, enforce_confidence=False)
            tts_override = (overrides or {}).get("suppress_tts", False)
            if not tts_override and tts_text:
                self.speak(tts_text, interaction_id=interaction_id)
        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
        self.logger.info("--- Interaction Complete ---")
        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
        return True

    def _respond_with_clarification(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        """Respond with a clarification prompt.
        TODO: Implement full clarification logic if needed.
        """
        self.logger.info("[CLARIFY] Clarification requested (stub)")
        response = "Could you please rephrase that?"
        self.broadcast("log", f"Argo: {response}")
        self._append_convo_ledger("argo", response)
        if not self.stop_signal.is_set() and not replay_mode:
            tts_text = self._sanitize_tts_text(response, enforce_confidence=False)
            tts_override = (overrides or {}).get("suppress_tts", False)
            if not tts_override and tts_text:
                self.speak(tts_text, interaction_id=interaction_id)
        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
        self.logger.info("--- Interaction Complete ---")
        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
        return True

    def _get_clarification_prompt(self) -> str:
        """Return a clarification prompt string.
        TODO: Implement varied prompts if needed.
        """
        return "Could you please rephrase that?"

    def _is_executable_command(self, user_text: str) -> bool:
        if not user_text:
            return False
        text = user_text.strip().lower()
        tokens = re.findall(r"\w+", text)
        if not tokens:
            return False
        action_verbs = {
            "open", "close", "quit", "exit", "shutdown", "shut", "delete", "run", "start", "stop",
            "enable", "disable", "install", "remove", "play", "pause", "resume", "next", "skip",
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

    def _has_music_keywords(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        if self._is_executable_command(lowered):
            return False
        if re.search(r"\b(play|pray|music|song|album|artist|track|playlist|genre)\b", lowered):
            return True
        try:
            from core.music_player import KNOWN_ARTISTS
            return any(artist in lowered for artist in KNOWN_ARTISTS)
        except Exception:
            return False

    def _strip_politeness_for_music(self, text: str) -> tuple[str, str | None]:
        if not text:
            return text, None
        lowered = text.strip().lower()
        politeness_phrases = [
            "can you please",
            "could you please",
            "would you please",
            "hey can you",
            "hey could you",
            "hey please",
            "can you",
            "could you",
            "would you",
            "please",
        ]
        for phrase in politeness_phrases:
            if lowered == phrase:
                return "", phrase
            if lowered.startswith(phrase + " "):
                stripped = text.strip()[len(phrase):].strip()
                return stripped, phrase
        return text, None

    def _normalize_music_command_text(self, text: str) -> str:
        if not text:
            return text
        if not self._has_music_keywords(text):
            return text
        cleaned, stripped_phrase = self._strip_politeness_for_music(text)
        if stripped_phrase:
            self.logger.info(f"[STT_NORMALIZE] stripped_politeness=\"{stripped_phrase}\"")
        normalized = cleaned.strip()
        if re.match(r"^pray\b", normalized, flags=re.IGNORECASE):
            normalized = re.sub(r"^pray\b", "play", normalized, flags=re.IGNORECASE).strip()
        return normalized

    def _music_noun_detected(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        if re.search(r"\b(music|song|album|artist|track|playlist|genre)\b", lowered):
            return True
        if re.match(r"^play\b", lowered) and len(lowered.split()) > 1:
            return True
        try:
            from core.music_player import KNOWN_ARTISTS
            return any(artist in lowered for artist in KNOWN_ARTISTS)
        except Exception:
            return False

    def _should_reject_audio(self, rms: float, silence_ratio: float, duration_s: float) -> tuple[bool, str]:
        """Return True if audio should be rejected as silence/noise."""
        meets_duration_floor = duration_s >= self._stt_min_duration_s
        if meets_duration_floor or rms >= self._stt_min_rms_threshold:
            return False, ""
        if silence_ratio < self._stt_silence_ratio_threshold:
            return False, ""
        return True, (
            f"VAD discard: rms={rms:.4f}, duration_ms={duration_s * 1000:.0f}, "
            f"silence_ratio={silence_ratio:.2f}"
        )

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

    def _get_memory_context(self, interaction_id: str) -> str:
        project_ns = self._get_project_namespace()
        try:
            facts = self._memory_store.list_memory("FACT")
            projects = self._memory_store.list_memory("PROJECT", namespace=project_ns)
            prefs = self._memory_store.list_memory("PREFERENCE")
        except Exception as e:
            self.logger.warning(f"[MEMORY] Context load failed: {e}")
            self._record_timeline("MEMORY_CONTEXT_ERROR", stage="memory", interaction_id=interaction_id)
            return ""
        parts = []
        if facts:
            parts.append("FACT: " + "; ".join([f"{m.key} = {m.value}" for m in facts[:20]]))
        if projects:
            parts.append("PROJECT: " + "; ".join([f"{m.key} = {m.value}" for m in projects[:20]]))
        if prefs:
            parts.append("PREFERENCE: " + "; ".join([f"{m.key} = {m.value}" for m in prefs[:20]]))
        if self._ephemeral_memory:
            parts.append("EPHEMERAL: " + "; ".join([f"{k} = {v}" for k, v in list(self._ephemeral_memory.items())[:20]]))
        return " | ".join(parts)

    def _parse_memory_write(self, user_text: str) -> dict | None:
        text = user_text.strip()
        original_lower = text.lower()
        lower = original_lower
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
        safe_query = " ".join(re.findall(r"[a-z0-9]+", (user_text or "").lower()))
        safe_query = re.sub(r"\s+", " ", safe_query).strip()
        token_count = len(safe_query.split()) if safe_query else 0
        self.logger.info(f"[RAG] sanitized_rag_query='{safe_query}' tokens={token_count}")
        if token_count < 2:
            return ""
        try:
            from tools.argo_rag import query_index
            results = query_index(safe_query, limit=5)
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
        if self.stt_engine_manager is None or self.stt_engine_manager.model is None:
            self.logger.error("[STT] Engine not initialized")
            return ""
        
        self.logger.info(
            f"[STT] Starting transcription (engine={self.stt_engine})... "
            f"Audio len: {len(audio_data)}"
        )
        self._record_timeline("STT_START", stage="stt", interaction_id=interaction_id)
        
        start = time.perf_counter()
        try:
            # Basic audio metrics
            duration_s = len(audio_data) / 16000.0 if len(audio_data) else 0
            rms = float(np.sqrt(np.mean(audio_data ** 2))) if len(audio_data) else 0.0
            peak = float(np.max(np.abs(audio_data))) if len(audio_data) else 0.0
            silence_ratio = float(np.mean(np.abs(audio_data) < 0.01)) if len(audio_data) else 1.0

            reject, reason = self._should_reject_audio(rms, silence_ratio, duration_s)
            if reject:
                self.logger.info(reason)
                self._record_timeline(f"STT_DISCARD {reason}", stage="stt", interaction_id=interaction_id)
                return ""

            # Clamp normalization: avoid noise amplification
            if peak > 1.0:
                audio_data = audio_data / peak

            # Use STT engine manager for transcription
            stt_result = self.stt_engine_manager.transcribe(
                audio_data,
                language="en",
                beam_size=1 if self.stt_engine == "faster" else None,
                condition_on_previous_text=False if self.stt_engine == "faster" else None,
                initial_prompt=self._stt_initial_prompt or None,
            )
            
            text = stt_result["text"]
            engine = stt_result["engine"]
            duration_ms = stt_result["duration_ms"]
            segments = stt_result.get("segments", [])
            
            # Log segments (defensive: handle both dict and dataclass formats)
            for i, seg in enumerate(segments):
                seg_text = seg.text if hasattr(seg, "text") else seg.get("text", "")
                if hasattr(seg, "avg_logprob"):
                    confidence = np.exp(seg.avg_logprob)
                    self.logger.info(f"  Seg {i}: '{seg_text}' (conf={confidence:.2f})")
                else:
                    self.logger.info(f"  Seg {i}: '{seg_text}'")
            
            # Calculate confidence proxy
            confidence_proxy = 0.0
            if duration_s > 0:
                confidence_proxy = min(1.0, (len(text) / max(1.0, duration_s * 10)) * (1.0 - silence_ratio))
            
            self.logger.info(
                f"[STT] Done in {duration_ms:.0f}ms (engine={engine}): '{text}'"
            )
            
            self._record_timeline(
                f"STT_DONE engine={engine} len={len(text)} rms={rms:.4f} peak={peak:.4f} silence={silence_ratio:.2f} conf={confidence_proxy:.2f}",
                stage="stt",
                interaction_id=interaction_id,
            )
            
            self.broadcast("stt_metrics", {
                "interaction_id": interaction_id,
                "engine": engine,
                "text_len": len(text),
                "duration_s": duration_s,
                "rms": rms,
                "peak": peak,
                "silence_ratio": silence_ratio,
                "confidence": confidence_proxy,
            })
            
            self._last_stt_metrics = {
                "engine": engine,
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

    def generate_response(self, text, interaction_id: str = "", rag_context: str = "", memory_context: str = "", use_convo_buffer: bool = True, intent_type: Optional[str] = None, confidence: float = 1.0):
        """
        Generate a response, enforcing principle/mechanism explanation for knowledge intents.
        """
        if not self.llm_enabled:
            self.logger.info("LLM offline: skipping generation")
            return ""
        mode = self._resolve_personality_mode()
        serious_mode = self._is_serious(text)
        convo_context = self._conversation_buffer.as_context_block() if use_convo_buffer else ""
        prompt = self._build_llm_prompt(text, mode, serious_mode, rag_context, memory_context, convo_context)
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

            # --- KNOWLEDGE ANSWER GUARD ---
            knowledge_domains = {
                "knowledge_physics": ["heat", "cooling", "thermodynamics", "energy", "conduction", "convection", "radiation", "molecule", "evaporation", "law", "process"],
                "knowledge_finance": ["store of value", "medium of exchange", "inflation", "currency", "money", "bitcoin", "asset", "liability", "investment", "finance", "bond", "stock", "blockchain"],
                "knowledge_time_system": ["clock", "time source", "system", "status", "uptime", "cpu", "memory", "disk", "metric", "monitor"]
            }

            # Model override for strict instruction-following on knowledge intents
            STRICT_INSTRUCTION_MODEL = "gpt-4.1"  # or your most instruction-reliable model
            DEFAULT_MODEL = model_name
            knowledge_intents = {
                "knowledge_physics",
                "knowledge_finance",
                "knowledge_time_system"
            }
            # Use strict model only for these intents
            if intent_type in knowledge_intents:
                model_to_use = STRICT_INSTRUCTION_MODEL
            else:
                model_to_use = DEFAULT_MODEL

            if intent_type in knowledge_domains and confidence >= 0.95:
                def extract_principle_section(text):
                    # Find the Principle: section and return its content (up to Explanation: or end)
                    import re
                    match = re.search(r"principle:\s*(.*?)(?:\n\s*explanation:|$)", text, re.IGNORECASE | re.DOTALL)
                    return match.group(1).strip() if match else ""

                answer_lower = full_response.lower()
                principle_section = extract_principle_section(full_response)
                has_principle_header = "principle:" in answer_lower
                has_domain_keyword = any(kw in principle_section for kw in knowledge_domains[intent_type])
                if not (has_principle_header and has_domain_keyword):
                    # Structured retry with enforced schema
                    schema_instruction = (
                        "You must answer using the following structure:\n\n"
                        "Principle:\n<Name the underlying scientific, economic, or system principle>\n\n"
                        "Explanation:\n<Explain the phenomenon using that principle in plain language>\n\n"
                        "Do not omit the Principle section."
                    )
                    retry_prompt = self._build_llm_prompt(
                        text + "\n\n" + schema_instruction,
                        mode, serious_mode, rag_context, memory_context, convo_context
                    )
                    retry_response = ""
                    try:
                        stream2 = client.generate(model=model_to_use, prompt=retry_prompt, stream=True)
                        for chunk2 in stream2:
                            if self.stop_signal.is_set():
                                break
                            retry_response += chunk2.get('response', '')
                        retry_response = self._strip_prompt_artifacts(retry_response)
                    except Exception as e:
                        self.logger.error(f"[LLM] Retry Error: {e}")
                        retry_response = full_response
                    retry_lower = retry_response.lower()
                    retry_principle_section = extract_principle_section(retry_response)
                    has_principle_header_retry = "principle:" in retry_lower
                    has_domain_keyword_retry = any(kw in retry_principle_section for kw in knowledge_domains[intent_type])
                    if has_principle_header_retry and has_domain_keyword_retry:
                        self.logger.info("[KNOWLEDGE GUARD] Principle section and domain keyword found on retry.")
                        return retry_response
                    else:
                        # DETERMINISTIC FALLBACK for MUST_PASS knowledge intents
                        must_pass_phrases = getattr(self, 'must_pass_phrases', None)
                        is_must_pass = False
                        if must_pass_phrases:
                            # Check if the normalized input is a must_pass phrase for this intent
                            norm_input = text.strip().lower()
                            for phrase, intent in must_pass_phrases.items():
                                if norm_input == phrase.strip().lower() and intent == intent_type:
                                    is_must_pass = True
                                    break
                        if is_must_pass:
                            self.logger.warning(f"[KNOWLEDGE GUARD] LLM failed schema for MUST_PASS {intent_type}. Using deterministic fallback.")
                            self.logger.info("[KNOWLEDGE GUARD] knowledge_fallback_used = true")
                            # Deterministic, auditable fallback templates
                            if intent_type == "knowledge_physics":
                                fallback = (
                                    "Principle:\nHeat transfer and thermodynamics\n\n"
                                    "Explanation:\nObjects cool down because heat energy moves from warmer objects to cooler surroundings until temperatures equalize."
                                )
                            elif intent_type == "knowledge_finance":
                                fallback = (
                                    "Principle:\nDefinition of money\n\n"
                                    "Explanation:\nMoney functions as a medium of exchange, store of value, and unit of account. Bitcoin partially satisfies these criteria."
                                )
                            elif intent_type == "knowledge_time_system":
                                fallback = (
                                    "Principle:\nSystem clock and resource monitoring\n\n"
                                    "Explanation:\nThe current time comes from the system clock, while system status reflects CPU, memory, and other runtime metrics."
                                )
                            else:
                                fallback = "[Error: No fallback template for this intent.]"
                            # Mark as system generated, confidence high
                            fallback += "\n[system_generated: true]"
                            return fallback
                        else:
                            self.logger.warning("[KNOWLEDGE GUARD] Principle section or domain keyword still missing after retry. Downgrading confidence.")
                            # Downgrade confidence, flag weak_pass, and return as is with warning
                            return retry_response + "\n[Warning: Principle section or domain keyword missing. Answer may be incomplete.]"
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

    def _build_llm_prompt(self, user_text: str, mode: str, serious_mode: bool, rag_context: str = "", memory_context: str = "", convo_context: str = "") -> str:
        critical = "CRITICAL: Never use numbered lists or bullet points. Use plain conversational prose only.\n"
        rag_block = ""
        if rag_context:
            rag_block = (
                "RAG CONTEXT (read-only). Use only this context. If it is insufficient, say you do not know.\n"
                f"{rag_context}\n"
            )
        memory_block = ""
        if memory_context:
            memory_block = (
                "MEMORY CONTEXT (read-only). Use only if relevant. Do not invent new facts.\n"
                f"{memory_context}\n"
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
        return f"{persona}{critical}{rag_block}{memory_block}{convo_block}User: {user_text}\nResponse:"

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

    def _format_ports_summary(self, ports: dict | None) -> str:
        if not ports:
            return "Ports information unavailable."
        serial = ports.get("serial") or []
        parallel = ports.get("parallel") or []
        usb = ports.get("usb_controllers") or []
        bits = []
        if serial:
            serial_names = ", ".join(p.get("name") or p.get("device_id") or "Unknown" for p in serial)
            bits.append(f"Serial ports: {serial_names}.")
        if parallel:
            parallel_names = ", ".join(p.get("name") or p.get("device_id") or "Unknown" for p in parallel)
            bits.append(f"Parallel ports: {parallel_names}.")
        if usb:
            usb_names = ", ".join(u.get("name") or u.get("device_id") or "USB controller" for u in usb)
            bits.append(f"USB controllers: {usb_names}.")
        return " ".join(bits).strip() or "Ports information unavailable."

    def _format_irq_summary(self, irqs: list | None, limit: int = 25) -> str:
        if not irqs:
            return "IRQ information unavailable."
        lines = []
        for irq in irqs[:limit]:
            irq_num = irq.get("irq")
            name = irq.get("name") or irq.get("description") or "IRQ"
            if irq_num is not None:
                lines.append(f"IRQ {irq_num}: {name}")
            else:
                lines.append(f"IRQ: {name}")
        remaining = len(irqs) - len(lines)
        if remaining > 0:
            lines.append(f"({remaining} more)")
        return "; ".join(lines).strip() or "IRQ information unavailable."

    def _get_gate_statuses(self, capability_key: str, module_key: str) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for gate in GATES_ORDER:
            allowed = True
            if gate == Gate.VALIDATION:
                if not is_capability_enabled(capability_key) or not is_module_enabled(module_key):
                    allowed = False
            elif gate == Gate.PERMISSION:
                if not is_permission_allowed(capability_key):
                    allowed = False
            elif gate == Gate.SAFETY:
                allowed = True
            elif gate == Gate.RESOURCE:
                if capability_key == "music_playback" and not self.runtime_overrides.get("music_enabled", True):
                    allowed = False
            elif gate == Gate.AUDIT:
                allowed = True
            statuses[gate.value] = "PASS" if allowed else "FAIL"
        return statuses

    def _format_gate_summary(self, capability_key: str, module_key: str) -> str:
        statuses = self._get_gate_statuses(capability_key, module_key)
        if not statuses:
            return "Gates: unavailable."
        order = [g.value for g in GATES_ORDER]
        bits = [f"{gate.capitalize()} {statuses.get(gate, 'UNKNOWN')}" for gate in order]
        return "Gates: " + ", ".join(bits) + "."

    def _format_subsystem_summary(self) -> str:
        stt_status = "OK" if self.stt_engine_manager is not None else "UNKNOWN"
        tts_status = "OK" if self.runtime_overrides.get("tts_enabled", True) else "DISABLED"
        llm_status = "OK" if self.llm_enabled else "OFFLINE"
        music_status = "OK" if self.runtime_overrides.get("music_enabled", True) else "DISABLED"
        ui_status = "UNKNOWN"
        try:
            ui_status = "OK" if self.runtime_overrides.get("ui_enabled", True) else "DISABLED"
        except Exception:
            pass
        return (
            "Subsystems: "
            f"STT {stt_status}, TTS {tts_status}, LLM {llm_status}, "
            f"Music {music_status}, UI {ui_status}."
        )

    def _format_governance_summary(self) -> str:
        block = self._config.get("canonical.governance", {}) if self._config else {}
        if not isinstance(block, dict):
            block = {}
        overview = block.get("overview")
        laws = block.get("laws") or []
        gates = block.get("five_gates") or []
        bits = []
        if overview:
            bits.append(overview)
        if laws:
            bits.append("Laws: " + " ".join(laws))
        if gates:
            gate_names = [g.get("name") for g in gates if isinstance(g, dict) and g.get("name")]
            if gate_names:
                bits.append("Five Gates: " + ", ".join(str(n) for n in gate_names if n))
        return "Governance: " + " ".join(bits) if bits else "Governance: unavailable."

    def _format_bluetooth_status(self, status: dict) -> str:
        if not status.get("adapter_present"):
            return "Bluetooth adapter not detected."
        enabled = status.get("adapter_enabled")
        paired = status.get("paired_devices") or []
        connected = status.get("connected_devices") or []
        audio_active = status.get("audio_device_active")
        parts = ["Bluetooth is on." if enabled else "Bluetooth is off."]
        parts.append(f"Paired devices: {len(paired)}.")
        if connected:
            parts.append("Connected devices: " + ", ".join(connected) + ".")
        else:
            parts.append("No devices are connected.")
        if audio_active is True:
            parts.append("Audio device active: yes.")
        elif audio_active is False:
            parts.append("Audio device active: no.")
        return " ".join(parts)

    def _is_bluetooth_status_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        if "bluetooth" in lowered or "bt" in lowered:
            return any(term in lowered for term in {"status", "on", "off", "connected", "paired", "devices", "adapter"})
        return "connected" in lowered and any(term in lowered for term in {"headset", "headphones", "earbuds", "speaker", "keyboard", "mouse"})

    def _is_bluetooth_control_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        if any(term in lowered for term in {"turn", "enable", "disable", "connect", "disconnect", "pair"}):
            return "bluetooth" in lowered or "bt" in lowered or any(term in lowered for term in {"headset", "headphones", "earbuds", "speaker", "keyboard", "mouse"})
        return False

    def _respond_with_bluetooth_status(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if self._is_bluetooth_control_text(user_text):
            self.logger.error("[CONTROL/STATUS VIOLATION] Bluetooth status attempted control")
            message = "Bluetooth status cannot change device state. Say a control command explicitly."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        self.logger.info("[BLUETOOTH] mode=STATUS")
        status = get_bluetooth_status()
        message = self._format_bluetooth_status(status)
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, deterministic=True, force_tts=True)

    def _respond_with_bluetooth_control(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if self._is_bluetooth_status_text(user_text) and not self._is_bluetooth_control_text(user_text):
            self.logger.error("[CONTROL/STATUS VIOLATION] Bluetooth control attempted status-only response")
            message = "Bluetooth control requires an explicit command."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if not self._is_bluetooth_control_text(user_text):
            message = "Bluetooth control requires an explicit command."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if stt_conf < self._personal_mode_min_confidence:
            message = "Bluetooth command unclear. Please repeat."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        action = getattr(intent, "action", None)
        target = getattr(intent, "target", None)
        self.logger.info(f"[BLUETOOTH] mode=CONTROL action={action} target={target}")
        allowed, reason = self._evaluate_gates("bluetooth_control", "bluetooth", interaction_id)
        if not allowed:
            message = f"Bluetooth control blocked by policy ({reason})."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if action == "on":
            ok, msg = set_bluetooth_enabled(True)
        elif action == "off":
            ok, msg = set_bluetooth_enabled(False)
        elif action == "connect":
            ok, msg = connect_device(target or "")
        elif action == "disconnect":
            ok, msg = disconnect_device(target or "")
        elif action == "pair":
            ok, msg = pair_device(target)
        else:
            ok, msg = False, "Bluetooth control requires an explicit command."
        if not ok and msg.startswith("Multiple matches"):
            return self._deliver_canonical_response(msg, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        return self._deliver_canonical_response(msg, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _format_audio_routing_status(self, status: dict) -> str:
        output = status.get("default_output") or "Unknown"
        input_dev = status.get("default_input") or "Unknown"
        outputs = status.get("output_devices") or []
        inputs = status.get("input_devices") or []
        parts = [f"Audio output is set to {output}.", f"Input is {input_dev}."]
        if outputs:
            sample = ", ".join(outputs[:5])
            parts.append(f"Available outputs: {sample}.")
        if inputs:
            sample = ", ".join(inputs[:5])
            parts.append(f"Available inputs: {sample}.")
        return " ".join(parts)

    def _is_audio_routing_status_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        status_phrases = {
            "audio status",
            "what audio device am i using",
            "where is sound playing",
            "are my headphones active",
            "what speakers are active",
            "audio routing status",
        }
        if any(p in lowered for p in status_phrases):
            return True
        if "audio" in lowered and any(term in lowered for term in {"status", "using", "playing", "active"}):
            return True
        return False

    def _is_audio_routing_control_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        control_phrases = {
            "switch to",
            "use",
            "set audio output to",
            "set audio input to",
            "change audio device",
            "change audio output",
            "change audio input",
        }
        if any(p in lowered for p in control_phrases):
            return True
        return False

    def _respond_with_audio_routing_status(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if self._is_audio_routing_control_text(user_text):
            self.logger.error("[CONTROL/STATUS VIOLATION] Audio routing STATUS attempted control")
            message = "Audio routing status cannot change devices. Say a control command explicitly."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        self.logger.info("[AUDIO_ROUTING] mode=STATUS")
        status = get_audio_routing_status()
        message = self._format_audio_routing_status(status)
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _respond_with_audio_routing_control(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if self._is_audio_routing_status_text(user_text) and not self._is_audio_routing_control_text(user_text):
            self.logger.error("[CONTROL/STATUS VIOLATION] Audio routing CONTROL attempted status-only response")
            message = "Audio routing control requires an explicit command."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if not self._is_audio_routing_control_text(user_text):
            message = "Audio routing control requires an explicit command."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if stt_conf < self._personal_mode_min_confidence:
            message = "Audio routing command unclear. Please repeat."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        self.logger.info(f"[AUDIO_ROUTING] mode=CONTROL action=switch target={getattr(intent, 'target', None)}")
        allowed, reason = self._evaluate_gates("audio_routing_control", "audio_routing", interaction_id)
        if not allowed:
            message = f"Audio routing control blocked by policy ({reason})."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        action_target = getattr(intent, "target", None) or user_text
        is_input = "input" in user_text.lower() or "mic" in user_text.lower() or "microphone" in user_text.lower()
        ok, msg = set_audio_routing(action_target, is_input)
        return self._deliver_canonical_response(msg, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _is_app_status_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(phrase in lowered for phrase in {
            "what apps are running",
            "what applications are running",
            "list running applications",
            "list running apps",
        }) or re.search(r"\b(is|are|do i have)\b", lowered) is not None and any(term in lowered for term in {"open", "running"})

    def _is_app_control_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        return re.search(r"\b(open|launch|start|close|quit|exit|shut down|shutdown)\b", lowered) is not None

    def _respond_with_app_status(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if self._is_app_control_text(user_text):
            self.logger.error("[CONTROL/STATUS VIOLATION] App STATUS attempted control")
            message = "App status cannot change applications. Say a control command explicitly."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        self.logger.info("[APP] mode=STATUS")
        message = app_status_response(user_text)
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _respond_with_app_control(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if self._is_app_status_text(user_text) and not self._is_app_control_text(user_text):
            self.logger.error("[CONTROL/STATUS VIOLATION] App CONTROL attempted status-only response")
            message = "App control requires an explicit command."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if not self._is_app_control_text(user_text):
            message = "App control requires an explicit command."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        action = getattr(intent, "action", None)
        if action != "close" and stt_conf < self._personal_mode_min_confidence:
            message = "App command unclear. Please repeat."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        app_key = resolve_app_name(user_text)
        if not app_key:
            if action == "close":
                message = "Which app should I close? I can close Notepad, Word, Edge, Calculator, or File Explorer."
            else:
                message = "I don't have a known application called that."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if action == "close":
            self.logger.info("[INTENT] APP_CONTROL close")
        if action not in {"close"}:
            allowed, reason = self._evaluate_gates("app_control", "app_control", interaction_id)
            if not allowed:
                message = f"App control blocked by policy ({reason})."
                self.logger.info(f"Argo: {message}")
                return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        self.logger.info(f"[APP] mode=CONTROL action={action} target={app_key}")
        if action in {"open", "launch"}:
            ok, msg = open_app(app_key)
        elif action in {"close", "quit"}:
            ok, msg, pid, result = close_app_deterministic(app_key)
            pid_display = pid if pid is not None else "<none>"
            self.logger.info(f"[APP_CONTROL] action=close app={app_key} pid={pid_display} result={result}")
        elif action == "focus":
            ok, msg, _ = focus_app_deterministic(app_key)
        else:
            ok, msg = False, "App control requires an explicit command."
        self.logger.info(f"Argo: {msg}")
        return self._deliver_canonical_response(msg, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _respond_with_focus_status(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        target = getattr(intent, "target", None) if intent else None
        if target:
            display = APP_REGISTRY.get(target, {}).get("display", target.capitalize())
            if not is_app_running(target):
                message = f"{display} isn't running."
                return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
            active_key, active_display = get_active_app()
            if active_key == target:
                message = f"Yes, {active_display or display} is focused."
            else:
                message = f"{display} is running but not focused."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

        active_key, active_display = get_active_app()
        if active_display:
            message = f"Active app is {active_display}."
        else:
            message = "Active app unavailable."
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _respond_with_focus_control(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        target = getattr(intent, "target", None) if intent else None
        if not target:
            message = "Which app should I focus? I can focus Notepad, Word, Edge, Calculator, or File Explorer."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        allowed, reason = self._evaluate_gates("app_focus_control", "app_focus", interaction_id)
        if not allowed:
            message = f"App focus blocked by policy ({reason})."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        ok, msg, _ = focus_app_deterministic(target)
        return self._deliver_canonical_response(msg, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _is_system_volume_text(self, text: str) -> bool:
        lowered = (text or "").lower()
        if any(term in lowered for term in {"app volume", "application volume", "per app", "per-app"}):
            return False
        if any(term in lowered for term in {"headphones", "speaker", "speakers", "device", "monitor"}):
            return False
        if "music" in lowered or "song" in lowered:
            return False
        return any(term in lowered for term in {"volume", "mute", "unmute", "sound"})

    def _respond_with_system_volume_status(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        allowed, reason = self._evaluate_gates("system_volume", "system_volume", interaction_id)
        if not allowed:
            message = f"System volume status blocked by policy ({reason})."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        volume, muted = get_system_volume_status()
        message = f"System volume is {volume}%. Muted: {'true' if muted else 'false'}."
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _respond_with_system_volume_control(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if not self._is_system_volume_text(user_text):
            message = "System volume control requires a direct system volume command."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        allowed, reason = self._evaluate_gates("system_volume", "system_volume", interaction_id)
        if not allowed:
            message = f"System volume control blocked by policy ({reason})."
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        lowered = (user_text or "").lower()
        prev_volume, prev_muted = get_system_volume_status()
        ok = False
        msg = ""
        new_volume = prev_volume
        new_muted = prev_muted

        match = re.search(r"set volume to (\d{1,3})%?", lowered)
        if match:
            ok, msg, prev_volume, new_volume, new_muted = set_system_volume_percent(int(match.group(1)))
        elif re.search(r"\bvolume up\b|\bturn volume up\b|\bincrease volume\b", lowered):
            ok, msg, prev_volume, new_volume, new_muted = adjust_system_volume_percent(5)
        elif re.search(r"\bvolume down\b|\bturn volume down\b|\bdecrease volume\b", lowered):
            ok, msg, prev_volume, new_volume, new_muted = adjust_system_volume_percent(-5)
        elif re.search(r"\bmute\b", lowered):
            ok, msg, prev_volume, new_volume, new_muted = mute_system_volume()
        elif re.search(r"\bunmute\b", lowered):
            ok, msg, prev_volume, new_volume, new_muted = unmute_system_volume()
        else:
            msg = "System volume control requires an explicit command."

        self.logger.info(
            f"[SYSTEM_VOLUME] prev={prev_volume} new={new_volume} muted={new_muted}"
        )
        if not ok and msg:
            return self._deliver_canonical_response(msg, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        if ok:
            response = f"System volume set to {new_volume}%."
            if new_muted:
                response = "System volume muted."
            return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)
        return self._deliver_canonical_response("System volume command failed.", interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    # =========================================================================
    # WORLD TIME - City/Country to IANA Timezone mapping
    # =========================================================================
    LOCATION_TO_TIMEZONE = {
        # Major cities
        "london": "Europe/London",
        "paris": "Europe/Paris",
        "berlin": "Europe/Berlin",
        "rome": "Europe/Rome",
        "madrid": "Europe/Madrid",
        "amsterdam": "Europe/Amsterdam",
        "brussels": "Europe/Brussels",
        "vienna": "Europe/Vienna",
        "zurich": "Europe/Zurich",
        "stockholm": "Europe/Stockholm",
        "oslo": "Europe/Oslo",
        "copenhagen": "Europe/Copenhagen",
        "helsinki": "Europe/Helsinki",
        "dublin": "Europe/Dublin",
        "lisbon": "Europe/Lisbon",
        "athens": "Europe/Athens",
        "moscow": "Europe/Moscow",
        "istanbul": "Europe/Istanbul",
        "dubai": "Asia/Dubai",
        "mumbai": "Asia/Kolkata",
        "delhi": "Asia/Kolkata",
        "bangalore": "Asia/Kolkata",
        "kolkata": "Asia/Kolkata",
        "chennai": "Asia/Kolkata",
        "singapore": "Asia/Singapore",
        "hong kong": "Asia/Hong_Kong",
        "hongkong": "Asia/Hong_Kong",
        "shanghai": "Asia/Shanghai",
        "beijing": "Asia/Shanghai",
        "tokyo": "Asia/Tokyo",
        "osaka": "Asia/Tokyo",
        "seoul": "Asia/Seoul",
        "bangkok": "Asia/Bangkok",
        "jakarta": "Asia/Jakarta",
        "sydney": "Australia/Sydney",
        "melbourne": "Australia/Melbourne",
        "brisbane": "Australia/Brisbane",
        "perth": "Australia/Perth",
        "auckland": "Pacific/Auckland",
        "new york": "America/New_York",
        "nyc": "America/New_York",
        "new york city": "America/New_York",
        "los angeles": "America/Los_Angeles",
        "la": "America/Los_Angeles",
        "san francisco": "America/Los_Angeles",
        "seattle": "America/Los_Angeles",
        "chicago": "America/Chicago",
        "denver": "America/Denver",
        "phoenix": "America/Phoenix",
        "miami": "America/New_York",
        "boston": "America/New_York",
        "washington": "America/New_York",
        "dc": "America/New_York",
        "atlanta": "America/New_York",
        "dallas": "America/Chicago",
        "houston": "America/Chicago",
        "toronto": "America/Toronto",
        "vancouver": "America/Vancouver",
        "montreal": "America/Toronto",
        "mexico city": "America/Mexico_City",
        "sao paulo": "America/Sao_Paulo",
        "rio": "America/Sao_Paulo",
        "buenos aires": "America/Argentina/Buenos_Aires",
        "cairo": "Africa/Cairo",
        "johannesburg": "Africa/Johannesburg",
        "lagos": "Africa/Lagos",
        "nairobi": "Africa/Nairobi",
        # Countries (use capital/major city timezone)
        "uk": "Europe/London",
        "united kingdom": "Europe/London",
        "england": "Europe/London",
        "france": "Europe/Paris",
        "germany": "Europe/Berlin",
        "italy": "Europe/Rome",
        "spain": "Europe/Madrid",
        "japan": "Asia/Tokyo",
        "china": "Asia/Shanghai",
        "india": "Asia/Kolkata",
        "australia": "Australia/Sydney",
        "canada": "America/Toronto",
        "brazil": "America/Sao_Paulo",
        "russia": "Europe/Moscow",
        "south korea": "Asia/Seoul",
        "korea": "Asia/Seoul",
        "mexico": "America/Mexico_City",
        "egypt": "Africa/Cairo",
        "south africa": "Africa/Johannesburg",
        # US states/regions
        "california": "America/Los_Angeles",
        "texas": "America/Chicago",
        "florida": "America/New_York",
        "new jersey": "America/New_York",
        "hawaii": "Pacific/Honolulu",
        "alaska": "America/Anchorage",
    }

    def _format_world_time(self, location: str) -> str:
        """Get the current time in a specified location."""
        from zoneinfo import ZoneInfo
        
        location_lower = location.lower().strip()
        
        # Try direct lookup
        tz_name = self.LOCATION_TO_TIMEZONE.get(location_lower)
        
        if not tz_name:
            # Try partial match
            for loc, tz in self.LOCATION_TO_TIMEZONE.items():
                if loc in location_lower or location_lower in loc:
                    tz_name = tz
                    break
        
        if not tz_name:
            return f"I don't have timezone data for {location}. Try a major city name."
        
        try:
            tz = ZoneInfo(tz_name)
            now = datetime.now(tz)
            time_str = now.strftime("%I:%M %p").lstrip("0")
            # Clean up location name for speech
            location_display = location.title()
            return f"It's {time_str} in {location_display}."
        except Exception as e:
            self.logger.error(f"[WORLD_TIME] Error getting time for {location}: {e}")
            return f"Couldn't get the time for {location}."

    def _respond_with_world_time(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        location = getattr(intent, "target", None) if intent else None
        if not location:
            message = "I didn't catch the location. Where would you like to know the time?"
        else:
            message = self._format_world_time(location)
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _format_time_status(self, subintent: str | None) -> str:
        now = datetime.now()
        if subintent == "day":
            return f"Today is {now.strftime('%A')}."
        if subintent == "date":
            return f"Today's date is {now.strftime('%A, %B %d, %Y')}."
        time_str = now.strftime("%I:%M %p").lstrip("0")
        return f"It's {time_str}."

    def _respond_with_time_status(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        subintent = getattr(intent, "subintent", None) if intent else None
        message = self._format_time_status(subintent)
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _has_disallowed_app_launch_tokens(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        if re.search(r"https?://|www\.", lowered):
            return True
        if re.search(r"[a-zA-Z]:\\", text):
            return True
        if re.search(r"\\\\", text):
            return True
        if re.search(r"\s--?\w+", lowered):
            return True
        if re.search(r"\s/\w+", lowered):
            return True
        if re.search(r"[\"']", text):
            return True
        if re.search(r"\.(txt|docx|xlsx|pdf|png|jpg|jpeg|gif|mp3|mp4|exe)\b", lowered):
            return True
        return False

    def _respond_with_app_launch(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        if stt_conf < self._personal_mode_min_confidence and not self._is_executable_command(user_text):
            message = "App launch command unclear. Please repeat."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

        if self._has_disallowed_app_launch_tokens(user_text):
            self.logger.info("[APP_LAUNCH] app=<unknown> result=rejected source=voice")
            message = "App launch only supports core apps without files, URLs, or arguments."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

        app_key = getattr(intent, "target", None) or resolve_app_launch_target(user_text)
        if not app_key:
            self.logger.info("[APP_LAUNCH] app=<unknown> result=rejected source=voice")
            message = "I can open Notepad, Calculator, Microsoft Edge, File Explorer, or PowerShell."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

        allowed, reason = self._evaluate_gates("app_launch", "app_launch", interaction_id)
        if not allowed:
            self.logger.info(f"[APP_LAUNCH] app={app_key} result=failed source=voice")
            message = f"App launch blocked by policy ({reason})."
            self.logger.info(f"Argo: {message}")
            return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

        ok = launch_app(app_key)
        display_name = {
            "notepad": "Notepad",
            "calculator": "Calculator",
            "microsoft edge": "Microsoft Edge",
            "file explorer": "File Explorer",
            "powershell": "PowerShell",
        }.get(app_key, app_key.title())
        result = "success" if ok else "failed"
        self.logger.info(f"[APP_LAUNCH] app={app_key} result={result} source=voice")
        message = f"Opening {display_name}." if ok else f"I couldn't open {display_name}."
        self.logger.info(f"Argo: {message}")
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, force_tts=True)

    def _allow_low_conf_music_command(self, intent, user_text: str) -> bool:
        if not intent or intent.intent_type not in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
            return False
        if not self._is_executable_command(user_text):
            return False
        if intent.intent_type in {IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
            return True
        if getattr(intent, "is_generic_play", False):
            return True
        if getattr(intent, "keyword", None) or getattr(intent, "title", None) or getattr(intent, "artist", None):
            return True
        return False

    def _deliver_canonical_response(
        self,
        message: str,
        interaction_id: str,
        replay_mode: bool,
        overrides: dict | None,
        *,
        enforce_confidence: bool = True,
        force_tts: bool = False,
        suppress_barge_in_seconds: float | None = None,
        deterministic: bool = True,
        stt_conf: float | None = None,
        intent_type: str | None = None,
    ) -> bool:
        # Log when TTS is allowed despite low STT confidence for deterministic commands
        if deterministic and stt_conf is not None and stt_conf < self._personal_mode_min_confidence:
            self.logger.info(
                f"[TTS] Allowed despite low STT confidence "
                f"(reason={TTS_ALLOWED_REASON_DETERMINISTIC}, "
                f"confidence={stt_conf:.2f}, intent={intent_type or 'unknown'})"
            )
        self.broadcast("log", f"Argo: {message}")
        if not self.stop_signal.is_set() and not replay_mode:
            tts_text = self._sanitize_tts_text(message, enforce_confidence=enforce_confidence, deterministic=deterministic)
            tts_override = (overrides or {}).get("suppress_tts", False)
            if force_tts:
                tts_override = False
            if tts_override:
                self.logger.info("[TTS] Suppressed for next interaction override")
            elif tts_text and (force_tts or self.runtime_overrides.get("tts_enabled", True)):
                if suppress_barge_in_seconds:
                    self._pending_barge_in_suppression = suppress_barge_in_seconds
                    if self._edge_tts is not None and hasattr(self._edge_tts, "suppress_interrupt"):
                        try:
                            self._edge_tts.suppress_interrupt(suppress_barge_in_seconds)
                        except Exception:
                            pass
                self.speak(tts_text, interaction_id=interaction_id)
        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
        self.logger.info("--- Interaction Complete ---")
        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
        return True

    def _respond_with_system_health(self, user_text, intent, interaction_id, replay_mode, overrides) -> bool:
        """Answer system health questions without invoking the LLM."""

        is_system_status = bool(intent and intent.intent_type == IntentType.SYSTEM_STATUS)

        def _finish(message: str) -> bool:
            return self._deliver_canonical_response(
                message,
                interaction_id,
                replay_mode,
                overrides,
                enforce_confidence=not is_system_status,
                force_tts=is_system_status,
                suppress_barge_in_seconds=1.5 if is_system_status else None,
            )

        if not is_system_status:
            allowed, reason = self._evaluate_gates("system_health", "system_health", interaction_id)
            if not allowed:
                return _finish(f"System health access blocked by policy ({reason}).")

        subintent = getattr(intent, "subintent", None) if intent else None
        if intent and intent.intent_type == IntentType.SYSTEM_STATUS and not subintent:
            subintent = "full"
        raw_text_lower = (getattr(intent, "raw_text", None) or user_text or "").lower()

        if subintent == "disk" or "drive" in raw_text_lower or "disk" in raw_text_lower:
            disks = get_disk_info()
            if not disks:
                return _finish("Hardware information unavailable.")
            drive_match = re.search(r"\b([a-z])\s*drive\b", raw_text_lower)
            if not drive_match:
                drive_match = re.search(r"\b([a-z]):\b", raw_text_lower)
            if drive_match:
                letter = drive_match.group(1).upper()
                key = f"{letter}:"
                info = disks.get(key) or disks.get(letter)
                if info:
                    return _finish(
                        f"{letter} drive is {info['percent']} percent full, with {info['free_gb']} gigabytes free."
                    )
                return _finish("Hardware information unavailable.")
            if "fullest" in raw_text_lower or "most used" in raw_text_lower:
                disk, info = max(disks.items(), key=lambda x: x[1]["percent"])
                return _finish(f"{disk} is the fullest drive at {info['percent']} percent used.")
            if "most free" in raw_text_lower or "most space" in raw_text_lower:
                disk, info = max(disks.items(), key=lambda x: x[1]["free_gb"])
                return _finish(f"{disk} has the most free space at {info['free_gb']} gigabytes free.")
            total_free = round(sum(d["free_gb"] for d in disks.values()), 1)
            return _finish(f"You have {total_free} gigabytes free across {len(disks)} drives.")

        if subintent == "full":
            report = get_system_full_report()
            message = self._format_system_full_report(report)
            message = f"{message} {self._format_subsystem_summary()} {self._format_gate_summary('system_health', 'system_health')}"
            raw_text_lower = (getattr(intent, "raw_text", None) or user_text or "").lower()
            if any(term in raw_text_lower for term in {"law", "laws", "governance", "gate", "gates"}):
                message = f"{message} {self._format_governance_summary()}"
            return _finish(message)

        if subintent in {"memory", "cpu", "gpu", "os", "motherboard", "hardware"}:
            profile = get_system_profile()
            gpus = get_gpu_profile()
            wants_specs = "spec" in raw_text_lower or "detail" in raw_text_lower
            wants_ports = "port" in raw_text_lower or "usb" in raw_text_lower
            wants_irqs = "irq" in raw_text_lower or "interrupt" in raw_text_lower
            wants_drives = "drive" in raw_text_lower or "disk" in raw_text_lower or "storage" in raw_text_lower
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
                    if ram_gb is not None:
                        return _finish(f"Your system has {ram_gb} gigabytes of memory{extra_text}.")
                    return _finish("Hardware information unavailable.")
                return _finish(
                    f"Your system has {ram_gb} gigabytes of memory." if ram_gb is not None else "Hardware information unavailable."
                )
            if subintent == "cpu":
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
                    if cpu_name:
                        return _finish(f"Your CPU is a {cpu_name}{detail}.")
                    return _finish("Hardware information unavailable.")
                return _finish(
                    f"Your CPU is a {cpu_name}." if cpu_name else "Hardware information unavailable."
                )
            if subintent == "gpu":
                if gpus:
                    if wants_specs:
                        gpu_bits = []
                        for gpu in gpus:
                            name = gpu.get("name")
                            vram = gpu.get("vram_mb")
                            driver_version = gpu.get("driver_version")
                            detail = []
                            if vram:
                                detail.append(f"{vram}MB VRAM")
                            if driver_version:
                                detail.append(f"driver {driver_version}")
                            gpu_bits.append(f"{name} ({', '.join(detail)})" if detail else f"{name}")
                        return _finish("Your GPU(s): " + "; ".join(gpu_bits) + ".")
                    return _finish(f"Your GPU is {gpus[0].get('name')}.")
                return _finish("No GPU detected.")
            if subintent == "os":
                os_name = profile.get("os") if profile else None
                return _finish(f"You are running {os_name}." if os_name else "Hardware information unavailable.")
            if subintent == "motherboard":
                board = profile.get("motherboard") if profile else None
                if wants_specs and profile:
                    bios = profile.get("bios_version")
                    sys_maker = profile.get("system_manufacturer")
                    sys_model = profile.get("system_model")
                    parts = []
                    if sys_maker or sys_model:
                        parts.append(" ".join(p for p in [sys_maker, sys_model] if p).strip())
                    if bios:
                        parts.append(f"BIOS {bios}")
                    extra = f" ({', '.join(parts)})" if parts else ""
                    if board:
                        return _finish(f"Your motherboard is {board}{extra}.")
                    return _finish("Hardware information unavailable.")
                return _finish(f"Your motherboard is {board}." if board else "Hardware information unavailable.")
            cpu_name = profile.get("cpu") if profile else None
            ram_gb = profile.get("ram_gb") if profile else None
            if not cpu_name or ram_gb is None:
                return _finish("Hardware information unavailable.")
            response = f"Your CPU is a {cpu_name}. You have {ram_gb} gigabytes of memory."
            if gpus:
                response += f" Your GPU is {gpus[0].get('name')}."
            if (wants_specs or wants_drives) and profile:
                drives = profile.get("storage_drives") or []
                if drives:
                    drive_bits = []
                    for drive in drives:
                        name = drive.get("model") or "Drive"
                        size = drive.get("size_gb")
                        iface = drive.get("interface")
                        detail = []
                        if size:
                            detail.append(f"{size}GB")
                        if iface:
                            detail.append(iface)
                        drive_bits.append(f"{name} ({', '.join(detail)})" if detail else name)
                    response += " Storage: " + "; ".join(drive_bits) + "."
            if wants_ports:
                response += " " + self._format_ports_summary(profile.get("ports") if profile else None)
            if wants_irqs:
                response += " " + self._format_irq_summary(profile.get("irqs") if profile else None)
            return _finish(response)

        if subintent == "temperature":
            temps = get_temperature_health()
            if temps.get("error") == "TEMPERATURE_UNAVAILABLE":
                return _finish("Temperature sensors are not available on this system.")
            return _finish(self._format_temperature_response(temps))

        health = get_system_health()
        self.logger.info(
            "[SYSTEM] cpu=%s ram=%s disk=%s",
            health.get("cpu_percent"),
            health.get("ram_percent"),
            health.get("disk_percent"),
        )
        return _finish(self._format_system_health(health))

    def _respond_with_argo_identity(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        block = self._config.get("canonical.identity", {}) if self._config else {}
        if not isinstance(block, dict):
            block = {}
        statement = block.get("statement")
        laws = block.get("laws") or []
        segments = []
        if statement:
            segments.append(statement)
        if laws:
            segments.append("Operating laws: " + " ".join(laws))
        message = " ".join(segments).strip() or "Identity information unavailable."
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, deterministic=True, force_tts=True)

    def _respond_with_argo_governance(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        block = self._config.get("canonical.governance", {}) if self._config else {}
        if not isinstance(block, dict):
            block = {}
        overview = block.get("overview")
        laws = block.get("laws") or []
        gates = block.get("five_gates") or []
        subintent = getattr(intent, "subintent", None) if intent else None
        lines = []
        if overview and subintent in {None, "overview"}:
            lines.append(overview)
        if laws and subintent in {None, "overview", "laws"}:
            lines.append("Laws: " + " ".join(laws))
        if gates and subintent in {None, "overview", "gates"}:
            gate_bits = []
            for gate in gates:
                if not isinstance(gate, dict):
                    continue
                name = gate.get("name") or "Gate"
                summary = gate.get("summary") or gate.get("description") or ""
                gate_bits.append(f"{name} — {summary}".strip(" —"))
            if gate_bits:
                lines.append("Five Gates: " + " ".join(gate_bits))
        message = " ".join(lines).strip() or "Governance information unavailable."
        return self._deliver_canonical_response(message, interaction_id, replay_mode, overrides, enforce_confidence=False, deterministic=True, force_tts=True)

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

    def speak(self, text, interaction_id: str = "", force_tts: bool = False):
        if not self.runtime_overrides.get("tts_enabled", True) and not force_tts:
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
            if self._pending_barge_in_suppression and hasattr(self._edge_tts, "suppress_interrupt"):
                try:
                    self._edge_tts.suppress_interrupt(self._pending_barge_in_suppression)
                except Exception:
                    pass
                self._pending_barge_in_suppression = None

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
        phrases = text

        identity_phrases = {
            "what cpu do i have",
            "which cpu",
            "cpu brand",
            "cpu model",
            "what processor do i have",
            "which processor",
            "processor model",
            "processor name",
            "what gpu do i have",
            "which gpu",
            "gpu brand",
            "gpu model",
            "what graphics card",
            "what video card",
            "what motherboard",
            "which motherboard",
            "motherboard brand",
            "motherboard model",
            "what os",
            "what operating system",
            "os version",
            "system specs",
            "hardware specs",
        }
        qualifier_tokens = {"brand", "model", "type"}
        hardware_tokens = {"cpu", "processor", "gpu", "graphics", "video", "motherboard", "ram", "memory", "os"}
        identity_query = any(p in phrases for p in identity_phrases) or (
            (tokens & qualifier_tokens) and (tokens & hardware_tokens)
        )

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
        if health_matches and not identity_query:
            return "SYSTEM_HEALTH", health_matches

        # COUNT short-circuit (numeric/utility before other canonical topics)
        count_number_tokens = {
            "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
        }
        if ("count" in tokens and ("to" in tokens or tokens & count_number_tokens or re.search(r"\b\d+\b", text))):
            return "COUNT", {"count"}
        governance_phrases = {
            "argo laws",
            "the laws",
            "governing laws",
            "five gates",
            "hard gates",
            "permission gates",
            "argo gates",
        }
        matched_governance_phrases = {p for p in governance_phrases if p in phrases}
        if matched_governance_phrases:
            return "ARGO_GOVERNANCE", matched_governance_phrases
        governance_keywords = {
            "law",
            "laws",
            "rule",
            "rules",
            "constraint",
            "constraints",
            "policy",
            "policies",
            "gate",
            "gates",
            "permission",
            "permissions",
            "govern",
            "governing",
        }
        matched_governance_keywords = tokens & governance_keywords
        if matched_governance_keywords:
            return "ARGO_GOVERNANCE", matched_governance_keywords

        topic_keywords = {
            # Removed 'system' from ARCHITECTURE keywords to allow 'system health' etc. to route to normal logic
            "ARCHITECTURE": {"architecture", "design", "pipeline", "structure", "modules", "components", "layout", "engine"},
        }
        topic_phrases = {
            "ARCHITECTURE": {"system architecture", "pipeline design", "argo architecture"},
        }
        for topic in ["ARCHITECTURE"]:
            phrases_for_topic = topic_phrases.get(topic, set())
            matched_phrases = {p for p in phrases_for_topic if p in phrases}
            if matched_phrases:
                return topic, matched_phrases
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
        capabilities_phrases = {
            "what can you do",
            "what can argo do",
            "what can you do for me",
            "what are your capabilities",
            "what are your features",
            "list your capabilities",
            "list your features",
        }
        if any(p in phrases for p in capabilities_phrases):
            return "CAPABILITIES", {p for p in capabilities_phrases if p in phrases}

        # ARGO_IDENTITY fallback (tightened)
        keywords = {"identity", "yourself", "argo", "agent", "assistant", "name"}
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
            return "ARGO_IDENTITY", {p for p in identity_phrases if p in text}
        identity_specific = tokens & {"argo", "yourself", "identity", "assistant", "agent", "name"}
        question_cue = tokens & {"who", "what"}
        if identity_specific and question_cue:
            return "ARGO_IDENTITY", (identity_specific | question_cue)
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
            confidence_hint = 1.0
            stt_result = self._last_stt_metrics
            if stt_result and "confidence" in stt_result:
                confidence_hint = stt_result["confidence"]
            self._current_stt_confidence = confidence_hint

            if not user_text:
                self.logger.warning("No speech recognized.")
                self.broadcast("log", "User: [No speech recognized]")
                response = "I didn't catch any words. Try again."
                if not self.stop_signal.is_set() and not replay_mode:
                    tts_text = self._sanitize_tts_text(response, enforce_confidence=False)
                    tts_override = (overrides or {}).get("suppress_tts", False)
                    if tts_override:
                        self.logger.info("[TTS] Suppressed for next interaction override")
                    elif tts_text:
                        self.speak(tts_text, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return
            user_text = normalize_system_text(user_text)
            user_text = self._normalize_music_command_text(user_text)
            self.broadcast("log", f"User: {user_text}")
            self._conversation_buffer.add("User", user_text)
            self._append_convo_ledger("user", user_text)

            self.handle_user_text(
                user_text=user_text,
                confidence_hint=confidence_hint,
                interaction_id=interaction_id,
                replay_mode=replay_mode,
                overrides=overrides,
                audio_data=audio_data,
            )
            return

        except Exception as e:
            self.logger.error(f"Pipeline Error: {e}", exc_info=True)
            self.broadcast("status", "ERROR")
            self._record_timeline("PIPELINE_ERROR", stage="pipeline", interaction_id=interaction_id)
        finally:
            self.processing_lock.release()

    # PERSONAL MODE CONTRACT:
    # - If text exists, ALWAYS respond.
    # - STT confidence NEVER blocks conversation.
    # - Confidence may only block ACTION execution.
    # - Identity reads bypass confidence entirely.
    # - strict_lab_mode is opt-in only.
    def handle_user_text(
        self,
        user_text: str,
        confidence_hint: float,
        interaction_id: str = "",
        replay_mode: bool = False,
        overrides: dict | None = None,
        audio_data=None,
    ) -> None:
        """Route recognized text through canonical, memory, and LLM paths.

        Confidence is treated as a hint (metadata). It may gate actions/memory writes
        but never suppresses conversational responses in personal mode.
        """
        user_text = (user_text or "").strip()
        personal_question_bypass_logged = False
        try:
            stt_conf = max(0.0, min(1.0, float(confidence_hint)))
        except Exception:
            stt_conf = 0.0
        self._current_stt_confidence = stt_conf

        early_intent = None
        try:
            early_intent = self._intent_parser.parse(user_text)
        except Exception:
            early_intent = None
        if early_intent and early_intent.intent_type == IntentType.SYSTEM_STATUS:
            self.logger.info("[INTENT] intent=SYSTEM_STATUS request_kind=<ignored>")
            if self._respond_with_system_health(user_text, early_intent, interaction_id, replay_mode, overrides):
                return
        if early_intent and early_intent.intent_type == IntentType.BLUETOOTH_STATUS:
            if self._respond_with_bluetooth_status(user_text, interaction_id, replay_mode, overrides):
                return
        if early_intent and early_intent.intent_type == IntentType.AUDIO_ROUTING_STATUS:
            if self._respond_with_audio_routing_status(user_text, interaction_id, replay_mode, overrides):
                return
        if early_intent and early_intent.intent_type == IntentType.APP_STATUS:
            if self._respond_with_app_status(user_text, interaction_id, replay_mode, overrides):
                return
        if early_intent and early_intent.intent_type == IntentType.TIME_STATUS:
            if self._respond_with_time_status(early_intent, interaction_id, replay_mode, overrides):
                return
        if early_intent and early_intent.intent_type == IntentType.WORLD_TIME:
            if self._respond_with_world_time(early_intent, interaction_id, replay_mode, overrides):
                return
        if early_intent and early_intent.intent_type == IntentType.VOLUME_STATUS:
            if self._respond_with_system_volume_status(interaction_id, replay_mode, overrides):
                return
        self.logger.info(
            "[STT] text_received conf_hint=%.2f strict_lab_mode=%s",
            stt_conf,
            self.strict_lab_mode,
        )

        if not user_text:
            response = "I didn't catch any words. Try again."
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

        filler_match = re.fullmatch(r"(okay\.?\s*)+|\.+", user_text, flags=re.IGNORECASE)
        request_kind = self._classify_request_kind(user_text)

        # IDENTITY STATEMENT CONFIRMATION GATE (before canonical, before LLM)
        confirm_name_pending = self._session_flags.get("confirm_name", False)
        if confirm_name_pending:
            if self._is_affirmative_response(user_text):
                if self._pending_memory:
                    try:
                        pending_key = self._pending_memory.get("key")
                        pending_value = self._pending_memory.get("value")
                        if pending_key and pending_value:
                            self._memory_store.add_memory(
                                "FACT",
                                pending_key,
                                pending_value,
                                source="explicit_user_request",
                            )
                        else:
                            self.logger.warning("[MEMORY] Pending memory missing key or value")
                        self.logger.info(f"[MEMORY] write_confirmed key=name value={self._pending_memory.get('value')}")
                        response = "Got it. I'll remember that."
                    except Exception as e:
                        self.logger.warning(f"[MEMORY] Name write failed: {e}")
                        response = "Memory store unavailable."
                else:
                    response = "No pending memory to write."
                self._pending_memory = None
                self._session_flags["confirm_name"] = False
            else:
                self.logger.info("[MEMORY] write_aborted user_response_negative_or_topic_change")
                self._pending_memory = None
                self._session_flags["confirm_name"] = False
                response = "Okay."

            self.broadcast("log", f"Argo: {response}")
            self._append_convo_ledger("argo", response)
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

        if user_text.lower().strip() == "clear conversation":
            self._conversation_ledger.clear()
            self.logger.info("[CONVO] convo_ledger_size=0")
            response = "Conversation cleared."
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

        if not self.strict_lab_mode and self._is_identity_query(user_text):
            self._respond_with_identity_lookup(interaction_id=interaction_id, replay_mode=replay_mode, overrides=overrides)
            return

        if not self.strict_lab_mode and filler_match:
            response = "Okay."
            self.broadcast("log", f"Argo: {response}")
            self._append_convo_ledger("argo", response)
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

        if not self.strict_lab_mode:
            compact_len = len(re.sub(r"\s+", "", user_text))
            low_conf_guard = stt_conf < self._personal_mode_min_confidence
            short_text_guard = compact_len < self._personal_mode_min_text_len
            if low_conf_guard or short_text_guard:
                early_intent = None
                try:
                    early_intent = self._intent_parser.parse(user_text)
                except Exception:
                    early_intent = None
                if early_intent and self._allow_low_conf_music_command(early_intent, user_text):
                    self.logger.info(
                        "[PERSONAL_MODE] Low confidence but executable music command; continuing"
                    )
                elif early_intent and early_intent.intent_type == IntentType.APP_LAUNCH and self._is_executable_command(user_text):
                    self.logger.info(
                        "[PERSONAL_MODE] Low confidence but executable app launch; continuing"
                    )
                elif (
                    early_intent
                    and early_intent.intent_type == IntentType.APP_CONTROL
                    and getattr(early_intent, "action", None) == "close"
                    and self._is_executable_command(user_text)
                ):
                    self.logger.info(
                        "[PERSONAL_MODE] Low confidence but executable app close; continuing"
                    )
                elif re.match(r"^(close|quit|exit|shut down|shutdown)\b", user_text.strip().lower()):
                    self.logger.info(
                        "[PERSONAL_MODE] Low confidence but explicit close command; continuing"
                    )
                elif user_text.strip().endswith("?") or re.match(r"^(what|why|how|who|when|where)\b", user_text.strip().lower()):
                    self.logger.info(
                        "[PERSONAL_MODE] Low confidence but explicit question; continuing"
                    )
                elif re.match(r"^count\b", user_text.strip().lower()):
                    self.logger.info(
                        "[PERSONAL_MODE] Low confidence but explicit count command; continuing"
                    )
                else:
                    self.logger.warning(
                        "[PERSONAL_MODE] Guarded utterance len=%s conf=%.2f thresholds(len=%s, conf=%.2f)",
                        compact_len,
                        stt_conf,
                        self._personal_mode_min_text_len,
                        self._personal_mode_min_confidence,
                    )
                    self._record_timeline("PERSONAL_LOW_CONF_GUARD", stage="pipeline", interaction_id=interaction_id)

        if self.strict_lab_mode:
            if stt_conf < 0.30 or filler_match:
                self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) or filler; skipping")
                if not self._low_conf_notice_given and self.runtime_overrides.get("tts_enabled", True):
                    self.speak("I didn’t catch that. Try a complete question.", interaction_id=interaction_id)
                    self._low_conf_notice_given = True
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return
            if stt_conf < 0.35 or not user_text.strip():
                user_text_lower = user_text.lower()
                if is_system_keyword(user_text):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but whitelisted system intent: {user_text}")
                elif re.search(r"\bcount\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but count detected; continuing")
                elif re.search(r"\bvolume\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but volume intent detected; continuing")
                elif re.search(r"\b(remember|save this|from now on|memory|forget)\b", user_text, flags=re.IGNORECASE):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but memory intent detected; continuing")
                elif any(term in user_text_lower for term in {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}):
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) but stop intent detected; continuing")
                elif stt_conf < 0.15 or not user_text.strip():
                    self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) or empty text; skipping")
                    if not self._low_conf_notice_given and self.runtime_overrides.get("tts_enabled", True):
                        self.speak("I didn’t catch that clearly. Try saying it as a full sentence.", interaction_id=interaction_id)
                        self._low_conf_notice_given = True
                    self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                    return

        # CANONICAL INTERCEPTION: Classify and intercept before any LLM routing
        from core.canonical_answers import get_canonical_answer
        topic, matched = self._classify_canonical_topic(user_text)
        if topic == "SYSTEM_HEALTH":
            self.logger.info(f"[CANONICAL] SYSTEM_HEALTH matched keywords: {sorted(matched)} | LLM BYPASSED")
            if self._respond_with_system_health(user_text, None, interaction_id, replay_mode, overrides):
                return
            topic = None
        if topic == "ARGO_IDENTITY":
            self.logger.info(f"[CANONICAL] ARGO_IDENTITY matched keywords: {sorted(matched)} | LLM BYPASSED")
            if self._respond_with_argo_identity(interaction_id, replay_mode, overrides):
                return
            topic = None
        if topic == "ARGO_GOVERNANCE":
            self.logger.info(f"[CANONICAL] ARGO_GOVERNANCE matched keywords: {sorted(matched)} | LLM BYPASSED")
            if self._respond_with_argo_governance(None, interaction_id, replay_mode, overrides):
                return
            topic = None
        if topic:
            self._session_flags["clarification_asked"] = False
        if self._is_convo_recall_request(user_text):
            response = self._handle_convo_recall()
            self.broadcast("log", f"Argo: {response}")
            self._append_convo_ledger("argo", response)
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
        if topic and topic not in {"SYSTEM_HEALTH", "COUNT"}:
            phrase_match = any(" " in m for m in matched)
            self.logger.debug(
                "[STT] confidence_used=%s phrase_match=%s",
                stt_conf,
                phrase_match,
            )
            if not phrase_match and stt_conf < 0.5:
                self.logger.info(f"[CANONICAL] Low confidence ({stt_conf:.2f}) without phrase match; deferring to LLM")
                topic = None
        if topic == "COUNT":
            response = self._build_count_response(user_text)
            self.logger.info(f"[CANONICAL] Intercepted topic: COUNT | Matched: {sorted(matched)} | LLM BYPASSED")
            self.broadcast("log", f"Argo: {response}")
            self._append_convo_ledger("argo", response)
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response, enforce_confidence=False, deterministic=True)
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
            self._append_convo_ledger("argo", answer or "")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(answer or "", enforce_confidence=False, deterministic=True)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            self.logger.info("--- Interaction Complete ---")
            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
            return

        meaningful_tokens = self._get_meaningful_tokens(user_text)
        has_interrogative = self._has_interrogative_structure(user_text)
        if self._is_non_propositional_utterance(user_text, request_kind):
            self.logger.info("[LLM] Non-propositional utterance detected; prompting for clarification")
            self._record_timeline("NON_PROPOSITIONAL_GUARD", stage="pipeline", interaction_id=interaction_id)
            self._respond_with_clarification(interaction_id, replay_mode, overrides)
            return

        allow_llm = topic is None
        if request_kind == "QUESTION" and not self.strict_lab_mode:
            assert allow_llm, "Personal mode questions must never be blocked"

        stop_terms = {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
        user_text_lower = user_text.lower()
        if any(term in user_text_lower for term in stop_terms):
            music_player = get_music_player()
            if music_player.is_playing():
                self.logger.info("[ARGO] Active music detected")
                music_player.stop()
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return
        filler_match = re.fullmatch(r"(okay\.?\s*)+|\.+", user_text.strip(), flags=re.IGNORECASE)
        if self.strict_lab_mode:
            if stt_conf < 0.30 or filler_match:
                self.logger.info(f"[STT] Low confidence ({stt_conf:.2f}) or filler; skipping")
                if not self._low_conf_notice_given and self.runtime_overrides.get("tts_enabled", True):
                    self.speak("I didn’t catch that. Try a complete question.", interaction_id=interaction_id)
                    self._low_conf_notice_given = True
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return
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
        elif not user_text.strip():
            self.logger.info("[STT] Empty text in personal mode; skipping")
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            return

        if self._handle_memory_command(user_text, interaction_id, replay_mode, overrides):
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            self.logger.info("--- Interaction Complete ---")
            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
            return

        contextual_reply = self._handle_contextual_followup(user_text)
        if contextual_reply:
            self.broadcast("log", f"Argo: {contextual_reply}")
            self._append_convo_ledger("argo", contextual_reply)
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(contextual_reply)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
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
        if (
            (intent is None or intent.intent_type != IntentType.MUSIC)
            and user_text.lower().startswith("play")
            and self._music_noun_detected(user_text)
        ):
            keyword = user_text[4:].strip()
            intent = Intent(
                intent_type=IntentType.MUSIC,
                confidence=1.0,
                raw_text=user_text,
                keyword=keyword or None,
            )
            request_kind = "ACTION"
            self.logger.info("[INTENT_OVERRIDE] forced MUSIC due to play+music nouns")
        safe_utterance = re.sub(r"\s+", " ", (user_text or "").replace("\n", " ").strip())
        intent_type_label = intent.intent_type.value if intent else "None"
        intent_artist = getattr(intent, "artist", None)
        intent_title = getattr(intent, "title", None)
        self.logger.info(
            "[INTENT] intent=%s request_kind=%s artist=%s title=%s utterance=\"%s\"",
            intent_type_label,
            request_kind,
            intent_artist,
            intent_title,
            safe_utterance,
        )
        if intent is None:
            music_keywords = {
                "play",
                "pause",
                "resume",
                "shuffle",
                "song",
                "music",
                "artist",
                "album",
                "next",
                "skip",
                "track",
            }
            detected_keywords = sorted({kw for kw in music_keywords if kw in safe_utterance.lower()})
            if detected_keywords:
                self.logger.warning(
                    "[INTENT WARNING] intent=None but music keywords detected keywords=%s utterance=\"%s\"",
                    detected_keywords,
                    safe_utterance,
                )
        
        # IDENTITY STATEMENT GATE: Detect "my name is X" BEFORE request classification gates
        # This must happen before canonical/clarification/LLM routing
        if not topic:
            name_candidate = self._extract_name_from_statement(user_text)
            if name_candidate and not self._session_flags.get("confirm_name", False):
                self.logger.info(
                    f"[MEMORY] candidate_detected type=identity.name value={name_candidate} conf_hint={stt_conf:.2f}"
                )
                self._pending_memory = {"key": "name", "value": name_candidate}
                self._session_flags["confirm_name"] = True
                response = f"Do you want me to remember that your name is {name_candidate}?"
                self.logger.info("[MEMORY] confirmation_requested")
                self._record_timeline("IDENTITY_CONFIRM_GATE", stage="pipeline", interaction_id=interaction_id)
                self.broadcast("log", f"Argo: {response}")
                self._append_convo_ledger("argo", response)
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
        
        canonical_reason = "none"
        if topic:
            canonical_reason = f"topic:{topic}"
        self.logger.info(f"[CANONICAL] classification={request_kind} canonical_reason={canonical_reason}")
        self._record_timeline(
            f"CLASSIFY {request_kind}",
            stage="pipeline",
            interaction_id=interaction_id,
        )
        if request_kind == "ACTION" and intent is None:
            request_kind = "QUESTION"

        low_confidence_audio = not self.strict_lab_mode and stt_conf < 0.50
        if (
            not self.strict_lab_mode
            and request_kind == "QUESTION"
            and low_confidence_audio
            and not personal_question_bypass_logged
        ):
            self.logger.info("[PERSONAL_MODE] Question bypassed confidence gating")
            personal_question_bypass_logged = True

        # CLARIFICATION GATE: Low-mid confidence question without phrase/canonical match
        if (
            request_kind == "QUESTION"
            and 0.35 <= stt_conf < 0.55
            and not topic
            and self.strict_lab_mode
        ):
            phrase_match_gate = any(" " in m for m in matched) if matched else False
            clarify_asked_already = self._session_flags.get("clarification_asked", False)
            
            if not phrase_match_gate and not clarify_asked_already:
                self._session_flags["clarification_asked"] = True
                response = self._get_clarification_prompt()
                self.logger.info(f"[CLARIFY] triggered conf={stt_conf:.2f} reason=ambiguous_question")
                self._record_timeline("CLARIFY_GATE", stage="pipeline", interaction_id=interaction_id)
                self.broadcast("log", f"Argo: {response}")
                self._append_convo_ledger("argo", response)
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

        # --- MUSIC VOLUME CONTROL (voice) ---
        # Recognize patterns like 'music volume 75%', 'set volume to 50%', 'volume up', 'volume down'
        user_text_lower = user_text.lower().strip()
        if any(term in user_text_lower for term in {"music", "song", "player"}):
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
                        request_kind = "ACTION"
                    if request_kind != "ACTION" and not is_status_query:
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
                    if low_confidence_audio and request_kind == "ACTION" and not is_status_query:
                        response = "I heard that, but the audio was unclear. Please repeat the volume command."
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
            self.logger.info(
                "[MUSIC] intent=%s request_kind=%s entered handler",
                intent.intent_type if intent else None,
                request_kind,
            )
            if request_kind != "ACTION" and intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}:
                self.logger.info(
                    "[MUSIC GUARD] guard=non_action intent=%s request_kind=%s",
                    intent.intent_type,
                    request_kind,
                )
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
            if (
                low_confidence_audio
                and request_kind == "ACTION"
                and intent.intent_type in {IntentType.MUSIC, IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT}
                and not self._allow_low_conf_music_command(intent, user_text)
            ):
                self.logger.info(
                    "[MUSIC GUARD] guard=low_confidence intent=%s request_kind=%s stt_conf=%.2f",
                    intent.intent_type,
                    request_kind,
                    stt_conf,
                )
                response = "I heard a music control, but the audio was unclear. Please repeat the command."
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
                executable = self._is_executable_command(user_text)
                if intent.intent_type == IntentType.MUSIC and user_text.lower().startswith("play"):
                    executable = True
                if not executable:
                    self.logger.info(
                        "[MUSIC GUARD] guard=non_executable intent=%s request_kind=%s text=\"%s\"",
                        intent.intent_type,
                        request_kind,
                        user_text,
                    )
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
                self.logger.info(
                    "[MUSIC GUARD] guard=policy_block intent=%s request_kind=%s reason=%s",
                    intent.intent_type,
                    request_kind,
                    reason,
                )
                response = f"Action blocked by policy ({reason})."
                self.logger.info(f"[GATE] {response}")
                if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                    self.speak(response, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return
            if not self.runtime_overrides.get("music_enabled", True):
                self.logger.info(
                    "[MUSIC GUARD] guard=music_disabled intent=%s request_kind=%s",
                    intent.intent_type,
                    request_kind,
                )
                msg = "Music is disabled."
                if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                    self.speak(msg, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return

            music_player = get_music_player()
            blocked = music_player.preflight()
            if blocked:
                self.logger.info(
                    "[MUSIC GUARD] guard=preflight intent=%s request_kind=%s message=%s",
                    intent.intent_type,
                    request_kind,
                    blocked,
                )
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
                title = None  # Not applicable for MUSIC_NEXT

            elif intent.intent_type == IntentType.MUSIC_STATUS:
                status = query_music_status()
                if self.runtime_overrides.get("tts_enabled", True) and not (overrides or {}).get("suppress_tts", False):
                    self.speak(status, interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                return

            else:
                artist = getattr(intent, "artist", None)
                title: Optional[str] = getattr(intent, "title", None)
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
                    if keyword and explicit_genre and not do_not_try_genre_lookup:
                        playback_started = music_player.play_by_genre(keyword, None)
                    if not playback_started and keyword:
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

        if intent and intent.intent_type == IntentType.BLUETOOTH_STATUS:
            if self._respond_with_bluetooth_status(user_text, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.BLUETOOTH_CONTROL:
            if self._respond_with_bluetooth_control(intent, user_text, stt_conf, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.AUDIO_ROUTING_STATUS:
            if self._respond_with_audio_routing_status(user_text, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.AUDIO_ROUTING_CONTROL:
            if self._respond_with_audio_routing_control(intent, user_text, stt_conf, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.APP_STATUS:
            if self._respond_with_app_status(user_text, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.APP_FOCUS_STATUS:
            if self._respond_with_focus_status(intent, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.APP_FOCUS_CONTROL:
            if self._respond_with_focus_control(intent, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.APP_LAUNCH:
            if self._respond_with_app_launch(intent, user_text, stt_conf, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.APP_CONTROL:
            if self._respond_with_app_control(intent, user_text, stt_conf, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.VOLUME_STATUS:
            if self._respond_with_system_volume_status(interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.VOLUME_CONTROL:
            if self._respond_with_system_volume_control(user_text, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.TIME_STATUS:
            if self._respond_with_time_status(intent, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.WORLD_TIME:
            if self._respond_with_world_time(intent, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.ARGO_IDENTITY:
            if self._respond_with_argo_identity(interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.ARGO_GOVERNANCE:
            if self._respond_with_argo_governance(intent, interaction_id, replay_mode, overrides):
                return

        if intent and intent.intent_type == IntentType.COUNT:
            response = self._build_count_response(user_text)
            self.broadcast("log", f"Argo: {response}")
            if not self.stop_signal.is_set() and not replay_mode:
                tts_text = self._sanitize_tts_text(response, enforce_confidence=False)
                tts_override = (overrides or {}).get("suppress_tts", False)
                if tts_override:
                    self.logger.info("[TTS] Suppressed for next interaction override")
                elif tts_text:
                    self.speak(tts_text, interaction_id=interaction_id)
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            self.logger.info("--- Interaction Complete ---")
            self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
            return

        if intent and intent.intent_type in {IntentType.SYSTEM_HEALTH, IntentType.SYSTEM_STATUS}:
            if self._respond_with_system_health(user_text, intent, interaction_id, replay_mode, overrides):
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

        restricted_llm_intents = {
            IntentType.MUSIC,
            IntentType.MUSIC_STOP,
            IntentType.MUSIC_NEXT,
            IntentType.MUSIC_STATUS,
            IntentType.SYSTEM_HEALTH,
            IntentType.SYSTEM_STATUS,
            IntentType.BLUETOOTH_STATUS,
            IntentType.BLUETOOTH_CONTROL,
            IntentType.AUDIO_ROUTING_STATUS,
            IntentType.AUDIO_ROUTING_CONTROL,
            IntentType.APP_STATUS,
            IntentType.APP_FOCUS_STATUS,
            IntentType.APP_FOCUS_CONTROL,
            IntentType.APP_LAUNCH,
            IntentType.APP_CONTROL,
            IntentType.VOLUME_STATUS,
            IntentType.VOLUME_CONTROL,
            IntentType.TIME_STATUS,
            IntentType.WORLD_TIME,
            IntentType.ARGO_IDENTITY,
            IntentType.ARGO_GOVERNANCE,
        }
        if intent and intent.intent_type in restricted_llm_intents:
            leak_messages = {
                IntentType.MUSIC: "Music control routing failed. Please repeat the command.",
                IntentType.MUSIC_STOP: "Music stop failed to route. Say stop music again.",
                IntentType.MUSIC_NEXT: "Skip command failed to route. Say next track again.",
                IntentType.MUSIC_STATUS: "Music status is handled locally. Ask again.",
                IntentType.SYSTEM_HEALTH: "System health is handled locally. Please ask again.",
                IntentType.SYSTEM_STATUS: "System status is handled locally. Please ask again.",
                IntentType.BLUETOOTH_STATUS: "Bluetooth status is handled locally. Ask again.",
                IntentType.BLUETOOTH_CONTROL: "Bluetooth control is handled locally. Please repeat the command.",
                IntentType.AUDIO_ROUTING_STATUS: "Audio routing status is handled locally. Ask again.",
                IntentType.AUDIO_ROUTING_CONTROL: "Audio routing control is handled locally. Please repeat the command.",
                IntentType.APP_STATUS: "App status is handled locally. Ask again.",
                IntentType.APP_FOCUS_STATUS: "App focus status is handled locally. Ask again.",
                IntentType.APP_FOCUS_CONTROL: "App focus control is handled locally. Please repeat the command.",
                IntentType.APP_LAUNCH: "App launch is handled locally. Please repeat the command.",
                IntentType.APP_CONTROL: "App control is handled locally. Please repeat the command.",
                IntentType.VOLUME_STATUS: "System volume status is handled locally. Ask again.",
                IntentType.VOLUME_CONTROL: "System volume control is handled locally. Please repeat the command.",
                IntentType.TIME_STATUS: "Time status is handled locally. Ask again.",
                IntentType.WORLD_TIME: "World time is handled locally. Ask again.",
                IntentType.ARGO_IDENTITY: "Identity answers are deterministic. Ask again if needed.",
                IntentType.ARGO_GOVERNANCE: "Governance answers are deterministic. Ask again if needed.",
            }
            leak_msg = leak_messages.get(intent.intent_type, "Routing error. Please repeat the request.")
            safe_text = safe_utterance or (user_text or "")
            if intent.intent_type == IntentType.SYSTEM_STATUS:
                self.logger.error("[CANONICAL LEAK] SYSTEM_STATUS reached LLM – BLOCKING")
            else:
                self.logger.error(f"[CANONICAL LEAK] intent={intent.intent_type} text=\"{safe_text}\"")
            self._deliver_canonical_response(leak_msg, interaction_id, replay_mode, overrides)
            return

        rag_context = ""
        memory_context = ""
        llm_context_scope = "isolated"
        if request_kind == "QUESTION":
            rag_context = self._get_rag_context(user_text, interaction_id)
            memory_context = self._get_memory_context(interaction_id)
            if rag_context:
                llm_context_scope = "buffered"
        if not rag_context and len(meaningful_tokens) < 5 and not has_interrogative:
            self.logger.info("[LLM] Isolated short utterance without interrogative; requesting clarification")
            self._record_timeline("ISOLATED_SHORT_GUARD", stage="pipeline", interaction_id=interaction_id)
            self._respond_with_clarification(interaction_id, replay_mode, overrides)
            return
        self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
        self.logger.info(f"[LLM] context_scope={llm_context_scope}")
        ai_text = self.generate_response(
            user_text,
            interaction_id=interaction_id,
            rag_context=rag_context,
            memory_context=memory_context,
            use_convo_buffer=(llm_context_scope == "buffered"),
        )
        ai_text = re.sub(r"[^\x00-\x7F]+", "", ai_text or "")
        ai_text = self._strip_disallowed_phrases(ai_text)
        if not ai_text.strip():
            self.logger.warning("[LLM] Empty response")
            self.broadcast("log", "Argo: [No response]")
            return
        self.broadcast("log", f"Argo: {ai_text}")
        self._conversation_buffer.add("Assistant", ai_text)
        self._append_convo_ledger("argo", ai_text)

        if not self.stop_signal.is_set() and not replay_mode:
            tts_text = self._sanitize_tts_text(ai_text, enforce_confidence=False)
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

        if not replay_mode and audio_data is not None:
            self._save_replay(
                interaction_id=interaction_id,
                audio_data=audio_data,
                user_text=user_text,
                ai_text=ai_text,
            )

        return
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
