"""Safe dashboard status for LiveKit, mobile access, and speaker identity."""

from __future__ import annotations

import os
import re
import socket
from importlib import metadata
from typing import Any
from urllib.parse import urlparse

from core.livekit_avatar import hedra_avatar_status
from core.livekit_preferences import REALTIME_VOICES, read_voice_mode


def _active_now() -> dict[str, Any] | None:
    try:
        from core.voice_active import read_active
        return read_active()
    except Exception:
        return None


def _persona_list() -> list[dict[str, str]]:
    try:
        from core.persona_briefs import selectable
        return selectable()
    except Exception:
        return []


def livekit_status(config: Any | None = None) -> dict[str, Any]:
    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config(config)
    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": cfg.room,
        "agent_name": cfg.agent_name,
        "model": cfg.model,
        "voice": cfg.voice,
        "server_reachable": _socket_reachable(cfg.url),
        "personality": cfg.personality,
        "avatar": hedra_avatar_status(config),
        "speaker_identity": speaker_identity_status(cfg),
        "voice_mode": read_voice_mode(),
        "active_now": _active_now(),
        "saved_for_next": {
            "model": cfg.model,
            "voice": cfg.voice,
            "personality": cfg.personality,
            "instruction_fingerprint": cfg.instruction_fingerprint,
        },
        "personas": _persona_list(),
        "voices": [{"name": voice, "label": label} for voice, label in REALTIME_VOICES],
        "interruption": {
            "allowed": True,
            "min_duration": cfg.min_interruption_duration,
            "min_words": cfg.min_interruption_words,
            "false_timeout": cfg.false_interruption_timeout,
        },
        "turn_detection": {"mode": cfg.turn_detection, "eagerness": cfg.turn_eagerness},
        "urgent_interrupt_phrases": list(cfg.urgent_interrupt_phrases),
        "fallback_model": cfg.fallback_model,
        "noise_cancellation": cfg.noise_cancellation,
        "input_noise_reduction": cfg.input_noise_reduction,
        "deep_think": {
            "enabled": cfg.deep_think_enabled,
            "model": cfg.deep_think_model,
            "timeout_seconds": cfg.deep_think_timeout,
        },
    }


def mobile_access_status(request_host: str | None = None) -> dict[str, Any]:
    host = _clean_request_host(request_host) or _best_lan_ip() or "127.0.0.1"
    http_port = _int(os.getenv("ARGO_HTTP_PORT", "8000"), 8000)
    ws_port = _int(os.getenv("ARGO_WS_PORT", "8001"), 8001)
    return {
        "host": host,
        "http_url": f"http://{host}:{http_port}/v2",
        "ws_url": f"ws://{host}:{ws_port}/ws",
        "livekit": livekit_status(),
        "note": "Use this URL from an iPad or phone on the same network; browser microphone permission must be allowed.",
    }


def speaker_identity_status(cfg: Any | None = None) -> dict[str, Any]:
    if cfg is None:
        from core.livekit_config import get_livekit_realtime_config
        cfg = get_livekit_realtime_config()
    provider = str(cfg.speaker_id_provider or "speechmatics").strip().lower()
    api_key_ready = bool(os.getenv("SPEECHMATICS_API_KEY", "").strip()) if provider == "speechmatics" else False
    plugin_ready = False
    plugin_error = ""
    if provider == "speechmatics":
        try:
            metadata.version("livekit-plugins-speechmatics")
        except Exception as exc:
            plugin_error = str(exc)
        else:
            plugin_ready = True
    else:
        plugin_error = f"Unsupported speaker identity provider: {provider}"
    return {
        "enabled": bool(cfg.speaker_id_enabled),
        "provider": provider,
        "api_key_ready": api_key_ready,
        "plugin_ready": plugin_ready,
        "ready": bool(cfg.speaker_id_enabled and api_key_ready and plugin_ready),
        "mode": "experimental_sidecar",
        "error": plugin_error,
    }


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_request_host(value: str | None) -> str:
    if not value:
        return ""
    host = value.split(":", 1)[0].strip()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return host
    return re.sub(r"[^A-Za-z0-9_.:-]", "", host)[:96]


def _best_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def _socket_reachable(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.port:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=0.25):
            return True
    except OSError:
        return False
