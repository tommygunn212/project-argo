"""Confidence policy stage for the classic conversation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from core.intent_parser import IntentType, is_system_keyword


@dataclass(frozen=True)
class ConfidenceGateResult:
    handled: bool
    intent: Any


def apply_confidence_gate(
    pipeline: Any,
    user_text: str,
    stt_confidence: float,
    early_intent: Any,
    interaction_id: str,
) -> ConfidenceGateResult:
    """Apply personal/lab confidence policy and preserve reparsed intent state."""
    filler_match = re.fullmatch(
        r"(okay\.?\s*)+|\.+", user_text, flags=re.IGNORECASE
    )
    if not pipeline.strict_lab_mode:
        compact_len = len(re.sub(r"\s+", "", user_text))
        low_confidence = stt_confidence < pipeline._personal_mode_min_confidence
        short_text = compact_len < pipeline._personal_mode_min_text_len
        if low_confidence or short_text:
            try:
                early_intent = pipeline._intent_parser.parse(user_text)
            except Exception:
                early_intent = None
            if early_intent and pipeline._allow_low_conf_music_command(
                early_intent, user_text
            ):
                pipeline.logger.info(
                    "[PERSONAL_MODE] Low confidence but executable music command; continuing"
                )
            elif (
                early_intent
                and early_intent.intent_type == IntentType.APP_LAUNCH
                and pipeline._is_executable_command(user_text)
            ):
                pipeline.logger.info(
                    "[PERSONAL_MODE] Low confidence but executable app launch; continuing"
                )
            elif (
                early_intent
                and early_intent.intent_type == IntentType.APP_CONTROL
                and getattr(early_intent, "action", None) == "close"
                and pipeline._is_executable_command(user_text)
            ):
                pipeline.logger.info(
                    "[PERSONAL_MODE] Low confidence but executable app close; continuing"
                )
            elif re.match(
                r"^(close|quit|exit|shut down|shutdown)\b",
                user_text.strip().lower(),
            ):
                pipeline.logger.info(
                    "[PERSONAL_MODE] Low confidence but explicit close command; continuing"
                )
            elif user_text.strip().endswith("?") or re.match(
                r"^(what|why|how|who|when|where)\b", user_text.strip().lower()
            ):
                pipeline.logger.info(
                    "[PERSONAL_MODE] Low confidence but explicit question; continuing"
                )
            elif re.match(r"^count\b", user_text.strip().lower()):
                pipeline.logger.info(
                    "[PERSONAL_MODE] Low confidence but explicit count command; continuing"
                )
            else:
                pipeline.logger.warning(
                    "[PERSONAL_MODE] Guarded utterance len=%s conf=%.2f "
                    "thresholds(len=%s, conf=%.2f)",
                    compact_len,
                    stt_confidence,
                    pipeline._personal_mode_min_text_len,
                    pipeline._personal_mode_min_confidence,
                )
                pipeline._record_timeline(
                    "PERSONAL_LOW_CONF_GUARD",
                    stage="pipeline",
                    interaction_id=interaction_id,
                )
        return ConfidenceGateResult(False, early_intent)

    if stt_confidence < 0.30 or filler_match:
        pipeline.logger.info(
            f"[STT] Low confidence ({stt_confidence:.2f}) or filler; skipping"
        )
        if (
            not pipeline._low_conf_notice_given
            and pipeline.runtime_overrides.get("tts_enabled", True)
        ):
            pipeline.speak(
                "I didn’t catch that. Try a complete question.",
                interaction_id=interaction_id,
            )
            pipeline._low_conf_notice_given = True
        pipeline.transition_state(
            "LISTENING", interaction_id=interaction_id, source="audio"
        )
        return ConfidenceGateResult(True, early_intent)

    if stt_confidence < 0.35 or not user_text.strip():
        user_text_lower = user_text.lower()
        if is_system_keyword(user_text):
            pipeline.logger.info(
                f"[STT] Low confidence ({stt_confidence:.2f}) but "
                f"whitelisted system intent: {user_text}"
            )
        elif re.search(r"\bcount\b", user_text, flags=re.IGNORECASE):
            pipeline.logger.info(
                f"[STT] Low confidence ({stt_confidence:.2f}) but count detected; continuing"
            )
        elif re.search(r"\bvolume\b", user_text, flags=re.IGNORECASE):
            pipeline.logger.info(
                f"[STT] Low confidence ({stt_confidence:.2f}) but volume intent detected; continuing"
            )
        elif re.search(
            r"\b(remember|save this|from now on|memory|forget)\b",
            user_text,
            flags=re.IGNORECASE,
        ):
            pipeline.logger.info(
                f"[STT] Low confidence ({stt_confidence:.2f}) but memory intent detected; continuing"
            )
        elif any(
            term in user_text_lower
            for term in {"stop", "pause", "cancel", "shut up", "shutup", "shut-up"}
        ):
            pipeline.logger.info(
                f"[STT] Low confidence ({stt_confidence:.2f}) but stop intent detected; continuing"
            )
    return ConfidenceGateResult(False, early_intent)
