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
import asyncio
from dataclasses import dataclass
from datetime import timedelta
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from core.config import get_config


DEFAULT_LOCAL_LIVEKIT_SECRET = "devsecretdevsecretdevsecretdevsecretdevsecret"
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_REALTIME_INSTRUCTIONS = (
    "You are ARGO, Tommy's realtime voice assistant. Speak like a capable, fun "
    "room assistant, not a research lab system. Prioritize fast back-and-forth "
    "conversation: answer in one short sentence by default, two only when useful. "
    "Do not narrate thinking, do not over-explain, and do not add filler before "
    "the answer. Be highly interruptible: when Tommy starts talking, stop cleanly "
    "and listen without apologizing or recapping the interruption. If a short "
    "phrase is ambiguous, ask one quick grounding question instead of guessing. "
    "Do not lecture about gates, policy, or architecture unless Tommy asks. You "
    "are connected to the realtime voice room; do not claim app, computer, or "
    "home actions unless a tool integration is explicitly connected for that action."
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
    speaker_id_enabled: bool
    speaker_id_provider: str


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
                0.08,
            ),
            0.08,
        ),
        false_interruption_timeout=_float(
            _env_or_config(
                cfg,
                "ARGO_REALTIME_FALSE_INTERRUPTION_TIMEOUT",
                "livekit.false_interruption_timeout",
                0.22,
            ),
            0.22,
        ),
        speaker_id_enabled=_bool(
            _env_or_config(cfg, "ARGO_SPEAKER_ID_ENABLED", "speaker_identity.enabled", False)
        ),
        speaker_id_provider=_env_or_config(
            cfg, "ARGO_SPEAKER_ID_PROVIDER", "speaker_identity.provider", "speechmatics"
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
    try:
        dispatch_id = ensure_livekit_agent_dispatch(room_name=room_name, config=cfg)
    except Exception:
        # Some local LiveKit builds expose worker dispatch through room config
        # but return 503 from the agent dispatch API. Do not block browser join.
        dispatch_id = ""

    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": room_name,
        "identity": participant_identity,
        "token": token,
        "agent_name": cfg.agent_name,
        "agent_dispatch_id": dispatch_id,
        "model": cfg.model,
        "voice": cfg.voice,
        "ttl_minutes": ttl_minutes,
    }


def ensure_livekit_agent_dispatch(
    *,
    room_name: str | None = None,
    config: LiveKitRealtimeConfig | None = None,
) -> str:
    """Ensure the local ARGO realtime worker is dispatched into the room."""

    cfg = config or get_livekit_realtime_config()
    if not cfg.agent_name:
        return ""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("LiveKit dispatch check skipped inside a running event loop")

    async def _ensure() -> str:
        from livekit import api

        lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
        try:
            room = _clean_name(room_name or cfg.room) or cfg.room
            existing = await lk.agent_dispatch.list_dispatch(room)
            for dispatch in existing:
                if dispatch.agent_name == cfg.agent_name:
                    return dispatch.id
            created = await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=room,
                    agent_name=cfg.agent_name,
                    metadata="argo-realtime",
                )
            )
            return created.id
        finally:
            await lk.aclose()

    return asyncio.run(_ensure())


def livekit_status(config: Any | None = None) -> dict[str, Any]:
    cfg = get_livekit_realtime_config(config)
    speaker_status = speaker_identity_status(cfg)
    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": cfg.room,
        "agent_name": cfg.agent_name,
        "model": cfg.model,
        "voice": cfg.voice,
        "server_reachable": _socket_reachable(cfg.url),
        "avatar": {
            "image": os.getenv("HEDRA_AVATAR_IMAGE", ""),
            "legacy_hedra_enabled": _bool(os.getenv("ARGO_HEDRA_AVATAR_ENABLED", False)),
            "legacy_hedra_available": bool(os.getenv("HEDRA_API_KEY")),
            "note": "Hedra realtime is legacy; ARGO keeps the Cortana portrait as the local visual fallback.",
        },
        "speaker_identity": speaker_status,
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


def speaker_identity_status(cfg: LiveKitRealtimeConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_livekit_realtime_config()
    provider = str(cfg.speaker_id_provider or "speechmatics").strip().lower()
    api_key_ready = bool(os.getenv("SPEECHMATICS_API_KEY", "").strip()) if provider == "speechmatics" else False
    plugin_ready = False
    plugin_error = ""
    if provider == "speechmatics":
        try:
            metadata.version("livekit-plugins-speechmatics")
        except Exception as exc:  # pragma: no cover - depends on optional package install
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
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
