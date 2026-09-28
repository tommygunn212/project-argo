"""Computer-vision intent rules."""

from __future__ import annotations

import re

from core.intent_models import Intent, IntentType


def parse_vision_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    # ── Computer Vision ────────────────────────────────────────

    # VISION_READ_ERROR: "read the error on my screen", "what error is that"
    if re.search(r"\b(read|what)\b.*\b(error|warning|exception|traceback|crash)\b.*\b(screen|see|display)?\b", text_lower) or \
       re.search(r"\b(error|warning|exception)\b.*\b(screen|say|mean)\b", text_lower):
        return Intent(
            intent_type=IntentType.VISION_READ_ERROR,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    # VISION_DESCRIBE: "what's on my screen", "describe my screen", "take a screenshot"
    if re.search(r"\b(describe|what(?:'s| is))\b.*\b(screen|see|looking|display|monitor|desktop)\b", text_lower) or \
       re.search(r"\b(look(?:ing)?|see)\b.*\b(screen|monitor|display)\b", text_lower) or \
       re.search(r"\b(take|grab|capture)\b.*\b(screenshot|screen\s?shot|snap|picture)\b", text_lower):
        return Intent(
            intent_type=IntentType.VISION_DESCRIBE,
            confidence=0.96,
            raw_text=text_original,
            serious_mode=serious_mode,
        )

    return None
