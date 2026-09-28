"""Classic system prompts must use the shared persona source of truth."""

from unittest.mock import Mock

import pytest

from core import persona_briefs
from core.pipeline import ArgoPipeline


def _pipeline(examples=""):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline._load_examples = Mock(return_value=examples)
    return pipeline


@pytest.mark.parametrize(
    "mode",
    ["argo", "tommy_gunn", "tommy_mix", "jarvis", "rick", "claptrap", "plain"],
)
def test_classic_prompt_uses_exact_shared_persona_brief(mode):
    prompt = _pipeline()._get_system_message(mode, serious_mode=False)

    assert persona_briefs.get(mode).block in prompt


def test_serious_mode_remains_clean_and_joke_free():
    prompt = _pipeline()._get_system_message("rick", serious_mode=True)

    assert "Serious mode" in prompt
    assert "No jokes" in prompt
    assert persona_briefs.RICK.block not in prompt


def test_tommy_examples_are_appended_to_classic_prompt():
    prompt = _pipeline("EXAMPLE BLOCK\n")._get_system_message(
        "tommy_gunn", serious_mode=False
    )

    assert "EXAMPLE BLOCK" in prompt
