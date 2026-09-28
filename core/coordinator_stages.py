"""Explicit interaction stages used by :mod:`core.coordinator`."""

from __future__ import annotations

from datetime import datetime
import io
from dataclasses import dataclass
import re
import time
from typing import Any, Callable, Optional

from core.intent_parser import Intent, IntentType, is_system_keyword, normalize_system_text
from core.config import get_config
from core.state_machine import State
from system_profile import get_gpu_profile, get_system_profile


def capture_audio_stage(
    coordinator: Any,
    initial_frames: Optional[list] = None,
) -> bytes:
    """Record one utterance and return a WAV payload for STT."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] "
        f"Recording (max {coordinator.MAX_RECORDING_DURATION}s, stops on "
        f"{coordinator.SILENCE_DURATION}s silence)..."
    )
    coordinator.current_probe.mark("recording_start")

    if coordinator.on_recording_start:
        try:
            coordinator.on_recording_start()
        except Exception as exc:
            coordinator.logger.debug(
                f"[Coordinator] on_recording_start callback error: {exc}"
            )

    audio = coordinator._record_with_silence_detection(
        initial_frames=initial_frames
    )
    coordinator.current_probe.mark("recording_end")

    if coordinator.on_recording_stop:
        try:
            coordinator.on_recording_stop()
        except Exception as exc:
            coordinator.logger.debug(
                f"[Coordinator] on_recording_stop callback error: {exc}"
            )

    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Recorded {len(audio)} "
        f"samples ({len(audio) / coordinator.AUDIO_SAMPLE_RATE:.2f}s)"
    )

    from scipy.io import wavfile

    audio_buffer = io.BytesIO()
    wavfile.write(audio_buffer, coordinator.AUDIO_SAMPLE_RATE, audio)
    audio_bytes = audio_buffer.getvalue()
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Audio buffer: "
        f"{len(audio_bytes)} bytes"
    )
    return audio_bytes


def transcribe_audio_stage(coordinator: Any, audio_bytes: bytes) -> str:
    """Transcribe one WAV payload and update observer/timing state."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Transcribing audio..."
    )
    coordinator.current_probe.mark("stt_start")
    text = coordinator.stt.transcribe(
        audio_bytes, coordinator.AUDIO_SAMPLE_RATE
    )
    coordinator.logger.info(f"[STT RAW] '{text}'")
    coordinator.current_probe.mark("stt_end")

    coordinator._last_wake_timestamp = datetime.now()
    coordinator._last_transcript = text
    coordinator.dynamic_silence_timeout = coordinator.get_dynamic_timeout(text)
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Transcribed: '{text}'"
    )
    return text


@dataclass(frozen=True)
class TranscriptStageResult:
    continue_processing: bool
    interaction_result: bool
    text: str
    stt_confidence: float


def process_transcript_stage(
    coordinator: Any,
    text: str,
    overrides: dict[str, Any],
) -> TranscriptStageResult:
    """Admit, normalize, or terminally handle a raw transcript."""
    if overrides.get("force_passive_listening"):
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Passive listening "
            "override active; skipping intent/command"
        )
        return TranscriptStageResult(False, False, text, 0.0)

    if coordinator.last_response_text:
        similarity = coordinator._similarity_ratio(
            text, coordinator.last_response_text
        )
        if similarity >= 0.80:
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Self-echo detected "
                f"(similarity={similarity:.2f}); discarding transcript"
            )
            coordinator.interaction_count -= 1
            return TranscriptStageResult(False, False, text, 0.0)

    run_triggers = {"run it", "test it", "run", "test"}
    if (
        coordinator._last_built_script
        and text.lower().strip() in run_triggers
    ):
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Running sandbox script: "
            f"{coordinator._last_built_script}"
        )
        output = coordinator.builder.test_run(coordinator._last_built_script)
        analysis_intent = Intent(
            intent_type=IntentType.DEVELOP,
            confidence=1.0,
            raw_text=(
                f"The script '{coordinator._last_built_script}' was executed. "
                f"Output:\n{output}\nSummarize the result and suggest next steps."
            ),
        )
        response_text = coordinator.generator.generate(
            analysis_intent, coordinator.memory
        )
        coordinator._last_response = response_text
        coordinator.last_response_text = response_text
        coordinator._safe_speak(
            response_text, interaction_id=coordinator.interaction_id
        )
        coordinator.memory.append(
            user_utterance=text,
            parsed_intent=analysis_intent.intent_type.value,
            generated_response=response_text,
        )
        coordinator._last_utterance_time = time.time()
        return TranscriptStageResult(False, True, text, 0.0)

    if not text or not text.strip():
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Empty transcription "
            "(silence only), skipping..."
        )
        coordinator.interaction_count -= 1
        return TranscriptStageResult(False, False, text, 0.0)

    try:
        stt_metrics = coordinator.stt.get_last_metrics()
    except Exception:
        stt_metrics = None
    stt_confidence = 0.0
    if stt_metrics:
        try:
            stt_confidence = float(stt_metrics.get("confidence", 0.0))
        except Exception:
            stt_confidence = 0.0

    text = normalize_system_text(text)
    if stt_confidence < 0.35 or not text.strip():
        if is_system_keyword(text):
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Low STT confidence "
                f"({stt_confidence:.2f}) but whitelisted system intent: {text}"
            )
        elif re.search(r"\bcount\b", text, flags=re.IGNORECASE):
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Low STT confidence "
                f"({stt_confidence:.2f}) but count detected; continuing"
            )
        elif stt_confidence < 0.10 or not text.strip():
            coordinator.logger.info(
                f"[Iteration {coordinator.interaction_count}] Low STT confidence "
                f"({stt_confidence:.2f}); skipping"
            )
            if (
                not coordinator._low_conf_notice_given
                and coordinator.runtime_overrides.get("tts_enabled", True)
            ):
                coordinator._safe_speak(
                    "I didn’t catch that clearly. Try saying it as a full sentence.",
                    interaction_id=coordinator.interaction_id,
                )
                coordinator._low_conf_notice_given = True
            coordinator.interaction_count -= 1
            return TranscriptStageResult(
                False, False, text, stt_confidence
            )

    return TranscriptStageResult(True, False, text, stt_confidence)


