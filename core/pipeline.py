
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
    ResponseStyle,
    ActionRisk,
)
from core.intent_parser import RuleBasedIntentParser, Intent, IntentType, normalize_system_text, is_system_keyword
from core.stt_engine_manager import STTEngineManager, verify_engine_dependencies
from core.music_player import get_music_player
from core.music_status import query_music_status
from core.app_control import (
    WRITABLE_APPS,
    get_active_app,
    write_text_to_app,
)
from core.app_registry import APP_REGISTRY
from core.app_registry import resolve_app_name

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
from core.pipeline_system_health import respond_with_system_health
from core.pipeline_topic_classifier import classify_canonical_topic
from core.pipeline_self_diagnostics import respond_with_self_diagnostics
from core.pipeline_draft_responses import PipelineDraftResponseService
from core.pipeline_scheduling_responses import PipelineSchedulingService
from core.pipeline_inspection_responses import PipelineInspectionService
from core.pipeline_task_planning import PipelineTaskPlanningService
from core.pipeline_writing_responses import PipelineWritingResponseService
from core import system_response_formatter as system_format
from core.pipeline_text_router import route_user_text
from core.pipeline_streaming_response import PipelineStreamingResponseService
from core.pipeline_response_generation import PipelineResponseGenerationService
from core.pipeline_bluetooth import PipelineBluetoothService
from core.pipeline_audio_routing import PipelineAudioRoutingService
from core.pipeline_system_volume import PipelineSystemVolumeService
from core.pipeline_apps import PipelineAppService
from core.pipeline_time import LOCATION_TO_TIMEZONE as TIMEZONE_MAP, PipelineTimeService
from core.pipeline_request_classifier import (
    classify_request_kind,
    classify_request_type,
    has_interrogative_structure,
    is_identity_query,
    meaningful_tokens,
)
from core.pipeline_settings import load_pipeline_settings
from core.pipeline_transcription import TranscriptionDependencies, transcribe_audio
from core.pipeline_warmup import WarmupDependencies, initialize_pipeline_runtime
from core.pipeline_interaction_runtime import (
    InteractionDependencies,
    process_interaction_audio,
)
from core.pipeline_speech import SpeechDependencies, speak_text
from core import persona_briefs
from core.pipeline_ambiguity import ambiguous_short_question_prompt

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
        settings = load_pipeline_settings(self._config, self.runtime_overrides)
        self._tts_min_text_length = settings.tts_min_text_length
        self._tts_min_confidence = settings.tts_min_confidence
        self._personal_mode_min_confidence = settings.personal_mode_min_confidence
        self._personal_mode_min_text_len = settings.personal_mode_min_text_length
        self._intent_parser = RuleBasedIntentParser()
        self._inspection_responses = PipelineInspectionService(self)
        self._scheduling_responses = PipelineSchedulingService(self)
        self._task_planning = PipelineTaskPlanningService(self)
        self._draft_responses = PipelineDraftResponseService(self)
        self._writing_responses = PipelineWritingResponseService(self)
        self._bluetooth = PipelineBluetoothService(self)
        self._audio_routing = PipelineAudioRoutingService(self)
        self._system_volume = PipelineSystemVolumeService(self)
        self._apps = PipelineAppService(self)
        self._time_responses = PipelineTimeService(self)
        self._streaming_responses = PipelineStreamingResponseService(self)
        self._response_generation = PipelineResponseGenerationService(self)
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
        session_memory_enabled = self.runtime_overrides.get("session_memory_enabled", True)
        self._conversation_buffer = ConversationBuffer(
            max_turns=settings.conversation_buffer_size,
            enabled=session_memory_enabled,
        )
        self._conversation_ledger = deque(maxlen=settings.conversation_ledger_size)
        self._pending_memory_write = None
        self._pending_memory = None
        self._memory_commands = MemoryCommandService(self)
        self._memory_service = PipelineMemoryService(self)
        self._session_flags = {}
        self._stt_prompt_profile = settings.stt_prompt_profile
        self._stt_initial_prompt = settings.stt_initial_prompt
        self._stt_min_rms_threshold = settings.stt_min_rms_threshold
        self._stt_silence_ratio_threshold = settings.stt_silence_ratio_threshold
        self._stt_min_duration_s = settings.stt_min_duration_seconds
        self._vad_silence_pad_ms = settings.vad_silence_pad_ms
        self.strict_lab_mode = settings.strict_lab_mode

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
        return ambiguous_short_question_prompt(text, request_kind, topic)

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
        try:
            result = initialize_pipeline_runtime(
                WarmupDependencies(
                    logger=self.logger,
                    config=self._config,
                    audio_output_device=getattr(
                        self.audio, "_output_device_index", None
                    ),
                    runtime_overrides=self.runtime_overrides,
                    llm_enabled=self.llm_enabled,
                    llm_router=self._llm_router,
                    stt_manager_factory=STTEngineManager,
                    verify_stt_dependencies=verify_engine_dependencies,
                    stt_prompt_profile=self._stt_prompt_profile,
                    tts_instructions=self._TTS_INSTRUCTIONS,
                    broadcast_audio_level=lambda level: self.broadcast(
                        "tts_audio_level", {"rms": level}
                    ),
                )
            )
        except Exception as exc:
            self.logger.error(f"[STT] Initialization Error: {exc}")
            raise
        self.stt_engine_manager = result.stt_manager
        self.stt_model_name = result.stt_model_name
        self.stt_engine = result.stt_engine
        self._tts_engine = result.tts_engine
        self._tts_model = result.tts_model
        self._openai_tts = result.openai_tts
        if result.current_voice_key is not None:
            self.current_voice_key = result.current_voice_key
        if result.personal_mode:
            self._tts_min_confidence = 0.0
            self._personal_mode_min_confidence = 0.0
        if result.llm_model_name is not None:
            self.llm_model_name = result.llm_model_name
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
        if self._brain.parse_memory_command(user_text):
            return "WRITE_MEMORY"
        if self._parse_memory_write(user_text):
            return "WRITE_MEMORY"
        return classify_request_kind(user_text)

    def _classify_request_type(self, user_text: str, intent) -> str:
        request_kind = self._classify_request_kind(user_text)
        return classify_request_type(
            user_text, intent, request_kind, self._is_executable_command
        )

    def _has_interrogative_structure(self, text: str) -> bool:
        return has_interrogative_structure(text)

    def _get_meaningful_tokens(self, text: str) -> list:
        return meaningful_tokens(text)

    def _is_identity_query(self, text: str) -> bool:
        return is_identity_query(text)

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
        outcome = transcribe_audio(
            TranscriptionDependencies(
                logger=self.logger,
                engine_manager=self.stt_engine_manager,
                engine_name=self.stt_engine,
                initial_prompt=self._stt_initial_prompt,
                should_reject_audio=self._should_reject_audio,
                record_timeline=self._record_timeline,
                broadcast=self.broadcast,
            ),
            audio_data,
            interaction_id,
        )
        if outcome.metrics is not None:
            self._last_stt_metrics = outcome.metrics
        return outcome.text

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
        service = getattr(self, "_response_generation", None)
        if service is None:
            service = PipelineResponseGenerationService(self)
            self._response_generation = service
        return service.generate(
            text,
            interaction_id=interaction_id,
            rag_context=rag_context,
            memory_context=memory_context,
            use_convo_buffer=use_convo_buffer,
            intent_type=intent_type,
            confidence=confidence,
        )

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
        selected_mode = mode if persona_briefs.get(mode) is not None else "neutral"
        message = persona_briefs.compose_instructions(
            selected_mode,
            deep_think=False,
        )
        if selected_mode == "tommy_gunn":
            message += "\n\n" + self._load_examples("tommy_gunn")
        return message

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
        return self._bluetooth.format_status(status)

    def _is_bluetooth_status_text(self, text: str) -> bool:
        return self._bluetooth.is_status_text(text)

    def _is_bluetooth_control_text(self, text: str) -> bool:
        return self._bluetooth.is_control_text(text)

    def _respond_with_bluetooth_status(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._bluetooth.respond_status(user_text, interaction_id, replay_mode, overrides)

    def _respond_with_bluetooth_control(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._bluetooth.respond_control(
            intent, user_text, stt_conf, interaction_id, replay_mode, overrides
        )

    def _format_audio_routing_status(self, status: dict) -> str:
        return self._audio_routing.format_status(status)

    def _is_audio_routing_status_text(self, text: str) -> bool:
        return self._audio_routing.is_status_text(text)

    def _is_audio_routing_control_text(self, text: str) -> bool:
        return self._audio_routing.is_control_text(text)

    def _respond_with_audio_routing_status(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._audio_routing.respond_status(user_text, interaction_id, replay_mode, overrides)

    def _respond_with_audio_routing_control(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._audio_routing.respond_control(
            intent, user_text, stt_conf, interaction_id, replay_mode, overrides
        )

    def _is_app_status_text(self, text: str) -> bool:
        return self._apps.is_status_text(text)

    def _is_app_control_text(self, text: str) -> bool:
        return self._apps.is_control_text(text)

    def _respond_with_app_status(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._apps.respond_status(user_text, interaction_id, replay_mode, overrides)

    def _respond_with_app_control(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._apps.respond_control(
            intent, user_text, stt_conf, interaction_id, replay_mode, overrides
        )

    def _respond_with_focus_status(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._apps.respond_focus_status(intent, interaction_id, replay_mode, overrides)

    def _respond_with_focus_control(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._apps.respond_focus_control(intent, interaction_id, replay_mode, overrides)

    def _is_system_volume_text(self, text: str) -> bool:
        return self._system_volume.is_system_volume_text(text)

    def _respond_with_system_volume_status(self, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._system_volume.respond_status(interaction_id, replay_mode, overrides)

    def _respond_with_system_volume_control(self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._system_volume.respond_control(
            user_text, interaction_id, replay_mode, overrides
        )

    # =========================================================================
    # WORLD TIME - City/Country to IANA Timezone mapping
    # =========================================================================
    LOCATION_TO_TIMEZONE = TIMEZONE_MAP

    def _format_world_time(self, location: str) -> str:
        return self._time_responses.format_world_time(location)

    def _respond_with_world_time(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._time_responses.respond_world_time(
            intent, interaction_id, replay_mode, overrides
        )

    def _format_time_status(self, subintent: str | None) -> str:
        return self._time_responses.format_time_status(subintent)

    def _respond_with_time_status(self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._time_responses.respond_time_status(
            intent, interaction_id, replay_mode, overrides
        )

    def _has_disallowed_app_launch_tokens(self, text: str) -> bool:
        return self._apps.has_disallowed_launch_tokens(text)

    def _respond_with_app_launch(self, intent, user_text: str, stt_conf: float, interaction_id: str, replay_mode: bool, overrides: dict | None) -> bool:
        return self._apps.respond_launch(
            intent,
            user_text,
            stt_conf,
            self._is_executable_command(user_text),
            interaction_id,
            replay_mode,
            overrides,
        )

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
        service = getattr(self, "_streaming_responses", None)
        if service is None:
            service = PipelineStreamingResponseService(self)
            self._streaming_responses = service
        return service.generate_and_speak(
            user_text=user_text,
            interaction_id=interaction_id,
            rag_context=rag_context,
            memory_context=memory_context,
            use_convo_buffer=use_convo_buffer,
            replay_mode=replay_mode,
            overrides=overrides,
        )

    def speak(self, text, interaction_id: str = "", force_tts: bool = False):
        speak_text(
            SpeechDependencies(
                logger=self.logger,
                tts_enabled=self.runtime_overrides.get("tts_enabled", True),
                current_state=self.current_state,
                current_voice_key=self.current_voice_key,
                tts_engine=self._tts_engine,
                tts_model=self._tts_model,
                tts_instructions=self._TTS_INSTRUCTIONS,
                edge_voices=self.voices,
                openai_voices=self.openai_voices,
                output_device=getattr(self.audio, "_output_device_index", None),
                stop_signal=self.stop_signal,
                acquire_audio=self.audio.acquire_audio,
                release_audio=self.audio.release_audio,
                transition_state=self.transition_state,
                record_timeline=self._record_timeline,
                record_event=log_event,
                play_error_cue=lambda turn_id: self._play_sound_cue(
                    "error", interaction_id=turn_id
                ),
                broadcast_audio_level=lambda level: self.broadcast(
                    "tts_audio_level", {"rms": level}
                ),
                set_speaking=lambda speaking: setattr(
                    self, "is_speaking", speaking
                ),
                set_finished_at=lambda finished_at: setattr(
                    self, "tts_finished_at", finished_at
                ),
                get_edge_tts=lambda: self._edge_tts,
                set_edge_tts=lambda tts: setattr(self, "_edge_tts", tts),
                get_openai_tts=lambda: self._openai_tts,
                set_openai_tts=lambda tts: setattr(self, "_openai_tts", tts),
                get_barge_in_suppression=lambda: self._pending_barge_in_suppression,
                clear_barge_in_suppression=lambda: setattr(
                    self, "_pending_barge_in_suppression", None
                ),
            ),
            text,
            interaction_id=interaction_id,
            force_tts=force_tts,
        )


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
            self.stop_signal.clear()
            self.timeline_events = []
            if not interaction_id:
                interaction_id = str(uuid.uuid4())
            self.current_interaction_id = interaction_id
            process_interaction_audio(
                InteractionDependencies(
                    logger=self.logger,
                    acquire_audio=self.audio.acquire_audio,
                    release_audio=self.audio.release_audio,
                    transcribe=self.transcribe,
                    read_stt_metrics=lambda: self._last_stt_metrics,
                    set_stt_confidence=lambda confidence: setattr(
                        self, "_current_stt_confidence", confidence
                    ),
                    normalize_text=normalize_system_text,
                    normalize_music_text=lambda text: (
                        self._normalize_music_command_text(text)
                    ),
                    is_prompt_echo=lambda text, confidence: (
                        self._is_low_confidence_stt_prompt_echo(text, confidence)
                    ),
                    record_timeline=self._record_timeline,
                    transition_state=self.transition_state,
                    broadcast=self.broadcast,
                    add_conversation_turn=lambda role, text: (
                        self._conversation_buffer.add(role, text)
                    ),
                    broadcast_turn_info=lambda: self._broadcast_turn_info(),
                    append_conversation_ledger=lambda role, text: (
                        self._append_convo_ledger(role, text)
                    ),
                    handle_user_text=lambda **kwargs: self.handle_user_text(
                        **kwargs
                    ),
                ),
                audio_data,
                interaction_id=interaction_id,
                replay_mode=replay_mode,
                overrides=overrides,
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
        route_user_text(
            self,
            user_text,
            confidence_hint,
            interaction_id,
            replay_mode,
            overrides,
            audio_data,
        )

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
