"""Contract tests for Classic Voice music-text normalization policy."""

from unittest.mock import Mock

import pytest

from core.pipeline import ArgoPipeline


def _pipeline():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.logger = Mock()
    return pipeline


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ("", None)),
        ("Please play music", ("play music", "please")),
        ("Could you please play jazz", ("play jazz", "could you please")),
        ("HEY CAN YOU play Boston", ("play Boston", "hey can you")),
        ("would you", ("", "would you")),
        ("play music", ("play music", None)),
        ("  play music  ", ("  play music  ", None)),
    ],
)
def test_music_politeness_stripping_preserves_existing_contract(text, expected):
    assert ArgoPipeline._strip_politeness_for_music(None, text) == expected


def test_music_keyword_detection_excludes_direct_commands():
    pipeline = _pipeline()
    pipeline._is_executable_command = Mock(return_value=True)

    assert not pipeline._has_music_keywords("play music")


@pytest.mark.parametrize(
    "text",
    ["tell me about music", "is that a song", "information about The Clash"],
)
def test_music_keyword_detection_accepts_nouns_and_known_artists(text):
    pipeline = _pipeline()
    pipeline._is_executable_command = Mock(return_value=False)

    assert pipeline._has_music_keywords(text)


def test_music_normalization_strips_politeness_repairs_pray_and_logs():
    pipeline = _pipeline()

    assert pipeline._normalize_music_command_text(
        "Could you please pray The Clash"
    ) == "play The Clash"
    pipeline.logger.info.assert_called_once_with(
        '[STT_NORMALIZE] stripped_politeness="could you please"'
    )


def test_direct_music_command_is_not_rewritten_or_logged():
    pipeline = _pipeline()

    assert pipeline._normalize_music_command_text("play music") == "play music"
    pipeline.logger.info.assert_not_called()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", False),
        ("ordinary conversation", False),
        ("this song", True),
        ("play jazz", True),
        ("play", False),
        ("tell me about Boston", True),
    ],
)
def test_music_noun_detection(text, expected):
    assert ArgoPipeline._music_noun_detected(None, text) is expected
