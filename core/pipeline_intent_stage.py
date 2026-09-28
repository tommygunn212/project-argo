"""Intent preparation and clarification stage for the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from core.intent_parser import Intent, IntentType


@dataclass(frozen=True)
class IntentStageResult:
    handled: bool
    intent: Any
    request_kind: str
    safe_utterance: str
    low_confidence_audio: bool


def _finish_confirmation(
    pipeline: Any,
    response: str,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> None:
    pipeline.broadcast("log", f"Argo: {response}")
    pipeline._append_convo_ledger("argo", response)
    if not pipeline.stop_signal.is_set() and not replay_mode:
        tts_text = pipeline._sanitize_tts_text(response)
        if (overrides or {}).get("suppress_tts", False):
            pipeline.logger.info("[TTS] Suppressed for next interaction override")
        elif tts_text:
            pipeline.speak(tts_text, interaction_id=interaction_id)
    pipeline.transition_state("LISTENING", interaction_id=interaction_id, source="audio")
    pipeline.logger.info("--- Interaction Complete ---")
    pipeline._record_timeline(
        "INTERACTION_END", stage="pipeline", interaction_id=interaction_id
    )


def prepare_intent_stage(
    pipeline: Any,
    early_intent: Any,
    user_text: str,
    topic: str | None,
    matched: set[str],
    stt_confidence: float,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> IntentStageResult:
    """Prepare parsed intent and apply identity/clarification gates."""
    intent = early_intent
    request_kind = pipeline._classify_request_type(user_text, intent)
    if (
        (intent is None or intent.intent_type != IntentType.MUSIC)
        and user_text.lower().startswith("play")
        and pipeline._music_noun_detected(user_text)
    ):
        keyword = user_text[4:].strip()
        intent = Intent(
            intent_type=IntentType.MUSIC,
            confidence=1.0,
            raw_text=user_text,
            keyword=keyword or None,
        )
        request_kind = "ACTION"
        pipeline.logger.info(
            "[INTENT_OVERRIDE] forced MUSIC due to play+music nouns"
        )

    safe_utterance = re.sub(
        r"\s+", " ", (user_text or "").replace("\n", " ").strip()
    )
    pipeline.logger.info(
        '[INTENT] intent=%s request_kind=%s artist=%s title=%s utterance="%s"',
        intent.intent_type.value if intent else "None",
        request_kind,
        getattr(intent, "artist", None),
        getattr(intent, "title", None),
        safe_utterance,
    )

    if request_kind == "ACTION":
        pipeline._conversation_buffer.clear(reason="command intent")

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
        detected = sorted(
            keyword
            for keyword in music_keywords
            if keyword in safe_utterance.lower()
        )
        if detected:
            pipeline.logger.warning(
                '[INTENT WARNING] intent=None but music keywords detected '
                'keywords=%s utterance="%s"',
                detected,
                safe_utterance,
            )

    if not topic:
        name_candidate = pipeline._extract_name_from_statement(user_text)
        if name_candidate and not pipeline._session_flags.get("confirm_name", False):
            pipeline.logger.info(
                f"[MEMORY] candidate_detected type=identity.name "
                f"value={name_candidate} conf_hint={stt_confidence:.2f}"
            )
            pipeline._pending_memory = {"key": "name", "value": name_candidate}
            pipeline._session_flags["confirm_name"] = True
            response = (
                f"Do you want me to remember that your name is {name_candidate}?"
            )
            pipeline.logger.info("[MEMORY] confirmation_requested")
            pipeline._record_timeline(
                "IDENTITY_CONFIRM_GATE",
                stage="pipeline",
                interaction_id=interaction_id,
            )
            _finish_confirmation(
                pipeline, response, interaction_id, replay_mode, overrides
            )
            return IntentStageResult(
                True, intent, request_kind, safe_utterance, False
            )

    canonical_reason = f"topic:{topic}" if topic else "none"
    pipeline.logger.info(
        f"[CANONICAL] classification={request_kind} "
        f"canonical_reason={canonical_reason}"
    )
    pipeline._record_timeline(
        f"CLASSIFY {request_kind}",
        stage="pipeline",
        interaction_id=interaction_id,
    )
    if request_kind == "ACTION" and intent is None:
        request_kind = "QUESTION"

    ambiguity_prompt = pipeline._ambiguous_short_question_prompt(
        user_text, request_kind, topic
    )
    if ambiguity_prompt:
        pipeline.logger.info(
            '[CLARIFY] triggered reason=ambiguous_short_question text="%s"',
            safe_utterance,
        )
        pipeline._record_timeline(
            "AMBIGUOUS_SHORT_QUESTION_GUARD",
            stage="pipeline",
            interaction_id=interaction_id,
        )
        pipeline._respond_with_clarification(
            interaction_id,
            replay_mode,
            overrides,
            prompt=ambiguity_prompt,
        )
        return IntentStageResult(True, intent, request_kind, safe_utterance, False)

    low_confidence_audio = (
        not pipeline.strict_lab_mode and stt_confidence < 0.50
    )
    if (
        not pipeline.strict_lab_mode
        and request_kind == "QUESTION"
        and low_confidence_audio
    ):
        pipeline.logger.info(
            "[PERSONAL_MODE] Question bypassed confidence gating"
        )

    if (
        request_kind == "QUESTION"
        and 0.35 <= stt_confidence < 0.55
        and not topic
        and pipeline.strict_lab_mode
    ):
        phrase_match = any(" " in match for match in matched) if matched else False
        already_asked = pipeline._session_flags.get("clarification_asked", False)
        if not phrase_match and not already_asked:
            pipeline._session_flags["clarification_asked"] = True
            response = pipeline._get_clarification_prompt()
            pipeline.logger.info(
                f"[CLARIFY] triggered conf={stt_confidence:.2f} "
                "reason=ambiguous_question"
            )
            pipeline._record_timeline(
                "CLARIFY_GATE", stage="pipeline", interaction_id=interaction_id
            )
            _finish_confirmation(
                pipeline, response, interaction_id, replay_mode, overrides
            )
            return IntentStageResult(
                True,
                intent,
                request_kind,
                safe_utterance,
                low_confidence_audio,
            )

    return IntentStageResult(
        False, intent, request_kind, safe_utterance, low_confidence_audio
    )
