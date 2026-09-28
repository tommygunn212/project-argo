"""Runtime normalization for classic spoken-response controls."""

from collections.abc import Mapping
from typing import Any


DEFAULT_SPOKEN_RESPONSE_CONTROLS = {
    "temperature": 0.55,
    "max_tokens": 360,
    "max_sentences": 6,
    "verbosity": 3,
}


def resolve_spoken_response_controls(
    runtime_overrides: Mapping[str, Any],
) -> dict[str, float | int]:
    """Coerce and clamp user-tunable spoken-response settings."""

    defaults = DEFAULT_SPOKEN_RESPONSE_CONTROLS
    try:
        temperature = float(
            runtime_overrides.get("temperature", defaults["temperature"])
        )
    except Exception:
        temperature = defaults["temperature"]
    temperature = max(0.0, min(2.0, temperature))

    try:
        max_tokens = int(runtime_overrides.get("max_tokens", defaults["max_tokens"]))
    except Exception:
        max_tokens = defaults["max_tokens"]
    max_tokens = max(80, min(2048, max_tokens))

    try:
        max_sentences = int(
            runtime_overrides.get("max_sentences", defaults["max_sentences"])
        )
    except Exception:
        max_sentences = defaults["max_sentences"]
    max_sentences = max(1, min(20, max_sentences))

    try:
        verbosity = int(runtime_overrides.get("verbosity", defaults["verbosity"]))
    except Exception:
        verbosity = defaults["verbosity"]
    verbosity = max(1, min(5, verbosity))

    return {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "max_sentences": max_sentences,
        "verbosity": verbosity,
    }
