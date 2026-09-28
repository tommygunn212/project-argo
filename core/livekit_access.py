"""LiveKit room tokens and explicit worker dispatch."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import timedelta
from typing import Any

logger = logging.getLogger("ARGO.LiveKitAccess")


def _clean_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "-", str(value or "").strip())[:96]


def _clean_identity(value: str) -> str:
    return _clean_name(value) or f"tommy-{uuid.uuid4().hex[:8]}"


def build_livekit_token_response(
    *,
    identity: str | None = None,
    room: str | None = None,
    name: str | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    from livekit import api
    from core.livekit_config import get_livekit_realtime_config

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
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))
    )
    if cfg.agent_name:
        token_builder = token_builder.with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=cfg.agent_name)])
        )

    dispatch_id = ""
    dispatch_error = ""
    try:
        dispatch_id = ensure_livekit_agent_dispatch(room_name=room_name, config=cfg)
    except Exception as exc:
        dispatch_error = f"{type(exc).__name__}: {exc}"
        logger.error(
            "[LiveKit] AGENT DISPATCH FAILED room=%s agent=%s - the browser will "
            "join and publish audio but NOTHING will be listening: %s",
            room_name, cfg.agent_name, dispatch_error,
        )
    else:
        logger.info(
            "[LiveKit] agent dispatched room=%s agent=%s dispatch_id=%s",
            room_name, cfg.agent_name, dispatch_id or "(none)",
        )
    if cfg.agent_name and not dispatch_id and not dispatch_error:
        dispatch_error = "no dispatch id returned"
        logger.error(
            "[LiveKit] no dispatch id for room=%s agent=%s - no agent will hear this session",
            room_name, cfg.agent_name,
        )

    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": room_name,
        "identity": participant_identity,
        "token": token_builder.to_jwt(),
        "agent_name": cfg.agent_name,
        "agent_dispatch_id": dispatch_id,
        "agent_dispatch_error": dispatch_error,
        "agent_listening": bool(dispatch_id) or not cfg.agent_name,
        "model": cfg.model,
        "voice": cfg.voice,
        "ttl_minutes": ttl_minutes,
    }


def ensure_livekit_agent_dispatch(*, room_name: str | None = None, config: Any | None = None) -> str:
    """Clear stale ARGO dispatches and attach the current worker to the room."""
    from core.livekit_config import get_livekit_realtime_config

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
            resolved_room = _clean_name(room_name or cfg.room) or cfg.room
            try:
                existing = await lk.agent_dispatch.list_dispatch(resolved_room)
            except Exception:
                logger.warning(
                    "[LiveKit] could not list dispatches for room=%s", resolved_room, exc_info=True
                )
                existing = []
            for dispatch in existing:
                if dispatch.agent_name != cfg.agent_name:
                    continue
                try:
                    await lk.agent_dispatch.delete_dispatch(dispatch.id, resolved_room)
                    logger.info(
                        "[LiveKit] cleared stale dispatch id=%s agent=%s room=%s",
                        dispatch.id, cfg.agent_name, resolved_room,
                    )
                except Exception:
                    logger.warning(
                        "[LiveKit] could not clear stale dispatch id=%s room=%s",
                        dispatch.id, resolved_room, exc_info=True,
                    )
            created = await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=resolved_room,
                    agent_name=cfg.agent_name,
                    metadata="argo-realtime",
                )
            )
            logger.info(
                "[LiveKit] created dispatch id=%s agent=%s room=%s",
                created.id, cfg.agent_name, resolved_room,
            )
            return created.id
        finally:
            await lk.aclose()

    return asyncio.run(_ensure())
