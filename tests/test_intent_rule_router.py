from core.intent_models import Intent, IntentType
from core.intent_rules.router import DOMAIN_RULES, parse_domain_intent


def test_domain_rule_order_is_explicit_and_stable():
    assert [rule.__name__ for rule in DOMAIN_RULES] == [
        "parse_platform_intent",
        "parse_identity_or_governance",
        "parse_writing_intent",
        "parse_task_plan_intent",
        "parse_smart_home_intent",
        "parse_scheduling_intent",
        "parse_vision_intent",
        "parse_filesystem_intent",
        "parse_system_health",
    ]


def test_domain_router_returns_first_match_and_stops():
    calls = []

    def no_match(raw_text, normalized, serious_mode):
        calls.append(("first", raw_text, normalized, serious_mode))
        return None

    def match(raw_text, normalized, serious_mode):
        calls.append(("second", raw_text, normalized, serious_mode))
        return Intent(IntentType.COMMAND, 0.8, raw_text, serious_mode=serious_mode)

    def must_not_run(*args):
        raise AssertionError("router did not short-circuit")

    result = parse_domain_intent(
        "Raw Request", "raw request", True, (no_match, match, must_not_run)
    )

    assert result.intent_type is IntentType.COMMAND
    assert calls == [
        ("first", "Raw Request", "raw request", True),
        ("second", "Raw Request", "raw request", True),
    ]


def test_domain_router_returns_none_when_no_rule_matches():
    assert parse_domain_intent("hello", "hello", False, (lambda *_: None,)) is None
