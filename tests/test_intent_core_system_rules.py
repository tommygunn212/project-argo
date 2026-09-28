from core.intent_models import IntentType
from core.intent_parser import (
    HARDWARE_KEYWORDS,
    SYSTEM_CPU_QUERIES,
    detect_self_diagnostics,
)
from core.intent_parser import RuleBasedIntentParser
from core.intent_rules.core_system import (
    parse_control_intent,
    parse_full_system_status,
    parse_identity_or_governance,
    parse_system_health,
)


def test_control_intent_priority_and_serious_mode_policy():
    silence = parse_control_intent("shut up and sleep", "shut up and sleep", True, {"sleep"})
    sleep = parse_control_intent("sleep now", "sleep now", True, {"sleep"})
    diagnostics = parse_control_intent(
        "argo is broken", "argo is broken", True, {"sleep"}
    )

    assert silence.intent_type is IntentType.SILENCE_OVERRIDE
    assert silence.serious_mode is False
    assert sleep.intent_type is IntentType.SLEEP
    assert sleep.serious_mode is True
    assert diagnostics.intent_type is IntentType.SELF_DIAGNOSTICS


def test_control_intent_returns_none_for_ordinary_text():
    assert parse_control_intent("hello", "hello", False, {"sleep"}) is None


def test_full_status_is_available_before_wake_word_stripping():
    result = parse_full_system_status("argo status", "argo status", False)

    assert result.intent_type is IntentType.SYSTEM_STATUS
    assert result.subintent == "full"


def test_identity_and_governance_subintents_are_deterministic():
    identity = parse_identity_or_governance("who are you", "who are you", False)
    gates = parse_identity_or_governance("argo gates", "argo gates", False)
    overview = parse_identity_or_governance(
        "argo laws and gates", "argo laws and gates", True
    )

    assert identity.intent_type is IntentType.ARGO_IDENTITY
    assert gates.subintent == "gates"
    assert overview.subintent == "overview"
    assert overview.serious_mode is True


def test_hardware_query_selects_specific_subintent():
    result = parse_system_health("what cpu do i have", "what cpu do i have", False)

    assert result.intent_type is IntentType.SYSTEM_HEALTH
    assert result.subintent == "cpu"


def test_hardware_shopping_and_3d_printing_queries_are_not_machine_status():
    assert parse_system_health("best cpu to buy", "best cpu to buy", False) is None
    assert parse_system_health(
        "3d printer hotend temperature", "3d printer hotend temperature", False
    ) is None


def test_public_parser_facade_still_reexports_keyword_banks():
    assert "cpu" in HARDWARE_KEYWORDS
    assert "what cpu do i have" in SYSTEM_CPU_QUERIES
    assert detect_self_diagnostics("argo is broken")


def test_parser_never_leaks_internal_rule_tables_to_stdout(capsys):
    parser = RuleBasedIntentParser()

    parser.parse("why does coffee cool down?")
    parser.parse("who are you")

    assert capsys.readouterr().out == ""
