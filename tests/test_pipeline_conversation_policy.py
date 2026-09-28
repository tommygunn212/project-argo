"""Contract tests for classic conversation style and action policy."""

from types import SimpleNamespace

import pytest

from core.config import ActionRisk, ResponseStyle
from core.intent_parser import IntentType
from core.pipeline import ArgoPipeline


def _intent(intent_type):
    return SimpleNamespace(intent_type=intent_type)


@pytest.mark.parametrize(
    "intent_type",
    [IntentType.ARGO_IDENTITY, IntentType.ARGO_GOVERNANCE],
)
def test_identity_and_governance_responses_allow_personality(intent_type):
    assert ArgoPipeline._get_response_style(None, _intent(intent_type)) == (
        ResponseStyle.SNARK
    )


@pytest.mark.parametrize(
    "intent_type",
    [
        IntentType.MUSIC_STOP,
        IntentType.MUSIC_NEXT,
        IntentType.APP_CONTROL,
        IntentType.APP_LAUNCH,
        IntentType.VOLUME_CONTROL,
        IntentType.BLUETOOTH_CONTROL,
    ],
)
def test_reversible_action_responses_use_dry_style(intent_type):
    assert ArgoPipeline._get_response_style(None, _intent(intent_type)) == (
        ResponseStyle.DRY
    )


def test_missing_or_informational_intent_uses_neutral_style():
    assert ArgoPipeline._get_response_style(None, None) == ResponseStyle.NEUTRAL
    assert ArgoPipeline._get_response_style(
        None, _intent(IntentType.SYSTEM_STATUS)
    ) == ResponseStyle.NEUTRAL


@pytest.mark.parametrize(
    "verb",
    ["delete", "remove", "erase", "wipe", "shutdown", "restart", "reboot"],
)
def test_destructive_word_overrides_reversible_intent(verb):
    assert ArgoPipeline._get_action_risk(
        None, _intent(IntentType.APP_CONTROL), f"{verb} the app"
    ) == ActionRisk.DESTRUCTIVE


def test_kill_everything_phrase_is_destructive_but_kill_alone_is_not():
    intent = _intent(IntentType.SYSTEM_STATUS)

    assert ArgoPipeline._get_action_risk(
        None, intent, "kill everything"
    ) == ActionRisk.DESTRUCTIVE
    assert ArgoPipeline._get_action_risk(
        None, intent, "kill the process"
    ) == ActionRisk.AMBIGUOUS


@pytest.mark.parametrize(
    "intent_type",
    [
        IntentType.MUSIC,
        IntentType.MUSIC_STOP,
        IntentType.MUSIC_NEXT,
        IntentType.APP_CONTROL,
        IntentType.APP_LAUNCH,
        IntentType.VOLUME_CONTROL,
        IntentType.BLUETOOTH_CONTROL,
    ],
)
def test_known_reversible_actions_are_classified_reversible(intent_type):
    assert ArgoPipeline._get_action_risk(
        None, _intent(intent_type), "normal request"
    ) == ActionRisk.REVERSIBLE


def test_missing_intent_remains_ambiguous_even_with_destructive_words():
    assert ArgoPipeline._get_action_risk(None, None, "delete everything") == (
        ActionRisk.AMBIGUOUS
    )


@pytest.mark.parametrize(
    "context",
    ["music_started", "already_open", "already_closed", "", "opened"],
)
def test_successful_actions_are_silent_when_no_ack_is_needed(context):
    assert ArgoPipeline._minimal_ack(None, True, context) is None


@pytest.mark.parametrize("context", ["closed", "stopped", "muted", "unmuted"])
def test_selected_successful_actions_receive_minimal_ack(context):
    assert ArgoPipeline._minimal_ack(None, True, context) == "Done."


def test_failed_action_receives_brief_error():
    assert ArgoPipeline._minimal_ack(None, False, "opened") == "That didn't work."