@dataclass(frozen=True)
class IntentParseStageResult:
    continue_processing: bool
    interaction_result: bool
    intent: Any


def parse_intent_stage(
    coordinator: Any,
    text: str,
    log_event_fn: Any,
) -> IntentParseStageResult:
    """Parse intent and enforce unknown/query confidence policy."""
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Parsing intent..."
    )
    coordinator.current_probe.mark("parsing_start")
    intent = coordinator.parser.parse(text)
    coordinator.current_probe.mark("parsing_end")
    coordinator._last_intent = intent
    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] Intent: "
        f"{intent.intent_type.value} (confidence={intent.confidence:.2f})"
    )

    if intent.intent_type == IntentType.UNKNOWN and intent.confidence < 0.5:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "Low-confidence unknown intent, ignoring."
        )
        coordinator.interaction_count -= 1
        return IntentParseStageResult(False, False, intent)

    try:
        stt_metrics = coordinator.stt.get_last_metrics()
    except Exception:
        stt_metrics = None
    confidence_threshold = get_config().get(
        "speech_to_text.command_confidence_threshold", 0.35
    )
    deterministic = intent.intent_type in {
        IntentType.COMMAND,
        IntentType.COUNT,
        IntentType.MUSIC,
        IntentType.MUSIC_NEXT,
        IntentType.MUSIC_STOP,
        IntentType.MUSIC_STATUS,
        IntentType.SYSTEM_HEALTH,
        IntentType.SYSTEM_INFO,
        IntentType.APP_CONTROL,
        IntentType.ARGO_IDENTITY,
        IntentType.ARGO_GOVERNANCE,
    } or coordinator.executor.can_execute(text)

    if stt_metrics:
        stt_confidence = float(stt_metrics.get("confidence", 0.0))
        if stt_confidence < confidence_threshold:
            if deterministic:
                coordinator.logger.info(
                    "[TTS] Allowed despite low STT confidence "
                    "(reason=DETERMINISTIC_CONFIDENCE_BYPASS, "
                    f"confidence={stt_confidence:.2f}, "
                    f"intent={intent.intent_type.value})"
                )
            else:
                message = "Query suppressed — low STT confidence"
                coordinator.logger.warning(
                    f"[Iteration {coordinator.interaction_count}] {message} "
                    f"(conf={stt_confidence:.2f} < {confidence_threshold:.2f})"
                )
                log_event_fn(
                    f"QUERY_SUPPRESSED_LOW_STT conf={stt_confidence:.2f} "
                    f"threshold={confidence_threshold:.2f}",
                    stage="stt",
                )
                if coordinator.runtime_overrides.get("tts_enabled", True):
                    coordinator._safe_speak(
                        message, interaction_id=coordinator.interaction_id
                    )
                coordinator.current_probe.mark("llm_end")
                coordinator.current_probe.mark("tts_start")
                coordinator.current_probe.mark("tts_end")
                coordinator.current_probe.log_summary()
                coordinator.latency_stats.add_probe(coordinator.current_probe)
                return IntentParseStageResult(False, True, intent)

    return IntentParseStageResult(True, False, intent)


