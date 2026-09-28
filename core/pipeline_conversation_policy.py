"""Deterministic conversation style and action policy for Classic Voice."""

import re
from typing import Protocol

from core.config import ActionRisk, ResponseStyle
from core.intent_parser import IntentType


class IntentLike(Protocol):
    intent_type: IntentType


_DRY_RESPONSE_INTENTS = {
    IntentType.MUSIC_STOP,
    IntentType.MUSIC_NEXT,
    IntentType.APP_CONTROL,
    IntentType.APP_LAUNCH,
    IntentType.VOLUME_CONTROL,
    IntentType.BLUETOOTH_CONTROL,
}

_REVERSIBLE_ACTION_INTENTS = _DRY_RESPONSE_INTENTS | {IntentType.MUSIC}
_DESTRUCTIVE_ACTION_PATTERN = re.compile(
    r"\b(delete|remove|erase|wipe|kill everything|shutdown|restart|reboot)\b"
)
_ACTION_VERBS = {
    "open",
    "close",
    "quit",
    "exit",
    "shutdown",
    "shut",
    "delete",
    "run",
    "start",
    "stop",
    "enable",
    "disable",
    "install",
    "remove",
    "play",
    "pause",
    "resume",
    "next",
    "skip",
    "set",
    "change",
    "turn",
    "launch",
    "mute",
    "unmute",
    "lower",
    "raise",
}


def get_response_style(intent: IntentLike | None) -> str:
    """Return the stable response tone for an intent."""

    if not intent:
        return ResponseStyle.NEUTRAL
    if intent.intent_type in {IntentType.ARGO_IDENTITY, IntentType.ARGO_GOVERNANCE}:
        return ResponseStyle.SNARK
    if intent.intent_type in _DRY_RESPONSE_INTENTS:
        return ResponseStyle.DRY
    return ResponseStyle.NEUTRAL


def get_action_risk(intent: IntentLike | None, user_text: str = "") -> str:
    """Classify whether an action is reversible, destructive, or ambiguous."""

    if not intent:
        return ActionRisk.AMBIGUOUS
    if _DESTRUCTIVE_ACTION_PATTERN.search((user_text or "").lower()):
        return ActionRisk.DESTRUCTIVE
    if intent.intent_type in _REVERSIBLE_ACTION_INTENTS:
        return ActionRisk.REVERSIBLE
    return ActionRisk.AMBIGUOUS


def minimal_ack(action_result: bool, context: str = "") -> str | None:
    """Return the minimum useful acknowledgment for a completed action."""

    if context in {"music_started", "already_open", "already_closed"}:
        return None
    if action_result:
        if context in {"closed", "stopped", "muted", "unmuted"}:
            return "Done."
        return None
    return "That didn't work."


def is_executable_command(user_text: str) -> bool:
    """Return whether text is an immediate command under the classic rules."""

    if not user_text:
        return False
    text = user_text.strip().lower()
    tokens = re.findall(r"\w+", text)
    if not tokens:
        return False

    if re.search(r"\bvolume\s+\d{1,3}%?\b", text):
        return True
    if re.search(r"\b(lower|raise|increase|decrease)\s+(the\s+)?volume\b", text):
        return True
    if re.search(r"\b(louder|quieter|mute|unmute)\b", text):
        return True

    if tokens[0] not in _ACTION_VERBS:
        return False
    if text.endswith("?"):
        return False
    if re.search(r"\b(what|why|how|who|when|where|explain|describe|define)\b", text):
        return False
    if re.search(r"\b(would|could|can|should|might|maybe|perhaps|possibly)\b", text):
        return False
    if re.search(r"\bwhat happens if\b|\bwhat if\b", text):
        return False
    return True
