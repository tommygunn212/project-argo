"""Backend control-command dispatch independent of ``main`` globals."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable


@dataclass(frozen=True)
class BackendControlRuntime:
    smooth_voice_mode: str
    classic_voice_mode: str
    get_voice_mode: Callable[[], str]
    set_voice_mode: Callable[[str, str], None]
    set_listening_enabled: Callable[[bool], None]
    set_server_enabled: Callable[[bool], None]
    get_pipeline: Callable[[], Any]
    get_audio: Callable[[], Any]
    get_main_loop_thread: Callable[[], Any]
    start_main_loop_thread: Callable[[], bool]
    interrupt_current_response: Callable[..., None]
    hard_reset_pipeline: Callable[[str], dict]
    run_noise_calibration: Callable[[], None]
    clear_overrides: Callable[[], None]
    next_interaction_overrides: dict
    broadcast: Callable[[str, Any], None]
    event_logger: Callable[..., None]
    logger: Any


def dispatch_backend_control(runtime: BackendControlRuntime, command: Any) -> None:
    """Apply one UI control command to the current backend runtime."""
    data = {}
    if isinstance(command, dict):
        cmd = str(command.get("command", "")).upper()
        data = command.get("data", {}) or {}
    else:
        cmd = str(command).upper()
    del data  # Reserved for control commands with payloads.

    pipeline = runtime.get_pipeline()
    audio = runtime.get_audio()
    if cmd == "PAUSE":
        runtime.event_logger("UI_CMD_STOP_VAD", stage="ui")
        runtime.set_listening_enabled(False)
        runtime.event_logger("CONTROL_PAUSE", stage="control")
        if pipeline:
            runtime.interrupt_current_response("UI_PAUSE", target_state="IDLE")
        if audio:
            try:
                audio.stop()
            except Exception:
                pass
        runtime.broadcast("status", "IDLE")
        return

    if cmd in ("RESUME", "USE_CLASSIC_VOICE"):
        if cmd == "USE_CLASSIC_VOICE":
            runtime.set_voice_mode(
                runtime.classic_voice_mode, "user switched to classic voice"
            )
        elif runtime.get_voice_mode() == runtime.smooth_voice_mode:
            runtime.logger.warning(
                "[VoiceMode] refused RESUME: Smooth Voice owns the microphone"
            )
            runtime.event_logger("UI_CMD_START_VAD_REFUSED", stage="ui")
            runtime.broadcast(
                "log",
                "Smooth Voice owns the microphone. Switch to classic voice to use it.",
            )
            runtime.broadcast(
                "voice_mode",
                {"mode": runtime.get_voice_mode(), "reason": "resume refused"},
            )
            return
        runtime.event_logger("UI_CMD_START_VAD", stage="ui")
        runtime.set_listening_enabled(True)
        runtime.event_logger("CONTROL_RESUME", stage="control")
        if audio:
            try:
                audio.start()
            except Exception:
                pass
        runtime.start_main_loop_thread()
        if pipeline and pipeline.current_state in {"IDLE", "LISTENING"}:
            pipeline.transition_state("LISTENING", source="ui")
        return

    if cmd == "SERVER_STOP":
        runtime.event_logger("UI_CMD_STOP_SERVER", stage="ui")
        runtime.event_logger("CONTROL_SERVER_STOP", stage="control")
        runtime.broadcast("log", "Server stopping (pipeline thread)...")
        runtime.set_server_enabled(False)
        runtime.set_listening_enabled(False)
        runtime.interrupt_current_response("SERVER_STOP", target_state="IDLE")
        runtime.hard_reset_pipeline("SERVER_STOP")
        if audio:
            try:
                audio.stop()
            except Exception:
                pass
        runtime.broadcast("status", "IDLE")
        return

    if cmd == "HARD_STOP":
        runtime.event_logger("UI_CMD_HARD_STOP", stage="ui")
        result = runtime.hard_reset_pipeline("HARD_STOP")
        runtime.set_listening_enabled(False)
        runtime.broadcast("log", f"Hard stop: {result.get('actions')}")
        runtime.broadcast("status", "IDLE")
        return

    if cmd == "SERVER_START":
        runtime.event_logger("UI_CMD_START_SERVER", stage="ui")
        runtime.event_logger("CONTROL_SERVER_START", stage="control")
        started = runtime.start_main_loop_thread()
        runtime.broadcast(
            "log", "Server start requested" if started else "Server already running"
        )
        return

    if cmd == "SERVER_RESTART":
        runtime.event_logger("UI_CMD_RESTART_SERVER", stage="ui")
        runtime.event_logger("CONTROL_SERVER_RESTART", stage="control")
        runtime.set_server_enabled(False)
        runtime.set_listening_enabled(False)
        runtime.interrupt_current_response("SERVER_RESTART", target_state="IDLE")
        if audio:
            try:
                audio.stop()
            except Exception:
                pass
        main_loop_thread = runtime.get_main_loop_thread()
        if main_loop_thread and main_loop_thread.is_alive():
            main_loop_thread.join(timeout=5.0)
        started = runtime.start_main_loop_thread()
        runtime.broadcast(
            "log", "Server restart requested" if started else "Server already running"
        )
        return

    if cmd == "FORCE_RELEASE_AUDIO":
        runtime.event_logger("UI_CMD_FORCE_RELEASE_AUDIO", stage="ui")
        runtime.interrupt_current_response(
            "UI_FORCE_RELEASE", target_state="LISTENING"
        )
        return

    if cmd == "RESET_INTERACTION":
        runtime.event_logger("UI_CMD_RESET_INTERACTION", stage="ui")
        if pipeline:
            try:
                pipeline.reset_interaction()
            except Exception:
                pass
        runtime.broadcast("status", "LISTENING")
        return

    if cmd == "CALIBRATE_NOISE":
        runtime.event_logger("UI_CMD_CALIBRATE_NOISE", stage="ui")
        runtime.broadcast("log", "Noise calibration requested...")
        threading.Thread(target=runtime.run_noise_calibration, daemon=True).start()
        return

    if cmd in ("FULL_RESET", "FORCE_RESET"):
        runtime.event_logger("UI_CMD_FORCE_RESET", stage="ui")
        runtime.set_server_enabled(False)
        runtime.set_listening_enabled(False)
        runtime.interrupt_current_response("FULL_RESET", target_state="IDLE")
        if audio:
            try:
                audio.stop()
            except Exception:
                pass
        runtime.clear_overrides()
        runtime.next_interaction_overrides.clear()
        time.sleep(0.3)
        started = runtime.start_main_loop_thread()
        runtime.broadcast(
            "log", "Full reset requested" if started else "Server already running"
        )
