"""Contract tests for classic spoken-response controls."""

from core.pipeline import ArgoPipeline


def _controls(overrides):
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.runtime_overrides = overrides
    return pipeline._get_spoken_response_controls()


def test_spoken_response_controls_coerce_runtime_strings():
    assert _controls(
        {
            "temperature": "1.25",
            "max_tokens": "512",
            "max_sentences": "9",
            "verbosity": "4",
        }
    ) == {
        "temperature": 1.25,
        "max_tokens": 512,
        "max_sentences": 9,
        "verbosity": 4,
    }


def test_spoken_response_controls_clamp_every_boundary():
    assert _controls(
        {
            "temperature": -10,
            "max_tokens": 1,
            "max_sentences": 100,
            "verbosity": 99,
        }
    ) == {
        "temperature": 0.0,
        "max_tokens": 80,
        "max_sentences": 20,
        "verbosity": 5,
    }


def test_spoken_response_controls_fall_back_independently_on_bad_values():
    assert _controls(
        {
            "temperature": "hot",
            "max_tokens": None,
            "max_sentences": [],
            "verbosity": object(),
        }
    ) == {
        "temperature": 0.55,
        "max_tokens": 360,
        "max_sentences": 6,
        "verbosity": 3,
    }
