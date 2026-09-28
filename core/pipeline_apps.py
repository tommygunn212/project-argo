"""Application status, lifecycle, and focus responses for the classic pipeline."""

from __future__ import annotations

import re
from typing import Any, Protocol

from core.app_control import (
    app_status_response,
    close_app_deterministic,
    focus_app_deterministic,
    get_active_app,
    is_app_running,
    open_app,
)
from core.app_registry import APP_REGISTRY, get_supported_app_displays, resolve_app_name
from core.app_launch import get_supported_launch_displays, launch_app, resolve_app_launch_target


class AppHost(Protocol):
    logger: Any
    _personal_mode_min_confidence: float

    def _deliver_canonical_response(self, *args, **kwargs) -> bool: ...

    def _evaluate_gates(
        self, capability_key: str, module_key: str, interaction_id: str
    ) -> tuple[bool, str]: ...


class PipelineAppService:
    def __init__(self, host: AppHost) -> None:
        self._host = host

    @staticmethod
    def is_status_text(text: str) -> bool:
        lowered = (text or "").lower()
        return any(
            phrase in lowered
            for phrase in {
                "what apps are running",
                "what applications are running",
                "list running applications",
                "list running apps",
            }
        ) or (
            re.search(r"\b(is|are|do i have)\b", lowered) is not None
            and any(term in lowered for term in {"open", "running"})
        )

    @staticmethod
    def is_control_text(text: str) -> bool:
        return re.search(
            r"\b(open|launch|start|close|quit|exit|shut down|shutdown)\b",
            (text or "").lower(),
        ) is not None

    def _deliver(self, message, interaction_id, replay_mode, overrides) -> bool:
        return self._host._deliver_canonical_response(
            message, interaction_id, replay_mode, overrides,
            enforce_confidence=False, force_tts=True,
        )

    def respond_status(
        self, user_text: str, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        host = self._host
        if self.is_control_text(user_text):
            host.logger.error("[CONTROL/STATUS VIOLATION] App STATUS attempted control")
            return self._deliver(
                "App status cannot change applications. Say a control command explicitly.",
                interaction_id,
                replay_mode,
                overrides,
            )
        host.logger.info("[APP] mode=STATUS")
        return self._deliver(
            app_status_response(user_text), interaction_id, replay_mode, overrides
        )

    def respond_control(
        self,
        intent,
        user_text: str,
        stt_conf: float,
        interaction_id: str,
        replay_mode: bool,
        overrides: dict | None,
    ) -> bool:
        host = self._host
        if self.is_status_text(user_text) and not self.is_control_text(user_text):
            host.logger.error("[CONTROL/STATUS VIOLATION] App CONTROL attempted status-only response")
            return self._log_and_deliver(
                "App control requires an explicit command.", interaction_id, replay_mode, overrides
            )
        if not self.is_control_text(user_text):
            return self._log_and_deliver(
                "App control requires an explicit command.", interaction_id, replay_mode, overrides
            )
        action = getattr(intent, "action", None)
        if action != "close" and stt_conf < host._personal_mode_min_confidence:
            return self._log_and_deliver(
                "App command unclear. Please repeat.", interaction_id, replay_mode, overrides
            )
        app_key = resolve_app_name(user_text)
        if not app_key:
            supported = ", ".join(get_supported_app_displays())
            message = (
                f"Which app should I close? I can close {supported}."
                if action == "close"
                else "I don't have a known application called that."
            )
            return self._log_and_deliver(message, interaction_id, replay_mode, overrides)
        if action == "close":
            host.logger.info("[INTENT] APP_CONTROL close")
        if action != "close":
            allowed, reason = host._evaluate_gates(
                "app_control", "app_control", interaction_id
            )
            if not allowed:
                return self._log_and_deliver(
                    f"App control blocked by policy ({reason}).",
                    interaction_id,
                    replay_mode,
                    overrides,
                )
        host.logger.info(f"[APP] mode=CONTROL action={action} target={app_key}")
        if action in {"open", "launch"}:
            _ok, message = open_app(app_key)
        elif action in {"close", "quit"}:
            _ok, message, pid, result = close_app_deterministic(app_key)
            pid_display = pid if pid is not None else "<none>"
            host.logger.info(
                f"[APP_CONTROL] action=close app={app_key} pid={pid_display} result={result}"
            )
        elif action == "focus":
            _ok, message, _ = focus_app_deterministic(app_key)
        else:
            _ok, message = False, "App control requires an explicit command."
        return self._log_and_deliver(message, interaction_id, replay_mode, overrides)

    def _log_and_deliver(self, message, interaction_id, replay_mode, overrides) -> bool:
        self._host.logger.info(f"Argo: {message}")
        return self._deliver(message, interaction_id, replay_mode, overrides)

    def respond_focus_status(
        self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        target = getattr(intent, "target", None) if intent else None
        if target:
            display = APP_REGISTRY.get(target, {}).get("display", target.capitalize())
            if not is_app_running(target):
                message = f"{display} isn't running."
            else:
                active_key, active_display = get_active_app()
                message = (
                    f"Yes, {active_display or display} is focused."
                    if active_key == target
                    else f"{display} is running but not focused."
                )
            return self._deliver(message, interaction_id, replay_mode, overrides)
        _active_key, active_display = get_active_app()
        message = f"Active app is {active_display}." if active_display else "Active app unavailable."
        return self._deliver(message, interaction_id, replay_mode, overrides)

    def respond_focus_control(
        self, intent, interaction_id: str, replay_mode: bool, overrides: dict | None
    ) -> bool:
        target = getattr(intent, "target", None) if intent else None
        if not target:
            message = f"Which app should I focus? I can focus {', '.join(get_supported_app_displays())}."
            return self._deliver(message, interaction_id, replay_mode, overrides)
        allowed, reason = self._host._evaluate_gates(
            "app_focus_control", "app_focus", interaction_id
        )
        if not allowed:
            return self._deliver(
                f"App focus blocked by policy ({reason}).",
                interaction_id,
                replay_mode,
                overrides,
            )
        _ok, message, _ = focus_app_deterministic(target)
        return self._deliver(message, interaction_id, replay_mode, overrides)

    @staticmethod
    def has_disallowed_launch_tokens(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(
            (
                re.search(r"https?://|www\.", lowered),
                re.search(r"[a-zA-Z]:\\", text),
                re.search(r"\\\\", text),
                re.search(r"\s--?\w+", lowered),
                re.search(r"\s/\w+", lowered),
                re.search(r"[\"']", text),
                re.search(r"\.(txt|docx|xlsx|pdf|png|jpg|jpeg|gif|mp3|mp4|exe)\b", lowered),
            )
        )

    def respond_launch(
        self,
        intent,
        user_text: str,
        stt_conf: float,
        executable_command: bool,
        interaction_id: str,
        replay_mode: bool,
        overrides: dict | None,
    ) -> bool:
        host = self._host
        if stt_conf < host._personal_mode_min_confidence and not executable_command:
            return self._log_and_deliver(
                "App launch command unclear. Please repeat.",
                interaction_id,
                replay_mode,
                overrides,
            )
        if self.has_disallowed_launch_tokens(user_text):
            host.logger.info("[APP_LAUNCH] app=<unknown> result=rejected source=voice")
            return self._log_and_deliver(
                "App launch only supports core apps without files, URLs, or arguments.",
                interaction_id,
                replay_mode,
                overrides,
            )
        app_key = getattr(intent, "target", None) or resolve_app_launch_target(user_text)
        if not app_key:
            host.logger.info("[APP_LAUNCH] app=<unknown> result=rejected source=voice")
            return self._log_and_deliver(
                f"I can open {', '.join(get_supported_launch_displays())}.",
                interaction_id,
                replay_mode,
                overrides,
            )
        allowed, reason = host._evaluate_gates("app_launch", "app_launch", interaction_id)
        if not allowed:
            host.logger.info(f"[APP_LAUNCH] app={app_key} result=failed source=voice")
            return self._log_and_deliver(
                f"App launch blocked by policy ({reason}).",
                interaction_id,
                replay_mode,
                overrides,
            )
        ok = launch_app(app_key)
        display_name = {
            "notepad": "Notepad",
            "calculator": "Calculator",
            "microsoft edge": "Microsoft Edge",
            "file explorer": "File Explorer",
            "powershell": "PowerShell",
        }.get(app_key, app_key.title())
        result = "success" if ok else "failed"
        host.logger.info(f"[APP_LAUNCH] app={app_key} result={result} source=voice")
        message = f"Opening {display_name}." if ok else f"I couldn't open {display_name}."
        return self._log_and_deliver(message, interaction_id, replay_mode, overrides)
