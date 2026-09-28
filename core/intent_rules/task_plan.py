"""Multi-domain task-planner intent rule."""

from __future__ import annotations

import re

from core.intent_models import Intent, IntentType


def parse_task_plan_intent(text_original: str, text_lower: str, serious_mode: bool) -> Intent | None:
    # ── Task Planner (must be before individual Smart Home/Reminder/Calendar/Vision/File rules) ──

    # TASK_PLAN: multi-step requests with connectors across domains
    if (" and then " in text_lower or " then " in text_lower or " and also " in text_lower or " after that " in text_lower or " followed by " in text_lower):
        # Must touch at least 2 different action domains
        _domains = 0
        for _dp in [r"\b(email|send|draft|write)\b", r"\b(remind|reminder)\b",
                    r"\b(calendar|schedule|event|appointment)\b", r"\b(search|find|look for|locate)\b",
                    r"\b(screen|screenshot|describe)\b", r"\b(note|save|jot)\b",
                    r"\b(research|look up|summarize)\b", r"\b(lights?|thermostat|smart\s*home|turn\s+on|turn\s+off)\b"]:
            if re.search(_dp, text_lower):
                _domains += 1
        if _domains >= 2:
            return Intent(
                intent_type=IntentType.TASK_PLAN,
                confidence=0.94,
                raw_text=text_original,
                serious_mode=serious_mode,
            )

    return None
