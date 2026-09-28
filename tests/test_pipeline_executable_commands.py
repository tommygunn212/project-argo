"""Contract tests for Classic Voice executable-command detection."""

import pytest

from core.pipeline import ArgoPipeline


@pytest.mark.parametrize(
    "text",
    [
        "volume 50",
        "volume 50%?",
        "lower the volume",
        "raise volume",
        "louder",
        "could you make it quieter?",
        "mute",
        "unmute the speakers",
        "open chrome",
        "play some music please",
        "turn on the lights",
        "set a timer",
        "skip this track",
    ],
)
def test_executable_command_forms_are_accepted(text):
    assert ArgoPipeline._is_executable_command(None, text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "???",
        "please open chrome",
        "open chrome?",
        "open what exactly",
        "open maybe chrome",
        "play perhaps some jazz",
        "how does volume work",
        "what happens if I delete it",
        "music is nice",
    ],
)
def test_non_executable_or_hedged_forms_are_rejected(text):
    assert not ArgoPipeline._is_executable_command(None, text)


def test_action_verb_must_be_the_first_token():
    assert ArgoPipeline._is_executable_command(None, "start spotify")
    assert not ArgoPipeline._is_executable_command(None, "argo start spotify")
