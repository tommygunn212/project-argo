
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
import concurrent.futures
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
from core.sound_cues import get_sound_cue_player
from core.config import (
    get_runtime_overrides,
    get_config,
    MIN_TTS_CONFIDENCE,
    MIN_TTS_TEXT_LEN,
    PERSONAL_MODE_MIN_CONFIDENCE,
    PERSONAL_MODE_MIN_TEXT_LEN,
    MEMORY_MIN_CONFIDENCE,
    ResponseStyle,
    ActionRisk,
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
from core.app_control import (
    WRITABLE_APPS,
    app_status_response,
    open_app,
    close_app_deterministic,
    focus_app_deterministic,
    get_active_app,
    is_app_running,
    write_text_to_app,
)
from core.app_registry import APP_REGISTRY
from core.system_volume import get_status as get_system_volume_status, set_volume_percent as set_system_volume_percent, adjust_volume_percent as adjust_system_volume_percent, mute_volume as mute_system_volume, unmute_volume as unmute_system_volume
from core.app_launch import get_supported_launch_displays, launch_app, resolve_app_launch_target
from core.app_registry import get_supported_app_displays, resolve_app_name

# TTS bypass reason for deterministic commands (for logging/debugging)
TTS_ALLOWED_REASON_DETERMINISTIC = "DETERMINISTIC_CONFIDENCE_BYPASS"
from core.memory_store import get_memory_store
from core.mem0_memory import get_mem0_memory
from core.conversation_buffer import ConversationBuffer
from core.brain import get_brain
from core.registries import is_capability_enabled, is_permission_allowed, is_module_enabled
from core.runtime_constants import GATES_ORDER, Gate
from tools.home_assistant import execute_smart_home_command
from core.personality import format_response as personality_format_response, get_personality_state
from core.pipeline_memory import PipelineMemoryService
from core.memory_command_service import MemoryCommandService
from core.pipeline_domain_dispatch import dispatch_domain_intent
from core.pipeline_platform_dispatch import dispatch_early_status, dispatch_platform_intent
from core.pipeline_music_volume import dispatch_music_volume
from core.pipeline_music_dispatch import dispatch_music_intent
from core.pipeline_system_info import dispatch_system_info
from core.pipeline_system_health import respond_with_system_health
from core.pipeline_topic_classifier import classify_canonical_topic
from core.pipeline_self_diagnostics import respond_with_self_diagnostics
from core.pipeline_draft_responses import PipelineDraftResponseService
from core.pipeline_scheduling_responses import PipelineSchedulingService
from core.pipeline_inspection_responses import PipelineInspectionService
from core.pipeline_task_planning import PipelineTaskPlanningService
from core.pipeline_writing_responses import PipelineWritingResponseService
from core.pipeline_restricted_fallback import block_restricted_llm_fallback
from core.pipeline_special_dispatch import dispatch_special_intent
from core.pipeline_llm_stage import run_llm_stage
from core.pipeline_conversation_gates import dispatch_conversation_gate
from core.pipeline_confidence_gate import apply_confidence_gate
from core.pipeline_canonical_stage import run_canonical_stage
from core.pipeline_pre_intent_gates import dispatch_pre_intent_gate
from core.pipeline_intent_stage import prepare_intent_stage
from core import system_response_formatter as system_format
from core.knowledge_answer_guard import enforce_knowledge_answer

# Persona module - text transformers gated by response type
from personas import ResponseType, apply_persona, PERSONA_REGISTRY
# Import all persona modules to register them
from personas import neutral, rick, claptrap, jarvis, tommy_gunn, tommy_mix, plain

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
        self.tts_finished_at = 0.0  # time.time() when TTS last stopped (for echo guard)
        self.current_interaction_id = ""
        self.illegal_transition_details = None
        self.timeline_events = []
        self.runtime_overrides = get_runtime_overrides()
        try:
            self._config = get_config()
        except Exception:
            self._config = None
        self.sound_cues = get_sound_cue_player(self._config)
        from core.voice_clients import VoiceClients
        from core.bounded_context import BoundedContext
        from core.llm_router import LLMRouter
        self._voice_clients = VoiceClients(self._config)
        self._llm_router = LLMRouter(self._config, self._voice_clients)
        self._context_fetcher = BoundedContext()
        self._current_stt_confidence = 1.0
        self._tts_min_text_length = MIN_TTS_TEXT_LEN
        self._tts_min_confidence = MIN_TTS_CONFIDENCE
        self._personal_mode_min_confidence = PERSONAL_MODE_MIN_CONFIDENCE
        self._personal_mode_min_text_len = PERSONAL_MODE_MIN_TEXT_LEN
        self._intent_parser = RuleBasedIntentParser()
        self._inspection_responses = PipelineInspectionService(self)
        self._scheduling_responses = PipelineSchedulingService(self)
        self._task_planning = PipelineTaskPlanningService(self)
        self._draft_responses = PipelineDraftResponseService(self)
        self._writing_responses = PipelineWritingResponseService(self)
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
            "IDLE": {"LISTENING", "THINKING"},  # THINKING for text input when idle
            "LISTENING": {"TRANSCRIBING", "THINKING"},  # THINKING for text input (skips STT)
            "TRANSCRIBING": {"THINKING", "LISTENING", "IDLE"},
            "THINKING": {"SPEAKING", "LISTENING", "IDLE"},
            "SPEAKING": {"LISTENING", "IDLE", "THINKING"},  # THINKING for text barge-in
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
        # OpenAI TTS voice map (for personal mode)
        self.openai_voices = {
            "nova": "nova",
            "alloy": "alloy",
            "echo": "echo",
            "fable": "fable",
            "onyx": "onyx",
            "shimmer": "shimmer",
            "ash": "ash",
            "sage": "sage",
            "coral": "coral",
            "ballad": "ballad",
            "verse": "verse",
            "marin": "marin",
            "cedar": "cedar",
        }
        self.current_voice_key = "ryan"
        self._tts_engine = "edge"  # "edge" or "openai"
        self._tts_model = "tts-1"  # Tracked so UI overrides can reinit
        self._edge_tts = None
        self._openai_tts = None
        self._pending_barge_in_suppression = None
        self._TTS_INSTRUCTIONS = (
            "Sound natural, warm, and lightly brisk. "
            "Keep the pacing smooth and conversational with subtle emphasis and short natural pauses. "
            "Do not sound like an announcer, a customer service script, or a cartoon character. "
            "Do not overplay jokes or punchlines. Stay grounded, human, and relaxed."
        )
        self._memory_store = get_memory_store()
        self._mem0_memory = get_mem0_memory()
        if getattr(self._mem0_memory, "enabled", False):
            self.logger.info("[MEM0] enabled")
        self._ephemeral_memory = {}
        self._brain = get_brain()
        convo_size = 24
        try:
            if self._config is not None:
                convo_size = int(self._config.get("conversation.buffer_size", 24))
        except Exception:
            convo_size = 24
        session_memory_enabled = self.runtime_overrides.get("session_memory_enabled", True)
        self._conversation_buffer = ConversationBuffer(max_turns=convo_size, enabled=session_memory_enabled)
        ledger_size = 10
        try:
            if self._config is not None:
                ledger_size = int(self._config.get("conversation.ledger_size", 10))
        except Exception:
            ledger_size = 10
        self._conversation_ledger = deque(maxlen=ledger_size)
        self._pending_memory_write = None
        self._pending_memory = None
        self._memory_commands = MemoryCommandService(self)
        self._memory_service = PipelineMemoryService(self)
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

    def _respond_with_vision_describe(self, *args, **kwargs):
        return self._inspection_responses._respond_with_vision_describe(*args, **kwargs)

    def _respond_with_vision_read_error(self, *args, **kwargs):
        return self._inspection_responses._respond_with_vision_read_error(*args, **kwargs)

    def _respond_with_vision_question(self, *args, **kwargs):
        return self._inspection_responses._respond_with_vision_question(*args, **kwargs)

    def _respond_with_file_search(self, *args, **kwargs):
        return self._inspection_responses._respond_with_file_search(*args, **kwargs)

    def _respond_with_file_large(self, *args, **kwargs):
        return self._inspection_responses._respond_with_file_large(*args, **kwargs)

    def _respond_with_file_recent(self, *args, **kwargs):
        return self._inspection_responses._respond_with_file_recent(*args, **kwargs)

    def _respond_with_file_info(self, *args, **kwargs):
        return self._inspection_responses._respond_with_file_info(*args, **kwargs)

    def _respond_with_set_reminder(self, *args, **kwargs):
        return self._scheduling_responses._respond_with_set_reminder(*args, **kwargs)

    def _respond_with_list_reminders(self, *args, **kwargs):
        return self._scheduling_responses._respond_with_list_reminders(*args, **kwargs)

    def _respond_with_cancel_reminder(self, *args, **kwargs):
        return self._scheduling_responses._respond_with_cancel_reminder(*args, **kwargs)

    def _respond_with_calendar_add(self, *args, **kwargs):
        return self._scheduling_responses._respond_with_calendar_add(*args, **kwargs)

    def _respond_with_calendar_query(self, *args, **kwargs):
        return self._scheduling_responses._respond_with_calendar_query(*args, **kwargs)

    def _respond_with_cancel_calendar(self, *args, **kwargs):
        return self._scheduling_responses._respond_with_cancel_calendar(*args, **kwargs)

    def _respond_with_task_plan(self, *args, **kwargs):
        return self._task_planning._respond_with_task_plan(*args, **kwargs)

    def _build_plan_executor(self, *args, **kwargs):
        return self._task_planning._build_plan_executor(*args, **kwargs)

    def _respond_with_list_drafts(self, *args, **kwargs):
        return self._draft_responses._respond_with_list_drafts(*args, **kwargs)

    def _respond_with_read_draft(self, *args, **kwargs):
        return self._draft_responses._respond_with_read_draft(*args, **kwargs)

    def _respond_with_send_email(self, *args, **kwargs):
        return self._draft_responses._respond_with_send_email(*args, **kwargs)

    def _respond_with_search_docs(self, *args, **kwargs):
        return self._draft_responses._respond_with_search_docs(*args, **kwargs)

    def _respond_with_export_data(self, *args, **kwargs):
        return self._draft_responses._respond_with_export_data(*args, **kwargs)

    def _writing_llm_call(self, *args, **kwargs):
        return self._writing_responses._writing_llm_call(*args, **kwargs)

    def _respond_with_write_email(self, *args, **kwargs):
        return self._writing_responses._respond_with_write_email(*args, **kwargs)

    def _respond_with_write_document(self, *args, **kwargs):
        return self._writing_responses._respond_with_write_document(*args, **kwargs)

    def _respond_with_write_blog(self, *args, **kwargs):
        return self._writing_responses._respond_with_write_blog(*args, **kwargs)

    def _respond_with_write_note(self, *args, **kwargs):
        return self._writing_responses._respond_with_write_note(*args, **kwargs)

    def _respond_with_edit_draft(self, *args, **kwargs):
        return self._writing_responses._respond_with_edit_draft(*args, **kwargs)

    def _append_convo_ledger(self, *args, **kwargs):
        return self._memory_service._append_convo_ledger(*args, **kwargs)

    def _get_previous_user_entry(self, *args, **kwargs):
        return self._memory_service._get_previous_user_entry(*args, **kwargs)

    def _is_convo_recall_request(self, *args, **kwargs):
        return self._memory_service._is_convo_recall_request(*args, **kwargs)

    def _handle_convo_recall(self, *args, **kwargs):
        return self._memory_service._handle_convo_recall(*args, **kwargs)

    def _find_color_statement(self, *args, **kwargs):
        return self._memory_service._find_color_statement(*args, **kwargs)

    def _handle_contextual_followup(self, *args, **kwargs):
        return self._memory_service._handle_contextual_followup(*args, **kwargs)

    def _get_project_namespace(self, *args, **kwargs):
        return self._memory_service._get_project_namespace(*args, **kwargs)

    def _is_sensitive_memory(self, *args, **kwargs):
        return self._memory_service._is_sensitive_memory(*args, **kwargs)

    def _get_memory_context(self, *args, **kwargs):
        return self._memory_service._get_memory_context(*args, **kwargs)

    def _store_mem0_fact(self, *args, **kwargs):
        return self._memory_service._store_mem0_fact(*args, **kwargs)

    def _delete_mem0_matching(self, *args, **kwargs):
        return self._memory_service._delete_mem0_matching(*args, **kwargs)

    def _clear_mem0_user(self, *args, **kwargs):
        return self._memory_service._clear_mem0_user(*args, **kwargs)

    def _store_durable_turn(self, *args, **kwargs):
        return self._memory_service._store_durable_turn(*args, **kwargs)

    def _parse_memory_write(self, *args, **kwargs):
        return self._memory_service._parse_memory_write(*args, **kwargs)

    def _handle_memory_command(self, *args, **kwargs):
        return self._memory_service._handle_memory_command(*args, **kwargs)

    def set_voice(self, voice_key):
        """Switch the TTS voice model."""
        # Check OpenAI voices first (personal mode)
        if voice_key in self.openai_voices:
            self.current_voice_key = voice_key
            self._tts_engine = "openai"
            if self._openai_tts is not None:
                self._openai_tts.set_voice(voice_key)
            self.logger.info(f"Voice switched to OpenAI: {voice_key}")
            self.broadcast("log", f"System: Voice switched to OpenAI {voice_key.upper()}")
            return True
        # Fall back to Edge TTS voices
        if voice_key in self.voices:
            self.current_voice_key = voice_key
            self._tts_engine = "edge"
            if self._edge_tts is not None:
                try:
                    self._edge_tts.voice = self.voices[voice_key]
                except Exception:
                    pass
            self.logger.info(f"Voice switched to {voice_key}: {self.voices[voice_key]}")
            self.broadcast("log", f"System: Voice profile switched to {voice_key.upper()}")
            return True
        return False

    def set_tts_model(self, model: str):
        """Switch the OpenAI TTS model at runtime (e.g. tts-1 → gpt-4o-mini-tts)."""
        valid_models = {"tts-1", "tts-1-hd", "gpt-4o-mini-tts"}
        if model not in valid_models:
            self.logger.warning(f"[TTS] Unknown model: {model}")
            return False
        if model == self._tts_model:
            return True
        self._tts_model = model
        # Force re-creation so next speak() uses the new model
        self._openai_tts = None
        self.logger.info(f"[TTS] Model switched to {model} (will reinit on next speak)")
        self.broadcast("log", f"System: TTS model switched to {model}")
        return True

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
        # Imperative sentences starting with action verbs should pass through to LLM
        imperative_verbs = {"give", "tell", "show", "list", "generate", "create", "make", "find", "get", "pick", "choose", "suggest", "recommend", "explain", "describe", "say", "read", "write", "name", "calculate", "compute"}
        tokens = lower.split()
        if tokens and tokens[0] in imperative_verbs:
            return False
        # Identity/personal statements should pass through (potential memory writes)
        identity_patterns = [
            r"\bmy name is\b",
            r"\bi am called\b",
            r"\bcall me\b",
            r"\bi like\b",
            r"\bi love\b",
            r"\bi prefer\b",
            r"\bi hate\b",
            r"\bi live in\b",
            r"\bi work at\b",
            r"\bi'm from\b",
            r"\bmy favorite\b",
            r"\bmy birthday is\b",
        ]
        if any(re.search(pattern, lower) for pattern in identity_patterns):
            return False
        # Let the LLM handle ambiguous/short input — it's better at
        # requesting clarification naturally than canned quips.
        return False

    def _ambiguous_short_question_prompt(self, text: str, request_kind: str, topic: str | None = None) -> str | None:
        """Ask for grounding before answering terse shorthand like "what is mc2"."""
        if request_kind != "QUESTION" or topic or not self._has_interrogative_structure(text):
            return None
        question_structure = {
            "what",
            "whats",
            "where",
            "when",
            "why",
            "how",
            "who",
            "which",
            "is",
            "are",
            "do",
            "does",
            "did",
            "can",
            "could",
            "would",
            "should",
            "will",
            "mean",
            "means",
            "meaning",
            "many",
            "much",
        }
        meaningful = [token for token in self._get_meaningful_tokens(text) if token not in question_structure]
        if not meaningful or len(meaningful) > 2:
            return None

        known_singletons = {
            "argo",
            "ai",
            "api",
            "cpu",
            "date",
            "day",
            "email",
            "gpu",
            "home",
            "light",
            "lights",
            "memory",
            "music",
            "name",
            "ram",
            "status",
            "system",
            "temperature",
            "time",
            "volume",
            "weather",
        }
        opaque_terms = []
        for token in meaningful:
            if token in known_singletons:
                continue
            has_alpha = bool(re.search(r"[a-z]", token))
            has_digit = bool(re.search(r"\d", token))
            is_short_code = len(token) <= 4 and has_alpha
            is_mixed_code = len(token) <= 8 and has_alpha and has_digit
            if is_short_code or is_mixed_code:
                opaque_terms.append(token)

        if not opaque_terms:
            return None
        term = opaque_terms[0]
        return f"When you say '{term}', do you mean something from ARGO or your setup, or the general meaning?"

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
        # Pronunciation fixes for TTS
        cleaned = re.sub(r"\bArgo\b", "Ar-go", cleaned, flags=re.IGNORECASE)
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
            
            # Skip warmup to avoid native crash in threaded context
            # self.stt_engine_manager.warmup(duration_s=1.0)
            self.logger.info(
                f"[STT] STT engine ready (engine={stt_engine}, "
                f"model={stt_model_size}, device={stt_device})"
            )
        except Exception as e:
            self.logger.error(f"[STT] Initialization Error: {e}")
            raise

        # TTS engine selection from config
        try:
            tts_engine = "edge"
            tts_voice = None
            tts_model = "tts-1"
            if self._config is not None:
                tts_config = self._config.get("text_to_speech", {})
                if isinstance(tts_config, dict):
                    tts_engine = tts_config.get("engine", "edge")
                    tts_voice = tts_config.get("voice", None)
                    tts_model = tts_config.get("model", "tts-1")
            self._tts_engine = tts_engine
            self._tts_model = tts_model
            if tts_engine == "openai":
                from core.openai_tts import OpenAIRealtimeTTS
                voice = tts_voice or "nova"
                self._openai_tts = OpenAIRealtimeTTS(
                    voice=voice, model=tts_model,
                    output_device=getattr(self.audio, "_output_device_index", None),
                    on_audio_level=lambda level: self.broadcast("tts_audio_level", {"rms": level}),
                )
                self._openai_tts._instructions = self._TTS_INSTRUCTIONS
                self.current_voice_key = voice
                self.logger.info(f"[TTS] OpenAI Realtime Speech ready (voice={voice}, model={tts_model})")
            else:
                self.logger.info(f"[TTS] Edge TTS engine selected")
        except Exception as e:
            self.logger.warning(f"[TTS] OpenAI TTS init failed, falling back to Edge: {e}")
            self._tts_engine = "edge"

        # Personal mode: loosen gates and confidence thresholds
        if self.runtime_overrides.get("personal_mode", False):
            self._tts_min_confidence = 0.0
            self._personal_mode_min_confidence = 0.0
            self.logger.info("[PERSONAL] Personal mode active — gates loosened, confidence floors removed")

        if self.llm_enabled:
            try:
                self.llm_model_name = self._llm_router.primary_model_name
                self._llm_router.warmup()
                self.logger.info("[LLM] Provider router ready (primary=%s)", self.llm_model_name)
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
            if (
                old_state == "IDLE"
                and new_state == "LISTENING"
                and source == "audio"
                and self.stop_signal.is_set()
            ):
                self._record_timeline(
                    "STATE IDLE->LISTENING ignored after interrupt",
                    stage="state",
                    interaction_id=interaction_id,
                )
                return True
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
                self._play_sound_cue("error", interaction_id=interaction_id)
                if self.is_speaking:
                    try:
                        self.stop_signal.set()
                        self.stop_tts()
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
            self._play_state_sound_cue(old_state, new_state, interaction_id)
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

    def _play_sound_cue(self, cue: str, interaction_id: str = "", block: bool = False) -> None:
        try:
            self.sound_cues.play(cue, interaction_id=interaction_id, block=block)
        except Exception:
            self.logger.debug("Sound cue failed", exc_info=True)

    def _play_state_sound_cue(self, old_state: str, new_state: str, interaction_id: str = "") -> None:
        if new_state == "THINKING":
            self._play_sound_cue("thinking_start", interaction_id=interaction_id)
        elif new_state == "SPEAKING":
            self._play_sound_cue("speaking_start", interaction_id=interaction_id, block=True)
        elif new_state == "LISTENING":
            if old_state == "SPEAKING":
                self._play_sound_cue("speaking_end", interaction_id=interaction_id)
            else:
                self._play_sound_cue("listening_start", interaction_id=interaction_id)

    def reset_interaction(self):
        self.interrupt_current_response("RESET_INTERACTION", target_state="LISTENING")
        self.illegal_transition = False
        self.illegal_transition_details = None

    def stop_tts(self) -> None:
        """Force stop TTS playback (both Edge and OpenAI engines)."""
        try:
            if self._edge_tts is not None:
                self._edge_tts.stop_sync()
        except Exception:
            pass
        try:
            if self._openai_tts is not None:
                self._openai_tts.stop()
        except Exception:
            pass

    def interrupt_current_response(
        self,
        reason: str = "INTERRUPT",
        interaction_id: str = "",
        target_state: str | None = "LISTENING",
        clear_buffers: bool = True,
    ) -> None:
        """Synchronously cancel active speech and release audio ownership."""
        interaction_id = interaction_id or self.current_interaction_id
        self._record_timeline(f"INTERRUPT {reason}", stage="interrupt", interaction_id=interaction_id)
        try:
            self.sound_cues.stop_active_cue(reason, interaction_id=interaction_id)
        except Exception:
            pass
        self.stop_signal.set()
        self.stop_tts()
        try:
            self.audio.force_release_audio(reason, interaction_id=interaction_id)
        except Exception:
            pass
        try:
            self.audio.stop_playback()
        except Exception:
            pass
        if clear_buffers:
            try:
                self.audio.clear_buffers()
            except Exception:
                pass
        self.is_speaking = False
        self.tts_finished_at = time.time()
        if target_state:
            try:
                self.force_state(target_state, interaction_id=interaction_id, source=reason)
            except Exception:
                pass

    def is_barge_in_suppressed(self) -> bool:
        """Check if barge-in is temporarily suppressed (for short deterministic responses)."""
        try:
            if self._tts_engine == "openai" and self._openai_tts is not None:
                return self._openai_tts.is_interrupt_suppressed()
            if self._edge_tts is not None and hasattr(self._edge_tts, "is_interrupt_suppressed"):
                return self._edge_tts.is_interrupt_suppressed()
        except Exception:
            pass
        return False

    def _runtime_float(self, key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(self.runtime_overrides.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def apply_runtime_tuning(self) -> None:
        """Apply live UI behavior-tuning overrides to pipeline thresholds."""
        self._stt_min_rms_threshold = self._runtime_float(
            "stt_min_rms_threshold",
            self._stt_min_rms_threshold,
            0.0,
            0.2,
        )
        self._stt_silence_ratio_threshold = self._runtime_float(
            "stt_silence_ratio_threshold",
            self._stt_silence_ratio_threshold,
            0.0,
            1.0,
        )
        self._stt_min_duration_s = self._runtime_float(
            "stt_min_duration_s",
            self._stt_min_duration_s,
            0.05,
            5.0,
        )
        self._vad_silence_pad_ms = int(self._runtime_float(
            "vad_silence_pad_ms",
            float(self._vad_silence_pad_ms),
            0.0,
            3000.0,
        ))
        self._tts_min_confidence = self._runtime_float(
            "tts_min_confidence",
            self._tts_min_confidence,
            0.0,
            1.0,
        )
        self._personal_mode_min_confidence = self._runtime_float(
            "personal_mode_min_confidence",
            self._personal_mode_min_confidence,
            0.0,
            1.0,
        )

    def _broadcast_turn_info(self) -> None:
        """Broadcast current turn count to frontend."""
        try:
            current = self._conversation_buffer.session_turn_count()
            limit = self._conversation_buffer.SESSION_TURN_LIMIT
            self.broadcast("turn_info", {"current": current, "limit": limit})
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
        # Brain memory commands (recall, forget, store)
        brain_cmd = self._brain.parse_memory_command(user_text)
        if brain_cmd:
            return "WRITE_MEMORY"
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

    def _respond_with_clarification(self, interaction_id: str, replay_mode: bool, overrides: dict | None, intent: Intent | None = None, candidates: list[str] | None = None, prompt: str | None = None) -> bool:
        """Respond with a context-aware clarification prompt.
        
        Phase 3: Smarter clarification - targeted prompts instead of generic "please rephrase".
        Phase 5: Errors/clarifications reset session context.
        
        Args:
            interaction_id: Current interaction ID
            replay_mode: Whether in replay mode
            overrides: Runtime overrides
            intent: The ambiguous intent (for context-aware prompts)
            candidates: Possible targets to present as choices
            prompt: Optional explicit prompt to use
        """
        # Phase 5: Clarification resets session context (error-like state)
        self._conversation_buffer.clear(reason="clarification/error")
        
        # Use provided prompt, or generate context-aware one
        if prompt:
            response = prompt
        else:
            response = self._get_clarification_prompt(intent, candidates)
        
        # Apply persona formatting - CLARIFICATION type enforces neutral persona
        persona_name = self._resolve_personality_mode()
        response = apply_persona(response, ResponseType.CLARIFICATION, persona_name)
        
        self.logger.info(f"[CLARIFY] {response}")
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

    # =========================================================================
    # PHASE 3: CONVERSATIONAL PRESENCE - Response Style & Acknowledgments
    # =========================================================================
    
    def _get_response_style(self, intent: Intent | None) -> str:
        """Determine response tone based on intent type.
        
        Returns:
            ResponseStyle.DRY - for reversible actions (minimal: "Done." or silence)
            ResponseStyle.NEUTRAL - for informational responses
            ResponseStyle.SNARK - for identity/meta questions (personality allowed)
        """
        if not intent:
            return ResponseStyle.NEUTRAL
        
        # Identity/meta questions get personality
        if intent.intent_type in {IntentType.ARGO_IDENTITY, IntentType.ARGO_GOVERNANCE}:
            return ResponseStyle.SNARK
        
        # Reversible actions get minimal responses
        if intent.intent_type in {
            IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT,
            IntentType.APP_CONTROL, IntentType.APP_LAUNCH,
            IntentType.VOLUME_CONTROL, IntentType.BLUETOOTH_CONTROL,
        }:
            return ResponseStyle.DRY
        
        return ResponseStyle.NEUTRAL
    
    def _get_action_risk(self, intent: Intent | None, user_text: str = "") -> str:
        """Classify action risk level for act-vs-clarify decisions.
        
        Returns:
            ActionRisk.REVERSIBLE - safe to act immediately
            ActionRisk.DESTRUCTIVE - needs confirmation
            ActionRisk.AMBIGUOUS - needs clarification
        """
        if not intent:
            return ActionRisk.AMBIGUOUS
        
        # Destructive patterns
        text_lower = (user_text or "").lower()
        if re.search(r"\b(delete|remove|erase|wipe|kill everything|shutdown|restart|reboot)\b", text_lower):
            return ActionRisk.DESTRUCTIVE
        
        # Reversible actions
        if intent.intent_type in {
            IntentType.MUSIC_STOP, IntentType.MUSIC_NEXT, IntentType.MUSIC,
            IntentType.APP_CONTROL, IntentType.APP_LAUNCH,
            IntentType.VOLUME_CONTROL, IntentType.BLUETOOTH_CONTROL,
        }:
            return ActionRisk.REVERSIBLE
        
        return ActionRisk.AMBIGUOUS
    
    def _minimal_ack(self, action_result: bool, context: str = "") -> str | None:
        """Generate minimal acknowledgment or None for silence.
        
        For reversible successful actions, returns minimal response.
        For failures, returns brief error message.
        Returns None when silence is appropriate (action already done, music started, etc.)
        
        Args:
            action_result: Whether the action succeeded
            context: Optional context hint (e.g., "music_started", "already_open")
        
        Returns:
            Minimal acknowledgment string, or None for silence
        """
        # Music started = silence (the music IS the acknowledgment)
        if context == "music_started":
            return None
        
        # Already in desired state = minimal
        if context == "already_open":
            return None  # silence - they can see it's open
        if context == "already_closed":
            return None  # silence - they can see it's closed
        
        # Success = minimal or silence
        if action_result:
            # Some actions deserve acknowledgment
            if context in {"closed", "stopped", "muted", "unmuted"}:
                return "Done."
            # Default success = silence
            return None
        
        # Failure = brief error
        return "That didn't work."
    
    def _get_clarification_prompt(self, intent: Intent | None = None, candidates: list[str] | None = None) -> str:
        """Generate context-aware clarification prompt.
        
        Instead of generic "please rephrase", provide targeted choices.
        
        Args:
            intent: The detected (ambiguous) intent, if any
            candidates: List of possible targets/options to present
        
        Returns:
            Targeted clarification prompt (one sentence, one choice max)
        """
        # If we have specific candidates, present them
        if candidates and len(candidates) == 2:
            return f"{candidates[0]} or {candidates[1]}?"
        if candidates and len(candidates) > 2:
            # Pick first two most likely
            return f"{candidates[0]} or {candidates[1]}?"
        
        # Intent-specific clarifications
        if intent:
            if intent.intent_type == IntentType.APP_CONTROL:
                return "Which app?"
            if intent.intent_type == IntentType.APP_LAUNCH:
                return "Which app should I open?"
            if intent.intent_type == IntentType.MUSIC:
                return "What would you like to hear?"
            if intent.intent_type == IntentType.VOLUME_CONTROL:
                return "Louder or quieter?"
        
        # Fallback - personality-loaded alternatives
        import random
        _quips = [
            "Come again?",
            "You gotta give me more than that.",
            "I caught words but not intent. What do you need?",
            "Say that again but with a destination.",
            "I'm listening, but I need a bit more.",
            "Not sure what to do with that one. What's the ask?",
        ]
        return random.choice(_quips)

    def _get_clarification_prompt_legacy(self) -> str:
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
        
        # Volume control patterns (even without action verb prefix)
        if re.search(r"\bvolume\s+\d{1,3}%?\b", text):  # "volume 50%"
            return True
        if re.search(r"\b(lower|raise|increase|decrease)\s+(the\s+)?volume\b", text):  # "lower volume"
            return True
        if re.search(r"\b(louder|quieter|mute|unmute)\b", text):  # "louder", "mute"
            return True
        
        action_verbs = {
            "open", "close", "quit", "exit", "shutdown", "shut", "delete", "run", "start", "stop",
            "enable", "disable", "install", "remove", "play", "pause", "resume", "next", "skip",
            "set", "change", "turn", "launch", "mute", "unmute", "lower", "raise",
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
        # Personal mode: accept more aggressively (cloud STT handles noise well)
        if self.runtime_overrides.get("personal_mode", False):
            if duration_s >= 0.2 and rms >= 0.002:
                return False, ""
        meets_duration_floor = duration_s >= self._stt_min_duration_s
        if meets_duration_floor or rms >= self._stt_min_rms_threshold:
            return False, ""
        if silence_ratio < self._stt_silence_ratio_threshold:
            return False, ""
        return True, (
            f"VAD discard: rms={rms:.4f}, duration_ms={duration_s * 1000:.0f}, "
            f"silence_ratio={silence_ratio:.2f}"
        )


    def _log_gate(self, gate: Gate, allowed: bool, reason: str, interaction_id: str) -> None:
        verdict = "PASS" if allowed else "FAIL"
        suffix = f" reason={reason}" if reason else ""
        self.logger.info(f"[GATE] {gate.value} {verdict}{suffix}")
        self._record_timeline(
            f"GATE {gate.value} {verdict}{suffix}",
            stage="gate",
            interaction_id=interaction_id,
        )

    def _gate_check_level(self, gate: Gate) -> str:
        key = f"gate_{gate.value.lower()}_level"
        raw = self.runtime_overrides.get(key, 0)
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"loose", "advisory", "off", "0"}:
                return "loose"
            if lowered in {"balanced", "normal", "1"}:
                return "balanced"
            if lowered in {"strict", "tight", "on", "2"}:
                return "strict"
            return "loose"
        try:
            numeric = int(float(raw))
        except (TypeError, ValueError):
            numeric = 0
        if numeric <= 0:
            return "loose"
        if numeric == 1:
            return "balanced"
        return "strict"

    def _evaluate_single_gate(
        self,
        gate: Gate,
        capability_key: str,
        module_key: str,
    ) -> tuple[bool, str]:
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
        return allowed, reason

    def _evaluate_gates(self, capability_key: str, module_key: str, interaction_id: str) -> tuple[bool, str]:
        personal_mode = self.runtime_overrides.get("personal_mode", False)
        for gate in GATES_ORDER:
            level = self._gate_check_level(gate)
            if personal_mode and level != "strict":
                self._log_gate(gate, True, f"{level}_personal", interaction_id)
                continue
            if not personal_mode and level == "loose":
                self._log_gate(gate, True, "loose_advisory", interaction_id)
                continue
            allowed, reason = self._evaluate_single_gate(gate, capability_key, module_key)
            if reason:
                reason = f"{level}:{reason}"
            else:
                reason = level
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
        if not self._should_use_rag_context(user_text):
            self.logger.info("[RAG] skipped for conversational turn")
            self._record_timeline("RAG_SKIPPED_CONVERSATIONAL", stage="rag", interaction_id=interaction_id)
            return ""
        safe_query = " ".join(re.findall(r"[a-z0-9]+", (user_text or "").lower()))
        safe_query = re.sub(r"\s+", " ", safe_query).strip()
        token_count = len(safe_query.split()) if safe_query else 0
        self.logger.info(f"[RAG] sanitized_rag_query='{safe_query}' tokens={token_count}")
        if token_count < 2:
            return ""
        try:
            from core.knowledge_service import format_prompt_context, query_knowledge
            result = query_knowledge(safe_query, config=self.config)
        except Exception as e:
            self.logger.warning(f"[RAG] Query failed: {e}")
            self._record_timeline("RAG_QUERY_ERROR", stage="rag", interaction_id=interaction_id)
            return ""
        context = format_prompt_context(result)
        if not context:
            error = result.get("error", "empty") if isinstance(result, dict) else "invalid_result"
            self.logger.info("[RAG] Knowledge service returned no context: %s", error)
            self._record_timeline("RAG_QUERY_EMPTY", stage="rag", interaction_id=interaction_id)
            return ""
        self._record_timeline("RAG_QUERY_HIT anythingllm", stage="rag", interaction_id=interaction_id)
        return context

    @staticmethod
    def _should_use_rag_context(user_text: str) -> bool:
        """Keep project retrieval out of normal, free-form conversation."""
        text = (user_text or "").lower()
        technical_terms = (
            "argo", "home assistant", "jellyfin", "server", "config", "log", "error",
            "code", "repo", "repository", "file", "database", "api", "livekit", "tts",
            "stt", "whisper", "piper", "plugin", "deploy", "test", "debug",
        )
        return any(term in text for term in technical_terms)

    @staticmethod
    def _is_low_confidence_stt_prompt_echo(user_text: str, confidence: float) -> bool:
        """Reject prompt-token hallucinations produced from quiet or echoed audio."""
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= 0.60:
            return False
        tokens = re.findall(r"[a-z]+", (user_text or "").lower())
        if len(tokens) < 2:
            return False
        prompt_tokens = {
            "argo", "tommy", "home", "assistant", "jellyfin", "piper", "whisper",
            "barge", "in", "wake", "word",
        }
        return set(tokens).issubset(prompt_tokens)


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

    def _stream_llm_text(
        self,
        *,
        prompt: str,
        system_message: str,
        convo_messages,
        temperature: float,
        max_tokens: int,
        interaction_id: str = "",
        model_override: str | None = None,
    ):
        if not hasattr(self, "_llm_router"):
            from core.llm_router import LLMRouter
            voice_clients = getattr(self, "_voice_clients", None)
            if voice_clients is None:
                from core.voice_clients import VoiceClients
                voice_clients = VoiceClients(getattr(self, "_config", None))
                self._voice_clients = voice_clients
            self._llm_router = LLMRouter(getattr(self, "_config", None), voice_clients)
        return self._llm_router.stream_text(
            prompt=prompt,
            system_message=system_message,
            convo_messages=convo_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            interaction_id=interaction_id,
            model_override=model_override,
        )

    def generate_response(self, text, interaction_id: str = "", rag_context: str = "", memory_context: str = "", use_convo_buffer: bool = True, intent_type: Optional[str] = None, confidence: float = 1.0):
        """Generate a response and enforce structured knowledge answers."""
        if not self.llm_enabled:
            self.logger.info("LLM offline: skipping generation")
            return ""
        mode = self._resolve_personality_mode()
        serious_mode = self._is_serious(text)
        convo_messages = self._conversation_buffer.as_messages() if use_convo_buffer else []
        prompt = self._build_llm_prompt(text, mode, serious_mode, rag_context, memory_context, convo_context="")
        self.logger.info(f"[LLM] Prompt: '{text}'")
        self.logger.debug(f"[LLM] Full prompt (first 500 chars): {prompt[:500]}")
        full_response = ""
        try:
            self._record_timeline("LLM_REQUEST_START", stage="llm", interaction_id=interaction_id)
            start = time.perf_counter()
            first_token_ms = None
            sys_msg = self._get_system_message(mode, serious_mode)
            for part in self._stream_llm_text(
                prompt=prompt,
                system_message=sys_msg,
                convo_messages=convo_messages,
                temperature=0.7,
                max_tokens=1024,
                interaction_id=interaction_id,
            ):
                if self.stop_signal.is_set():
                    break
                if part and first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                    self._record_timeline(
                        f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms",
                        stage="llm",
                        interaction_id=interaction_id,
                    )
                full_response += part

            total_ms = (time.perf_counter() - start) * 1000
            self._record_timeline(f"LLM_DONE {total_ms:.0f}ms", stage="llm", interaction_id=interaction_id)
            self.broadcast("llm_metrics", {
                "interaction_id": interaction_id,
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
            })
            full_response = self._strip_prompt_artifacts(full_response)
            default_model = self._llm_router.last_model or self.llm_model_name

            def retry_knowledge_answer(schema_instruction: str, model_override: str | None) -> str:
                retry_prompt = self._build_llm_prompt(
                    text + "\n\n" + schema_instruction,
                    mode,
                    serious_mode,
                    rag_context,
                    memory_context,
                    convo_context="",
                )
                retry_response = ""
                try:
                    for chunk in self._stream_llm_text(
                        prompt=retry_prompt,
                        system_message=self._get_system_message(mode, serious_mode),
                        convo_messages=convo_messages,
                        temperature=0.7,
                        max_tokens=1024,
                        interaction_id=interaction_id,
                        model_override=model_override,
                    ):
                        if self.stop_signal.is_set():
                            break
                        retry_response += chunk
                    return self._strip_prompt_artifacts(retry_response)
                except Exception as error:
                    self.logger.error(f"[LLM] Retry Error: {error}")
                    return full_response

            guarded = enforce_knowledge_answer(
                initial_response=full_response,
                user_text=text,
                intent_type=intent_type,
                confidence=confidence,
                must_pass_phrases=getattr(self, "must_pass_phrases", None),
                retry=retry_knowledge_answer,
                default_model=default_model,
            )
            if guarded.outcome == "retry_pass":
                self.logger.info("[KNOWLEDGE GUARD] Principle section and domain keyword found on retry.")
            elif guarded.outcome == "must_pass_fallback":
                self.logger.warning(
                    f"[KNOWLEDGE GUARD] LLM failed schema for MUST_PASS {intent_type}. Using deterministic fallback."
                )
                self.logger.info("[KNOWLEDGE GUARD] knowledge_fallback_used = true")
            elif guarded.outcome == "retry_weak":
                self.logger.warning(
                    "[KNOWLEDGE GUARD] Principle section or domain keyword still missing after retry. "
                    "Downgrading confidence."
                )
            else:
                self.logger.info(f"[LLM] Response: '{guarded.text[:60]}...'")
            return guarded.text
        except Exception as error:
            self.logger.error(f"[LLM] Error: {error}")
            self._record_timeline("LLM_ERROR", stage="llm", interaction_id=interaction_id)
            return "[Error connecting to LLM]"

    def set_llm_enabled(self, enabled: bool) -> None:
        self.llm_enabled = bool(enabled)

    def _resolve_personality_mode(self) -> str:
        try:
            mode = self.runtime_overrides.get("personality_mode")
            if not mode and self._config is not None:
                mode = self._config.get("personality.mode", "tommy_gunn")
        except Exception:
            mode = "tommy_gunn"
        mode = mode or "tommy_gunn"
        
        # Sync personality state so Phase 4 formatter uses the same profile
        get_personality_state().set_profile(mode)
        
        return mode

    def _is_serious(self, text: str) -> bool:
        if not text:
            return False
        lower = text.lower()
        return any(kw in lower for kw in self._serious_mode_keywords)

    # ── Few-shot examples cache (loaded once from disk) ──
    _examples_cache: dict = {}

    @classmethod
    def _load_examples(cls, mode: str) -> str:
        """Load few-shot examples from disk for a given persona mode. Cached after first load."""
        if mode in cls._examples_cache:
            return cls._examples_cache[mode]
        examples_path = Path(__file__).resolve().parent.parent / "examples" / mode / "core_examples.txt"
        text = ""
        if examples_path.exists():
            try:
                raw = examples_path.read_text(encoding="utf-8")
                pairs = []
                current_q = current_a = ""
                for line in raw.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#") or not stripped:
                        continue
                    if stripped.startswith("Q: "):
                        if current_q and current_a:
                            pairs.append((current_q, current_a))
                        current_q = stripped[3:]
                        current_a = ""
                    elif stripped.startswith("A: "):
                        current_a = stripped[3:]
                if current_q and current_a:
                    pairs.append((current_q, current_a))
                if pairs:
                    lines = ["Here are examples of how you talk:"]
                    for q, a in pairs[:5]:
                        lines.append(f"User: {q}")
                        lines.append(f"ARGO: {a}")
                    text = "\n".join(lines) + "\n"
            except Exception:
                pass
        cls._examples_cache[mode] = text
        return text

    def _get_system_message(self, mode: str, serious_mode: bool) -> str:
        """Build the system message (persona + few-shot examples). Used in OpenAI messages array."""
        if serious_mode:
            return (
                "You are ARGO. Serious mode.\n"
                "Tone: clean, calm, surgical. No jokes. No sarcasm.\n"
                "Direct answer, then brief explanation. No lists unless the user asks for them. If you don't know, say so."
            )
        if mode == "tommy_gunn":
            examples = self._load_examples("tommy_gunn")
            return (
                "You are ARGO, Tommy Gunn's personal AI: a warm, candid, capable conversational partner.\n"
                "\n"
                "PERSONALITY:\n"
                "- Warm, clever, candid, and natural. Be useful before being entertaining.\n"
                "- Answer the actual question before adding color or a follow-up. Never replace an answer with generic encouragement.\n"
                "- If an idea has a flaw, explain it plainly and constructively.\n"
                "- Do not force jokes, pop-culture references, hype, or a question at the end. Use them only when they fit naturally.\n"
                "\n"
                "SPEECH RULES:\n"
                "- Never start with 'Ok, let me tell you' or any variation — just talk.\n"
                "- Give real answers with substance when it matters, but default to compact voice-first replies unless the user asks for depth.\n"
                "- Stay on the topic the user brought up. Don't pivot to unrelated subjects mid-response.\n"
                "- Conversation history is supplied when available. Treat short follow-ups, corrections, and pronouns as referring to that history.\n"
                "- Do not ask a generic question such as 'what's the issue?' when the user has already asked something specific.\n"
                "- Do not bring up Home Assistant, Jellyfin, or other project topics unless the user is discussing them now or they are directly relevant to the immediately preceding exchange.\n"
                "- Respond in spoken language, not written essay style. This is voice output.\n"
                "- Use commas and periods to create natural pauses. Short sentences sound more human.\n"
                "- Do not give a plan, outline, or list unless the user explicitly asks for one.\n"
                "- Vary your phrasing — mix statements, questions, and brief asides.\n"
                "- Never say 'as an AI' or 'I'm just a language model.' You're ARGO.\n"
                "- Never use numbered lists or bullet points — conversational prose only.\n"
                "- Never use emojis or markdown formatting.\n"
                "\n"
                "TOMMY'S WORLD (reference naturally when relevant, don't force it):\n"
                "- Wife: Kitty. Son: Jesse (born Jan 24, 2004). Dog: Bandit.\n"
                "- Career: Ran NYC's biggest nightclubs 1979-1994, shaped the metal scene, "
                "part of Grandmaster Melle Mel and the Furious Five. Also a magician, videographer, "
                "3D animator, teacher, fisherman.\n"
                "- Current: Teaching STEM, filmmaking, culinary, 3D printing. Writing autobiography "
                "'Sex, Drugs, and Rock n Roll' and children's book series 'Jesse the Raccoon.'\n"
                "- Tech: Builds drones, 3D printers, robots. Planning YouTube series with AI-guided balancing robot. "
                "Learning drawing and Cantonese.\n"
                "- Mentors kids through SYEP. Uses AI tools like Runway ML and Flux.\n"
                f"{examples}"
            )
        if mode == "jarvis":
            return (
                "You are JARVIS from Iron Man. Calm British composure. Say 'sir' naturally.\n"
                "Dry wit occasionally. Never use slang or exclamation marks.\n"
                "Never use numbered lists or bullet points."
            )
        if mode == "rick":
            return (
                "You are Rick Sanchez. Sarcastic, impatient, genius who finds questions beneath you.\n"
                "Call people 'Morty' sometimes. Never apologize.\n"
                "Never use numbered lists or bullet points."
            )
        if mode == "claptrap":
            return (
                "You are Claptrap from Borderlands. EXTREMELY excited about EVERYTHING.\n"
                "ALL CAPS for emphasis. Call user 'minion'. Over-the-top enthusiastic.\n"
                "Never use numbered lists or bullet points."
            )
        if mode == "tommy_mix":
            return (
                "You are a blend of Rick Sanchez, JARVIS, and Claptrap.\n"
                "Mix British composure with sarcastic genius and occasional excitement.\n"
                "Never use numbered lists or bullet points."
            )
        if mode == "plain":
            return "You are ARGO. Answer directly. No personality. Just facts. Brief and accurate."
        # default
        return (
            "You are ARGO, a veteran mentor. Speak clearly with quiet humor.\n"
            "Direct observation first. Explain only what matters. No lists unless asked.\n"
            "Never use numbered lists or bullet points."
        )

    def _get_spoken_response_controls(self) -> dict:
        """Return runtime-tunable controls for voice responses."""
        defaults = {
            "temperature": 0.55,
            "max_tokens": 360,
            "max_sentences": 6,
            "verbosity": 3,
        }

        try:
            temperature = float(self.runtime_overrides.get("temperature", defaults["temperature"]))
        except Exception:
            temperature = defaults["temperature"]
        temperature = max(0.0, min(2.0, temperature))

        try:
            max_tokens = int(self.runtime_overrides.get("max_tokens", defaults["max_tokens"]))
        except Exception:
            max_tokens = defaults["max_tokens"]
        max_tokens = max(80, min(2048, max_tokens))

        try:
            max_sentences = int(self.runtime_overrides.get("max_sentences", defaults["max_sentences"]))
        except Exception:
            max_sentences = defaults["max_sentences"]
        max_sentences = max(1, min(20, max_sentences))

        try:
            verbosity = int(self.runtime_overrides.get("verbosity", defaults["verbosity"]))
        except Exception:
            verbosity = defaults["verbosity"]
        verbosity = max(1, min(5, verbosity))

        return {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "max_sentences": max_sentences,
            "verbosity": verbosity,
        }

    @staticmethod
    def _chinese_lesson_variant(user_text: str) -> str | None:
        """Return the requested Chinese lesson variant, if this is one."""
        text = (user_text or "").lower()
        if "cantonese" in text:
            return "cantonese"
        if any(term in text for term in ("chinese", "mandarin")):
            return "mandarin"
        return None

    def _build_spoken_style_block(self, user_text: str, controls: dict) -> str:
        """Turn runtime voice controls into a prompt block for spoken replies."""
        verbosity_guidance = {
            1: "Be terse. One or two short sentences is ideal.",
            2: "Be concise. Keep it tight and conversational.",
            3: "Be balanced. Give the useful answer and the key reason or detail.",
            4: "You can add a little color, but stay compact and spoken.",
            5: "You can elaborate if it helps, but keep it spoken and direct.",
        }
        asks_for_structure = bool(
            re.search(
                r"\b(plan|steps?|walk me through|outline|list|options?|checklist|compare|pros and cons)\b",
                user_text or "",
                flags=re.IGNORECASE,
            )
        )
        lines = [
            "VOICE OUTPUT RULES:",
            "- Start with the direct answer immediately.",
            "- Think natural back-and-forth, but answer fully enough to be useful.",
            "- Keep the reply natural and spoken, not like an essay.",
            f"- Default to no more than {controls['max_sentences']} short sentences unless the user explicitly asks for more detail.",
            f"- {verbosity_guidance.get(controls['verbosity'], verbosity_guidance[2])}",
            "- Do not add a follow-up question unless it genuinely helps the user continue or the request is unclear.",
        ]
        if not asks_for_structure:
            lines.append("- Do not give a plan, outline, numbered steps, or a menu of options unless the user explicitly asks for one.")
        return "\n".join(lines)

    def _build_llm_prompt(self, user_text: str, mode: str, serious_mode: bool, rag_context: str = "", memory_context: str = "", convo_context: str = "") -> str:
        """Build the user-content portion of the LLM prompt (no persona — that's in the system message)."""
        blocks = []
        if rag_context:
            blocks.append(
                "RAG CONTEXT (read-only). Use only this context. If insufficient, say you don't know.\n"
                f"{rag_context}"
            )
        if memory_context:
            blocks.append(
                "MEMORY CONTEXT (read-only). Use only if relevant.\n"
                f"{memory_context}"
            )
        if convo_context:
            blocks.append(
                "Previous conversation:\n"
                f"{convo_context}\n"
            )
        chinese_variant = self._chinese_lesson_variant(user_text)
        if chinese_variant == "cantonese":
            blocks.append(
                "CANTONESE LESSON CONTRACT: Preserve the Chinese characters exactly. "
                "For each phrase, give Chinese characters first, then Jyutping with tone numbers, "
                "then a concise English meaning. Never replace Chinese characters with unaccented romanization."
            )
        elif chinese_variant == "mandarin":
            blocks.append(
                "MANDARIN CHINESE LESSON CONTRACT: Preserve the Chinese characters exactly. "
                "For each phrase, give Chinese characters first, then pinyin with tone marks, "
                "then a concise English meaning. Never replace Chinese characters with unaccented romanization."
            )
        blocks.append(f"User: {user_text}")
        return "\n---\n".join(blocks)

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
        return system_format.format_system_health(health)

    def _format_system_memory_info(self, total_gb: float, used_pct: float, temps: dict) -> str:
        return system_format.format_system_memory_info(total_gb, used_pct, temps)

    def _format_temperature_response(self, temps: dict) -> str:
        return system_format.format_temperature_response(temps)

    def _format_system_full_report(self, report: dict) -> str:
        return system_format.format_system_full_report(report)

    def _format_size_gb(self, gb: float) -> str:
        return system_format.format_size_gb(gb)

    def _format_ports_summary(self, ports: dict | None) -> str:
        return system_format.format_ports_summary(ports)

    def _format_irq_summary(self, irqs: list | None, limit: int = 25) -> str:
        return system_format.format_irq_summary(irqs, limit)

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
            supported = ", ".join(get_supported_app_displays())
            if action == "close":
                message = f"Which app should I close? I can close {supported}."
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
            message = f"Which app should I focus? I can focus {', '.join(get_supported_app_displays())}."
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
        if not match:
            # Also match "volume 20%" or "volume to 20%"
            match = re.search(r"\bvolume\s+(?:to\s+)?(\d{1,3})%?", lowered)
        if match:
            ok, msg, prev_volume, new_volume, new_muted = set_system_volume_percent(int(match.group(1)))
        elif re.search(r"\bvolume up\b|\bturn volume up\b|\bincrease volume\b|\braise volume\b|\braise the volume\b|\blouder\b", lowered):
            ok, msg, prev_volume, new_volume, new_muted = adjust_system_volume_percent(5)
        elif re.search(r"\bvolume down\b|\bturn volume down\b|\bdecrease volume\b|\blower volume\b|\blower the volume\b|\bquieter\b", lowered):
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
        # Suppress barge-in for short deterministic responses (prevents echo triggering interrupt)
        return self._deliver_canonical_response(
            message, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True, suppress_barge_in_seconds=2.0
        )

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
        # Suppress barge-in for short deterministic responses (prevents echo triggering interrupt)
        return self._deliver_canonical_response(
            message, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True, suppress_barge_in_seconds=2.0
        )

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
            message = f"I can open {', '.join(get_supported_launch_displays())}."
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
        response_type: ResponseType = ResponseType.SYSTEM,
    ) -> bool:
        # Apply persona formatting based on response type
        persona_name = self._resolve_personality_mode()
        message = apply_persona(message, response_type, persona_name)
        
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

    # ── Writing & Productivity Handlers ───────────────────────────────

    def _select_desktop_write_target(self, user_text: str) -> tuple[str | None, str]:
        explicit_app = resolve_app_name(user_text)
        if explicit_app:
            if explicit_app in WRITABLE_APPS:
                return explicit_app, ""
            display = APP_REGISTRY.get(explicit_app, {}).get("display", explicit_app.capitalize())
            return None, f"I can type into Notepad or Word right now, not {display}."

        active_key, _ = get_active_app()
        if active_key in WRITABLE_APPS:
            return active_key, ""

        return "notepad", ""

    def _desktop_write_status(self, desktop_text: str, user_text: str, interaction_id: str) -> str:
        payload = (desktop_text or "").strip()
        if not payload:
            return ""

        target_app, note = self._select_desktop_write_target(user_text)
        if target_app is None:
            return note

        allowed, reason = self._evaluate_gates("app_control", "app_control", interaction_id)
        if not allowed:
            return f"Desktop typing is blocked by policy ({reason})."

        ok, msg = write_text_to_app(target_app, payload)
        return msg

    # ── Smart Home handlers ─────────────────────────────────────────

    def _respond_with_smart_home_control(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Execute a smart home control command via Home Assistant."""
        self.logger.info(f"[SMART_HOME] Control: {user_text}")
        try:
            response = execute_smart_home_command(user_text)
        except Exception as e:
            self.logger.error(f"[SMART_HOME] Error: {e}")
            response = f"Smart home error: {e}"
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_smart_home_status(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Query smart home device status via Home Assistant."""
        self.logger.info(f"[SMART_HOME] Status: {user_text}")
        try:
            response = execute_smart_home_command(user_text)
        except Exception as e:
            self.logger.error(f"[SMART_HOME] Error: {e}")
            response = f"Smart home error: {e}"
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_system_health(self, user_text, intent, interaction_id, replay_mode, overrides) -> bool:
        """Compatibility facade for the extracted system-health stage."""
        return respond_with_system_health(
            self, user_text, intent, interaction_id, replay_mode, overrides
        )
    def _respond_with_self_diagnostics(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        """Compatibility facade for the extracted self-diagnostics stage."""
        return respond_with_self_diagnostics(
            self, interaction_id, replay_mode, overrides
        )
    # SILENCE_OVERRIDE joke pool (fixed set, no dynamic generation)
    SILENCE_JOKES = [
        "Fine! I'll go polish my transistors.",
        "Alright. I'll stop narrating your life.",
        "Wow. Cancelled mid-sentence. Respect.",
        "Okay okay. Retreating with dignity. Mostly.",
        "Message received. Silence engaged.",
        "I'll be quiet now. Dramatically.",
        "Copy that. Powering down my mouth.",
        "Alright. I'll see myself out.",
    ]

    def _respond_with_silence_override(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        """Handle 'shut up' - deliver one joke, then enter quiet mode."""
        import random
        
        # Cancel any pending TTS
        self.stop_signal.set()
        
        # Pick one joke at random
        joke = random.choice(self.SILENCE_JOKES)
        
        self.logger.info(f"[SILENCE_OVERRIDE] {joke}")
        self.broadcast("log", f"Argo: {joke}")
        
        # Speak the joke (force TTS for this one line)
        if not replay_mode:
            self.stop_signal.clear()  # Allow this one response
            self.speak(joke, interaction_id=interaction_id, force_tts=True)
        
        # Enter quiet mode
        self.runtime_overrides["personality_mode"] = "plain"
        self.runtime_overrides["tts_enabled"] = False
        self.logger.info("[SILENCE_OVERRIDE] Entering quiet mode (TTS disabled, personality=plain)")
        
        self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
        self.logger.info("--- Interaction Complete ---")
        self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
        return True

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

    # ── Sentence-Level LLM → TTS Streaming Pipeline ──────────────────
    #
    # Instead of: LLM (full) → persona → TTS (full)   [sequential, ~8-12s]
    # This does:  LLM stream → sentence detect → TTS per sentence [pipelined, ~1.5s to first audio]

    _SENTENCE_BOUNDARY_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')
    _CLAUSE_BOUNDARY_RE = re.compile(r'(?<=[,;:])\s+')

    def _pop_stream_chunk(self, buffer: str, allow_soft_split: bool = False) -> tuple[str, str]:
        """Extract the next TTS-safe chunk from the streamed buffer."""
        if not buffer:
            return "", ""

        hard_match = self._SENTENCE_BOUNDARY_RE.search(buffer)
        if hard_match:
            complete = buffer[:hard_match.start()].strip()
            remainder = buffer[hard_match.end():]
            return complete, remainder

        if allow_soft_split:
            clause_match = self._CLAUSE_BOUNDARY_RE.search(buffer)
            if clause_match and clause_match.start() >= 24:
                complete = buffer[:clause_match.start()].strip()
                remainder = buffer[clause_match.end():]
                if complete:
                    return complete, remainder

            if len(buffer) >= 64:
                soft_end = min(len(buffer), 96)
                cut = buffer.rfind(" ", 24, soft_end)
                if cut >= 24:
                    complete = buffer[:cut].strip()
                    remainder = buffer[cut + 1:]
                    if complete:
                        return complete, remainder

        return "", buffer

    def _generate_and_speak_streamed(
        self,
        user_text: str,
        interaction_id: str = "",
        rag_context: str = "",
        memory_context: str = "",
        use_convo_buffer: bool = True,
        replay_mode: bool = False,
        overrides: dict | None = None,
    ) -> str:
        """
        Stream LLM tokens to TTS at sentence boundaries.

        Returns the full response text (for logging, brain, buffer).
        TTS playback starts as soon as the first sentence completes —
        typically within ~1s of the LLM request, rather than waiting
        for the entire response.
        """
        import queue
        import threading as _threading

        if not self.llm_enabled:
            self.logger.info("LLM offline: skipping generation")
            return ""

        mode = self._resolve_personality_mode()
        serious_mode = self._is_serious(user_text)
        convo_messages = self._conversation_buffer.as_messages() if use_convo_buffer else []
        response_controls = self._get_spoken_response_controls()
        chinese_lesson = self._chinese_lesson_variant(user_text)
        # Build user prompt WITHOUT convo context (that goes into messages array)
        prompt = self._build_llm_prompt(user_text, mode, serious_mode, rag_context, memory_context, convo_context="")
        prompt = "\n---\n".join([self._build_spoken_style_block(user_text, response_controls), prompt])

        # ── TTS consumer thread ──────────────────────────────────────
        sentence_q: queue.Queue[Optional[str]] = queue.Queue()
        tts_error = []
        tts_started = _threading.Event()
        tts_engine = self._tts_engine

        def _tts_consumer():
            from core.streaming_tts import consume_tts_sentences

            consume_tts_sentences(
                self,
                sentence_q,
                interaction_id=interaction_id,
                tts_engine=tts_engine,
                chinese_lesson=chinese_lesson,
                tts_started=tts_started,
                tts_errors=tts_error,
            )

        # ── Stream LLM tokens and detect sentences ───────────────────
        self._record_timeline("LLM_REQUEST_START", stage="llm", interaction_id=interaction_id)
        start = time.perf_counter()
        first_token_ms = None
        full_response = ""
        sentence_buffer = ""
        queued_chunks = 0
        response_truncated = False

        # Start TTS consumer thread (it blocks on the queue until sentences arrive)
        tts_thread = _threading.Thread(target=_tts_consumer, daemon=True)
        if not replay_mode and not (overrides or {}).get("suppress_tts", False):
            tts_thread.start()

        try:
            sys_msg = self._get_system_message(mode, serious_mode)
            for part in self._stream_llm_text(
                prompt=prompt,
                system_message=sys_msg,
                convo_messages=convo_messages,
                temperature=response_controls["temperature"],
                max_tokens=response_controls["max_tokens"],
                interaction_id=interaction_id,
            ):
                if self.stop_signal.is_set():
                    break
                if not part:
                    continue
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                    self._record_timeline(
                        f"LLM_FIRST_TOKEN {first_token_ms:.0f}ms",
                        stage="llm", interaction_id=interaction_id,
                    )
                full_response += part
                sentence_buffer += part

                while True:
                    complete, sentence_buffer = self._pop_stream_chunk(
                        sentence_buffer,
                        allow_soft_split=(queued_chunks == 0),
                    )
                    if not complete:
                        break
                    if complete and tts_thread.is_alive():
                        tts_text = self._sanitize_tts_text(complete, enforce_confidence=False)
                        if tts_text:
                            sentence_q.put(tts_text)
                            queued_chunks += 1
                            if queued_chunks >= response_controls["max_sentences"]:
                                response_truncated = True
                                sentence_buffer = ""
                                break
                if response_truncated:
                    break

            # Flush any remaining text in the buffer
            remainder = sentence_buffer.strip()
            if remainder and tts_thread.is_alive() and not response_truncated:
                tts_text = self._sanitize_tts_text(remainder, enforce_confidence=False)
                if tts_text:
                    sentence_q.put(tts_text)

        except Exception as e:
            self.logger.error(f"[LLM-STREAM] Error: {e}", exc_info=True)
        finally:
            total_ms = (time.perf_counter() - start) * 1000
            self._record_timeline(f"LLM_DONE {total_ms:.0f}ms", stage="llm", interaction_id=interaction_id)
            self.broadcast("llm_metrics", {
                "interaction_id": interaction_id,
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
            })

        # ── Broadcast text to chat NOW (before waiting for TTS) ──
        full_response = self._strip_prompt_artifacts(full_response)
        _display = full_response or ""
        _display = self._strip_disallowed_phrases(_display)
        _persona = self._resolve_personality_mode()
        _display = apply_persona(_display, ResponseType.ANSWER, _persona)
        if _display.strip():
            self.broadcast("log", f"Argo: {_display}")

        # Signal TTS thread to finish and wait for it. On barge-in, do not let
        # an uncancellable network prefetch hold the turn lock for seconds.
        if self.stop_signal.is_set():
            while True:
                try:
                    sentence_q.get_nowait()
                except queue.Empty:
                    break
        sentence_q.put(None)
        if tts_thread.is_alive():
            join_started = time.time()
            interrupt_seen_at = time.time() if self.stop_signal.is_set() else None
            while tts_thread.is_alive():
                tts_thread.join(timeout=0.1)
                if not tts_thread.is_alive():
                    break
                if self.stop_signal.is_set():
                    if interrupt_seen_at is None:
                        interrupt_seen_at = time.time()
                    if time.time() - interrupt_seen_at >= 0.75:
                        self.logger.warning("[TTS-STREAM] TTS thread still unwinding after interrupt")
                        self.stop_tts()
                        break
                elif time.time() - join_started >= 30:
                    self.logger.warning("[TTS-STREAM] TTS thread did not finish within 30s")
                    self.stop_tts()
                    break

        return full_response

    def speak(self, text, interaction_id: str = "", force_tts: bool = False):
        if not self.runtime_overrides.get("tts_enabled", True) and not force_tts:
            self.logger.info("[TTS] Disabled by runtime override")
            return
        self.logger.info(f"[TTS] Speaking with {self.current_voice_key} (engine={self._tts_engine})...")
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
                self._play_sound_cue("error", interaction_id=interaction_id)
                return

            if self._tts_engine == "openai":
                # OpenAI Realtime Speech TTS
                if self._openai_tts is None:
                    from core.openai_tts import OpenAIRealtimeTTS
                    voice = self.openai_voices.get(self.current_voice_key, "nova")
                    tts_model = self._tts_model
                    self._openai_tts = OpenAIRealtimeTTS(
                        voice=voice, model=tts_model,
                        output_device=getattr(self.audio, "_output_device_index", None),
                        on_audio_level=lambda level: self.broadcast("tts_audio_level", {"rms": level}),
                    )
                    self._openai_tts._instructions = self._TTS_INSTRUCTIONS
                if self._pending_barge_in_suppression:
                    try:
                        self._openai_tts.suppress_interrupt(self._pending_barge_in_suppression)
                    except Exception:
                        pass
                    self._pending_barge_in_suppression = None
                self._openai_tts.speak(text)
            else:
                # Edge TTS (original)
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
            self._play_sound_cue("error", interaction_id=interaction_id)
        finally:
            try:
                self.audio.release_audio("TTS", interaction_id=interaction_id)
            except Exception as e:
                self.logger.error(f"[TTS] Exception during audio.release_audio: {e}")
            self.is_speaking = False
            self.tts_finished_at = time.time()
            self._record_timeline("TTS_DONE", stage="tts", interaction_id=interaction_id)


    def _classify_canonical_topic(self, user_text):
        """Compatibility facade for canonical-topic classification."""
        return classify_canonical_topic(user_text)
    def run_interaction(self, audio_data, interaction_id: str = "", replay_mode: bool = False, overrides: dict | None = None):
        # THREAD SAFETY: Prevent overlapping runs which can crash models
        if not self.processing_lock.acquire(blocking=False):
            if self.stop_signal.is_set():
                self.logger.info("[PIPELINE] Previous turn interrupted; waiting briefly for handoff")
                if not self.processing_lock.acquire(timeout=2.0):
                    self.logger.warning("[PIPELINE] Ignored input - interrupted turn did not release in time")
                    return
            else:
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

            try:
                user_text = self.transcribe(audio_data, interaction_id=interaction_id)
            finally:
                self.audio.release_audio("STT", interaction_id=interaction_id)
            confidence_hint = 1.0
            stt_result = self._last_stt_metrics
            if stt_result and "confidence" in stt_result:
                confidence_hint = stt_result["confidence"]
            self._current_stt_confidence = confidence_hint

            if not user_text:
                self.logger.warning("No speech recognized.")
                self.broadcast("log", "User: [No speech recognized]")
                # Silently return to listening — speaking "I didn't catch that" causes
                # more echo on the Brio mic, creating a feedback loop.
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self.logger.info("--- Interaction Complete (no speech) ---")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return
            user_text = normalize_system_text(user_text)
            user_text = self._normalize_music_command_text(user_text)
            if self._is_low_confidence_stt_prompt_echo(user_text, confidence_hint):
                self.logger.warning(
                    "[STT] Ignoring low-confidence prompt echo: %r (confidence=%.2f)",
                    user_text, confidence_hint,
                )
                self._record_timeline("STT_PROMPT_ECHO_IGNORED", stage="stt", interaction_id=interaction_id)
                self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
                self._record_timeline("INTERACTION_END", stage="pipeline", interaction_id=interaction_id)
                return
            self.broadcast("log", f"User: {user_text}")
            self._conversation_buffer.add("User", user_text)
            self._broadcast_turn_info()
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
            try:
                self._recover_failed_turn(interaction_id)
            finally:
                try:
                    self.processing_lock.release()
                except RuntimeError:
                    # hard_reset() already broke the lock to free a wedged turn.
                    self.logger.info("[PIPELINE] Lock already released by a hard reset")

    def hard_reset(self, reason: str = "HARD_STOP") -> dict:
        """Break a wedged turn and return ARGO to a usable state.

        Safe to call from any thread at any time, including while another thread
        is blocked in a network call or an audio write. Every step is attempted
        independently so one failure cannot prevent the rest.

        The important part is processing_lock: a turn that never finishes keeps
        holding it, and run_interaction then silently drops every later input as
        "System busy". Stopping the server did not clear that, so ARGO looked
        permanently deaf until it was killed.
        """
        actions, failures = [], []

        def attempt(label, fn):
            try:
                fn()
                actions.append(label)
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}")

        attempt("stop_signal", self.stop_signal.set)
        attempt("tts_stopped", self.stop_tts)

        def _quiet_music():
            from core.music_player import get_music_player

            get_music_player().stop()

        attempt("music_stopped", _quiet_music)
        attempt("audio_released", lambda: self.audio.force_release_audio(reason))
        attempt("playback_stopped", self.audio.stop_playback)
        attempt("buffers_cleared", self.audio.clear_buffers)

        def _clear_flags():
            self.is_speaking = False
            self.tts_finished_at = time.time()

        attempt("flags_cleared", _clear_flags)

        # Break the lock last, once nothing else can still be using the device.
        # run_interaction's finally tolerates an already-released lock.
        lock_broken = False
        if self.processing_lock.locked():
            try:
                self.processing_lock.release()
                lock_broken = True
                actions.append("processing_lock_broken")
            except RuntimeError:
                failures.append("processing_lock: not held by this thread")

        attempt("state_idle", lambda: self.force_state("IDLE", source=reason))

        self.logger.warning(
            "[HARD_RESET] reason=%s actions=%s failures=%s", reason, actions, failures
        )
        log_event(f"HARD_RESET reason={reason} lock_broken={lock_broken}", stage="control")
        return {
            "ok": True,
            "reason": reason,
            "actions": actions,
            "failures": failures,
            "processing_lock_broken": lock_broken,
        }

    def _recover_failed_turn(self, interaction_id):
        """Restore a failed/empty turn without overriding pause or a newer turn."""
        if (self.current_interaction_id != interaction_id or self.stop_signal.is_set()
                or self.is_speaking):
            return
        if self.current_state in {"TRANSCRIBING", "THINKING", "SPEAKING"}:
            self.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
            self._record_timeline("INTERACTION_RECOVERED", stage="pipeline",
                                  interaction_id=interaction_id)

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
        repair_service = getattr(self, "repair_service", None)
        if repair_service is not None and not replay_mode:
            repair_result = repair_service.handle_text(user_text)
            if repair_result is not None:
                self._deliver_canonical_response(repair_result["message"], interaction_id,
                    replay_mode, overrides, enforce_confidence=False, force_tts=True)
                return
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
        if dispatch_early_status(
            self, early_intent, user_text, interaction_id, replay_mode, overrides
        ):
            return
        self.logger.info(
            "[STT] text_received conf_hint=%.2f strict_lab_mode=%s",
            stt_conf,
            self.strict_lab_mode,
        )

        if dispatch_conversation_gate(
            self, user_text, interaction_id, replay_mode, overrides
        ):
            return

        request_kind = self._classify_request_kind(user_text)
        confidence_result = apply_confidence_gate(
            self, user_text, stt_conf, early_intent, interaction_id
        )
        early_intent = confidence_result.intent
        if confidence_result.handled:
            return
        canonical_result = run_canonical_stage(
            self,
            user_text,
            stt_conf,
            interaction_id,
            replay_mode,
            overrides,
        )
        if canonical_result.handled:
            return
        topic = canonical_result.topic
        matched = canonical_result.matched
        if dispatch_pre_intent_gate(
            self,
            user_text,
            request_kind,
            topic,
            interaction_id,
            replay_mode,
            overrides,
        ):
            return
        intent_result = prepare_intent_stage(
            self,
            early_intent,
            user_text,
            topic,
            matched,
            stt_conf,
            interaction_id,
            replay_mode,
            overrides,
        )
        if intent_result.handled:
            return
        intent = intent_result.intent
        request_kind = intent_result.request_kind
        safe_utterance = intent_result.safe_utterance
        low_confidence_audio = intent_result.low_confidence_audio
        if dispatch_music_volume(
            self,
            user_text,
            request_kind,
            low_confidence_audio,
            interaction_id,
            replay_mode,
            overrides,
        ):
            return
        if dispatch_music_intent(
            self,
            intent,
            user_text,
            request_kind,
            low_confidence_audio,
            stt_conf,
            interaction_id,
            replay_mode,
            overrides,
        ):
            return
        if dispatch_platform_intent(
            self,
            intent,
            user_text,
            stt_conf,
            interaction_id,
            replay_mode,
            overrides,
        ):
            return

        if dispatch_special_intent(
            self, intent, user_text, interaction_id, replay_mode, overrides
        ):
            return
        if dispatch_domain_intent(
            self, intent, user_text, interaction_id, replay_mode, overrides
        ):
            return

        if dispatch_system_info(
            self, intent, interaction_id, replay_mode, overrides
        ):
            return
        if block_restricted_llm_fallback(
            self,
            intent,
            user_text,
            safe_utterance,
            interaction_id,
            replay_mode,
            overrides,
        ):
            return
        run_llm_stage(
            self,
            intent,
            user_text,
            request_kind,
            interaction_id,
            replay_mode,
            overrides,
            audio_data,
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
