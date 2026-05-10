"""
LiveKit/OpenAI Realtime configuration helpers for ARGO.

The classic local pipeline is still useful for commands, diagnostics, and
fallback speech. This module owns only the realtime room path used for fast
voice conversation and clean barge-in behavior.
"""

from __future__ import annotations

import os
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from core.config import get_config


DEFAULT_LOCAL_LIVEKIT_SECRET = "devsecretdevsecretdevsecretdevsecretdevsecret"

DEFAULT_REALTIME_INSTRUCTIONS = (
    "You are ARGO, Tommy's realtime voice assistant. Speak like a capable, fun "
    "room assistant, not a research lab system. Keep most replies to one or two "
    "short sentences unless Tommy asks for depth. Be interruptible: when Tommy "
    "starts talking, stop cleanly and listen. Do not lecture about gates, policy, "
    "or architecture unless Tommy asks. You are connected to the realtime voice "
    "room; do not claim app, computer, or home actions unless a tool integration "
    "is explicitly connected for that action."
)


@dataclass(frozen=True)
class LiveKitRealtimeConfig:
    enabled: bool
    url: str
    api_key: str
    api_secret: str
    room: str
    agent_name: str
    model: str
    voice: str
    instructions: str
    greeting: str
    temperature: float
    speed: float
    token_ttl_minutes: int
    min_interruption_duration: float
    false_interruption_timeout: float


def get_livekit_realtime_config(config: Any | None = None) -> LiveKitRealtimeConfig:
    cfg = config or get_config()

    api_key = _env_or_config(cfg, "LIVEKIT_API_KEY", "livekit.api_key", "devkey")
    api_secret = _env_or_config(cfg, "LIVEKIT_API_SECRET", "livekit.api_secret", "")
    if not api_secret and api_key == "devkey":
        api_secret = DEFAULT_LOCAL_LIVEKIT_SECRET

    return LiveKitRealtimeConfig(
        enabled=_bool(_env_or_config(cfg, "ARGO_LIVEKIT_ENABLED", "livekit.enabled", True)),
        url=_env_or_config(cfg, "LIVEKIT_URL", "livekit.url", "ws://127.0.0.1:7880"),
        api_key=api_key,
        api_secret=api_secret,
        room=_clean_name(_env_or_config(cfg, "ARGO_LIVEKIT_ROOM", "livekit.room", "argo-live")),
        agent_name=_clean_name(_env_or_config(cfg, "LIVEKIT_AGENT_NAME", "livekit.agent_name", "")),
        model=_env_or_config(cfg, "ARGO_REALTIME_MODEL", "livekit.model", "gpt-realtime"),
        voice=_env_or_config(cfg, "ARGO_REALTIME_VOICE", "livekit.voice", "marin"),
        instructions=_env_or_config(
            cfg, "ARGO_REALTIME_INSTRUCTIONS", "livekit.instructions", DEFAULT_REALTIME_INSTRUCTIONS
        ),
        greeting=_env_or_config(cfg, "ARGO_REALTIME_GREETING", "livekit.greeting", ""),
        temperature=_float(_env_or_config(cfg, "ARGO_REALTIME_TEMPERATURE", "livekit.temperature", 0.6), 0.6),
        speed=_float(_env_or_config(cfg, "ARGO_REALTIME_SPEED", "livekit.speed", 1.0), 1.0),
        token_ttl_minutes=_int(
            _env_or_config(cfg, "ARGO_LIVEKIT_TOKEN_TTL_MINUTES", "livekit.token_ttl_minutes", 60),
            60,
        ),
        min_interruption_duration=_float(
            _env_or_config(
                cfg,
                "ARGO_REALTIME_MIN_INTERRUPTION_DURATION",
                "livekit.min_interruption_duration",
                0.12,
            ),
            0.12,
        ),
        false_interruption_timeout=_float(
            _env_or_config(
                cfg,
                "ARGO_REALTIME_FALSE_INTERRUPTION_TIMEOUT",
                "livekit.false_interruption_timeout",
                0.35,
            ),
            0.35,
        ),
    )


def build_livekit_token_response(
    *,
    identity: str | None = None,
    room: str | None = None,
    name: str | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    from livekit import api

    cfg = get_livekit_realtime_config(config)
    if not cfg.enabled:
        raise RuntimeError("LiveKit realtime voice is disabled in config.")
    if not cfg.api_key or not cfg.api_secret:
        raise RuntimeError("LiveKit API key/secret are required for token minting.")

    room_name = _clean_name(room or cfg.room) or cfg.room
    participant_identity = _clean_identity(identity or f"tommy-{uuid.uuid4().hex[:8]}")
    participant_name = name or participant_identity
    ttl_minutes = max(1, cfg.token_ttl_minutes)

    token_builder = (
        api.AccessToken(cfg.api_key, cfg.api_secret)
        .with_identity(participant_identity)
        .with_name(participant_name)
        .with_ttl(timedelta(minutes=ttl_minutes))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )
    if cfg.agent_name:
        token_builder = token_builder.with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=cfg.agent_name)]
            )
        )

    token = token_builder.to_jwt()

    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": room_name,
        "identity": participant_identity,
        "token": token,
        "agent_name": cfg.agent_name,
        "model": cfg.model,
        "voice": cfg.voice,
        "ttl_minutes": ttl_minutes,
    }


def livekit_status(config: Any | None = None) -> dict[str, Any]:
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
    }


def _env_or_config(config: Any, env_key: str, config_key: str, default: Any) -> Any:
    env_value = os.getenv(env_key)
    if env_value not in (None, ""):
        return env_value
    value = config.get(config_key, default)
    return default if value in (None, "") else value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "-", str(value or "").strip())[:96]


def _clean_identity(value: str) -> str:
    cleaned = _clean_name(value)
    return cleaned or f"tommy-{uuid.uuid4().hex[:8]}"


def _socket_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
