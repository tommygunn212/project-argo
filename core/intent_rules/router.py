"""Ordered routing across deterministic domain intent rules."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from core.intent_models import Intent
from core.intent_rules.core_system import parse_identity_or_governance, parse_system_health
from core.intent_rules.filesystem import parse_filesystem_intent
from core.intent_rules.platform import parse_platform_intent
from core.intent_rules.scheduling import parse_scheduling_intent
from core.intent_rules.smart_home import parse_smart_home_intent
from core.intent_rules.task_plan import parse_task_plan_intent
from core.intent_rules.vision import parse_vision_intent
from core.intent_rules.writing import parse_writing_intent


DomainRule = Callable[[str, str, bool], Intent | None]
DOMAIN_RULES: tuple[DomainRule, ...] = (
    parse_platform_intent,
    parse_identity_or_governance,
    parse_writing_intent,
    parse_task_plan_intent,
    parse_smart_home_intent,
    parse_scheduling_intent,
    parse_vision_intent,
    parse_filesystem_intent,
    parse_system_health,
)


def parse_domain_intent(
    raw_text: str,
    normalized: str,
    serious_mode: bool,
    rules: Sequence[DomainRule] = DOMAIN_RULES,
) -> Intent | None:
    for rule in rules:
        intent = rule(raw_text, normalized, serious_mode)
        if intent is not None:
            return intent
    return None
