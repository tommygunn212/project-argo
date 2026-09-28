"""Platform-control intent routing for the classic conversation pipeline."""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

from core.intent_parser import IntentType


class _Arguments(Enum):
    USER_TEXT = auto()
    INTENT = auto()
    INTENT_TEXT_CONFIDENCE = auto()
    INTERACTION = auto()


_PLATFORM_HANDLERS = {
    IntentType.BLUETOOTH_STATUS: ("_respond_with_bluetooth_status", _Arguments.USER_TEXT),
    IntentType.BLUETOOTH_CONTROL: (
        "_respond_with_bluetooth_control",
        _Arguments.INTENT_TEXT_CONFIDENCE,
    ),
    IntentType.AUDIO_ROUTING_STATUS: (
        "_respond_with_audio_routing_status",
        _Arguments.USER_TEXT,
    ),
    IntentType.AUDIO_ROUTING_CONTROL: (
        "_respond_with_audio_routing_control",
        _Arguments.INTENT_TEXT_CONFIDENCE,
    ),
    IntentType.APP_STATUS: ("_respond_with_app_status", _Arguments.USER_TEXT),
    IntentType.APP_FOCUS_STATUS: ("_respond_with_focus_status", _Arguments.INTENT),
    IntentType.APP_FOCUS_CONTROL: ("_respond_with_focus_control", _Arguments.INTENT),
    IntentType.APP_LAUNCH: (
        "_respond_with_app_launch",
        _Arguments.INTENT_TEXT_CONFIDENCE,
    ),
    IntentType.APP_CONTROL: (
        "_respond_with_app_control",
        _Arguments.INTENT_TEXT_CONFIDENCE,
    ),
    IntentType.VOLUME_STATUS: (
        "_respond_with_system_volume_status",
        _Arguments.INTERACTION,
    ),
    IntentType.VOLUME_CONTROL: (
        "_respond_with_system_volume_control",
        _Arguments.USER_TEXT,
    ),
    IntentType.TIME_STATUS: ("_respond_with_time_status", _Arguments.INTENT),
    IntentType.WORLD_TIME: ("_respond_with_world_time", _Arguments.INTENT),
}


def dispatch_platform_intent(
    pipeline: Any,
    intent: Any,
    user_text: str,
    stt_confidence: float,
    interaction_id: str,
    replay_mode: bool,
    overrides: dict[str, Any] | None,
) -> bool:
    """Dispatch device, application, volume, and clock intents."""
    if intent is None:
        return False

    route = _PLATFORM_HANDLERS.get(intent.intent_type)
    if route is None:
        return False

    handler_name, argument_shape = route
    handler = getattr(pipeline, handler_name)
    trailing = (interaction_id, replay_mode, overrides)
    if argument_shape is _Arguments.USER_TEXT:
        arguments = (user_text, *trailing)
    elif argument_shape is _Arguments.INTENT:
        arguments = (intent, *trailing)
    elif argument_shape is _Arguments.INTENT_TEXT_CONFIDENCE:
        arguments = (intent, user_text, stt_confidence, *trailing)
    else:
        arguments = trailing
    return bool(handler(*arguments))
