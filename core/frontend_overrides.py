"""Dashboard runtime-override dispatch and cross-process voice persistence."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class FrontendOverrideDependencies:
    set_runtime_override: Callable[[str, Any], None]
    get_runtime_overrides: Callable[[], dict]
    get_pipeline: Callable[[], Any]
    set_root_log_level: Callable[[str], None]
    log_event: Callable[..., None]
    broadcast: Callable[[str, Any], None]
    logger: Any


def dispatch_frontend_override(
    dependencies: FrontendOverrideDependencies,
    payload: dict,
) -> None:
    """Apply one dashboard override and persist Smooth Voice selections."""

    key = payload.get("key")
    value = payload.get("value")
    if not key:
        return

    dependencies.set_runtime_override(key, value)
    pipeline = dependencies.get_pipeline()
    if key == "debug_level":
        try:
            dependencies.set_root_log_level(str(value).upper())
        except Exception:
            pass
    if key == "tts_model" and pipeline:
        pipeline.set_tts_model(str(value))
    if key == "personality_mode":
        try:
            from core.livekit_config import write_voice_personality

            write_voice_personality(str(value))
            dependencies.log_event(
                f"VOICE_PERSONALITY_PERSISTED {value}", stage="ui"
            )
        except Exception:
            dependencies.logger.exception(
                "[OVERRIDE] Could not persist voice personality"
            )
    if key == "realtime_voice":
        try:
            from core.livekit_config import write_realtime_voice

            write_realtime_voice(str(value))
            dependencies.log_event(f"REALTIME_VOICE_PERSISTED {value}", stage="ui")
        except Exception as exc:
            dependencies.logger.exception(
                "[OVERRIDE] Could not persist realtime voice"
            )
            dependencies.broadcast("log", f"Voice not saved: {exc}")
    if pipeline and hasattr(pipeline, "apply_runtime_tuning"):
        try:
            pipeline.apply_runtime_tuning()
        except Exception:
            dependencies.logger.exception(
                "[OVERRIDE] Failed to apply runtime tuning"
            )
    dependencies.log_event(f"UI_CMD_SET_OVERRIDE {key}={value}", stage="ui")
    dependencies.broadcast("runtime_overrides", dependencies.get_runtime_overrides())