@dataclass(frozen=True)
class DeterministicStageResult:
    handled: bool
    interaction_result: bool
    output_produced: bool


def _finish_deterministic_latency(coordinator: Any) -> None:
    coordinator._last_utterance_time = time.time()
    coordinator.current_probe.mark("llm_end")
    coordinator.current_probe.mark("tts_start")
    coordinator.current_probe.mark("tts_end")
    coordinator.current_probe.log_summary()
    coordinator.latency_stats.add_probe(coordinator.current_probe)


def _system_info_response(intent: Any) -> str:
    profile = get_system_profile()
    gpus = get_gpu_profile()
    subintent = getattr(intent, "subintent", None)
    if subintent == "memory":
        ram_gb = profile.get("ram_gb") if profile else None
        return (
            f"Your system has {ram_gb} gigabytes of memory."
            if ram_gb is not None
            else "Hardware information unavailable."
        )
    if subintent == "cpu":
        cpu_name = profile.get("cpu") if profile else None
        return (
            f"Your CPU is a {cpu_name}."
            if cpu_name
            else "Hardware information unavailable."
        )
    if subintent == "gpu":
        return f"Your GPU is {gpus[0].get('name')}." if gpus else "No GPU detected."
    if subintent == "os":
        os_name = profile.get("os") if profile else None
        return (
            f"You are running {os_name}."
            if os_name
            else "Hardware information unavailable."
        )
    if subintent == "motherboard":
        board = profile.get("motherboard") if profile else None
        return (
            f"Your motherboard is {board}."
            if board
            else "Hardware information unavailable."
        )
    return "Hardware information unavailable."


def dispatch_simple_deterministic_stage(
    coordinator: Any,
    intent: Any,
    text: str,
) -> DeterministicStageResult:
    """Handle sleep, count, and simple system-profile requests."""
    if intent.intent_type == IntentType.SLEEP:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Sleep command detected"
        )
        output_produced = False
        try:
            coordinator._safe_speak("Going quiet.")
            output_produced = True
        except Exception:
            pass
        coordinator._safe_transition(
            coordinator.state_machine.sleep,
            State.SLEEP,
            source="ui",
            interaction_id=str(coordinator.interaction_id),
        )
        _finish_deterministic_latency(coordinator)
        return DeterministicStageResult(True, True, output_produced)

    if intent.intent_type == IntentType.COUNT:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] Count command detected"
        )
        response_text = coordinator._build_count_response(text)
        output_produced = False
        try:
            coordinator._safe_speak(
                response_text, interaction_id=coordinator.interaction_id
            )
            output_produced = True
        except Exception:
            pass
        _finish_deterministic_latency(coordinator)
        return DeterministicStageResult(True, True, output_produced)

    if intent.intent_type == IntentType.SYSTEM_INFO:
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "System profile command detected"
        )
        response_text = _system_info_response(intent)
        output_produced = False
        try:
            coordinator._safe_speak(
                response_text, interaction_id=coordinator.interaction_id
            )
            output_produced = True
        except Exception:
            pass
        _finish_deterministic_latency(coordinator)
        return DeterministicStageResult(True, True, output_produced)

    return DeterministicStageResult(False, False, False)


@dataclass(frozen=True)
class ProceduralStageResult:
    """Outcome of direct command-executor routing."""

    handled: bool
    interaction_result: bool
    output_produced: bool


def dispatch_procedural_stage(
    coordinator: Any,
    text: str,
    mark_output: Callable[[], None],
    finalize_watchdog: Callable[[], None],
) -> ProceduralStageResult:
    """Execute a supported procedural command without entering the LLM path."""
    if not coordinator.executor.can_execute(text):
        return ProceduralStageResult(False, False, False)

    coordinator.logger.info(
        f"[Iteration {coordinator.interaction_count}] "
        f"Procedural command detected: '{text}'"
    )
    coordinator.current_probe.mark("llm_start")
    output_produced = False
    try:
        coordinator.executor.execute(text)
        output_produced = True
        mark_output()
        coordinator.current_probe.mark("llm_end")
        coordinator.logger.info(
            f"[Iteration {coordinator.interaction_count}] "
            "Procedural command complete"
        )
    except Exception as exc:
        coordinator.logger.error(
            f"[Iteration {coordinator.interaction_count}] "
            f"Procedural command failed: {exc}"
        )
        coordinator.current_probe.mark("llm_end")

    finalize_watchdog()
    coordinator._last_utterance_time = time.time()
    return ProceduralStageResult(True, True, output_produced)
