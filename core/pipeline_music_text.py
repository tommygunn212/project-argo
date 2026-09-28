"""Music-specific text classification and normalization for Classic Voice."""

import re
from collections.abc import Callable, Collection
from typing import Any


_MUSIC_KEYWORD_PATTERN = re.compile(
    r"\b(play|pray|music|song|album|artist|track|playlist|genre)\b"
)
_MUSIC_NOUN_PATTERN = re.compile(
    r"\b(music|song|album|artist|track|playlist|genre)\b"
)
_POLITENESS_PHRASES = (
    "can you please",
    "could you please",
    "would you please",
    "hey can you",
    "hey could you",
    "hey please",
    "can you",
    "could you",
    "would you",
    "please",
)


def has_music_keywords(
    text: str,
    *,
    is_executable_command: Callable[[str], bool],
    known_artists: Collection[str],
) -> bool:
    """Detect music language only when text is not already a direct command."""

    if not text:
        return False
    lowered = text.lower()
    if is_executable_command(lowered):
        return False
    if _MUSIC_KEYWORD_PATTERN.search(lowered):
        return True
    return any(artist in lowered for artist in known_artists)


def strip_music_politeness(text: str) -> tuple[str, str | None]:
    """Strip one recognized leading courtesy phrase from music text."""

    if not text:
        return text, None
    lowered = text.strip().lower()
    for phrase in _POLITENESS_PHRASES:
        if lowered == phrase:
            return "", phrase
        if lowered.startswith(phrase + " "):
            return text.strip()[len(phrase) :].strip(), phrase
    return text, None


def normalize_music_command_text(
    text: str,
    *,
    has_keywords: Callable[[str], bool],
    strip_politeness: Callable[[str], tuple[str, str | None]],
    logger: Any,
) -> str:
    """Normalize courtesy-prefixed commands and the STT 'pray' homophone."""

    if not text or not has_keywords(text):
        return text
    cleaned, stripped_phrase = strip_politeness(text)
    if stripped_phrase:
        logger.info(f'[STT_NORMALIZE] stripped_politeness="{stripped_phrase}"')
    normalized = cleaned.strip()
    if re.match(r"^pray\b", normalized, flags=re.IGNORECASE):
        normalized = re.sub(
            r"^pray\b", "play", normalized, flags=re.IGNORECASE
        ).strip()
    return normalized


def music_noun_detected(text: str, known_artists: Collection[str]) -> bool:
    """Return whether text contains a music noun, play target, or known artist."""

    if not text:
        return False
    lowered = text.lower()
    if _MUSIC_NOUN_PATTERN.search(lowered):
        return True
    if re.match(r"^play\b", lowered) and len(lowered.split()) > 1:
        return True
    return any(artist in lowered for artist in known_artists)
