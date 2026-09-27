"""Optional avatar video for a voice session.

Avatar rendering is optional; audio is not. Every path here degrades forward,
never to silence:

    Simli  ->  local viseme renderer (in the browser)  ->  static portrait

Hedra's realtime avatar service is retired (``HEDRA_REALTIME_RETIRED`` in
core.livekit_config) and is never contacted. See AGENTS.md > External LiveKit
Participants for why Simli needs a publicly reachable LiveKit URL.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import os
from urllib.parse import urlsplit

from livekit.agents import AgentSession

from core.livekit_config import HEDRA_REALTIME_NOTICE

try:
    from livekit.plugins import simli as simli_plugin
except Exception as exc:  # pragma: no cover - optional dependency
    simli_plugin = None
    SIMLI_PLUGIN_IMPORT_ERROR: Exception | None = exc
else:
    SIMLI_PLUGIN_IMPORT_ERROR = None

logger = logging.getLogger("ARGO.LiveKit")

DEFAULT_START_TIMEOUT_S = 15.0
_LOOPBACK_HOSTS = {"", "localhost", "127.0.0.1", "0.0.0.0", "::1"}


def env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def avatar_start_timeout() -> float:
    """Seconds to wait for an avatar participant before giving ARGO her voice back."""
    try:
        return max(1.0, float(os.getenv("ARGO_AVATAR_START_TIMEOUT", DEFAULT_START_TIMEOUT_S)))
    except ValueError:
        return DEFAULT_START_TIMEOUT_S


def url_reachable_from_cloud(url: str) -> bool:
    """Can a cloud-hosted avatar provider dial this LiveKit URL?

    Simli is handed ARGO's LIVEKIT_URL plus a room token and joins from its own
    servers. A loopback or RFC1918 address resolves to *their* machine, so the
    avatar can never arrive. ``ARGO_AVATAR_ALLOW_LOCAL_URL=1`` overrides this
    for tunnels, port-forwards and other odd topologies.
    """
    if env_enabled("ARGO_AVATAR_ALLOW_LOCAL_URL"):
        return True
    if not url:
        return False
    host = (urlsplit(url).hostname or "").strip("[]").lower()
    if host in _LOOPBACK_HOSTS:
        return False
    try:
        return not ipaddress.ip_address(host).is_private
    except ValueError:
        return True  # a DNS name; assume it resolves publicly


async def start_avatar(session: AgentSession, room):
    """Start whichever avatar is enabled, or return None for the local portrait.

    The caller must keep the returned object referenced for the room lifetime.
    """
    if env_enabled("ARGO_HEDRA_AVATAR_ENABLED"):
        logger.info("[Avatar] %s", HEDRA_REALTIME_NOTICE)
    return await start_simli_avatar(session, room)


def _simli_settings() -> tuple[str, str] | None:
    """(api_key, face_id) when Simli is enabled and fully configured."""
    if not env_enabled("ARGO_SIMLI_AVATAR_ENABLED"):
        logger.info("[Simli] avatar disabled; using local portrait fallback")
        return None

    api_key = (os.getenv("SIMLI_API_KEY") or "").strip()
    if not api_key:
        logger.warning("[Simli] ARGO_SIMLI_AVATAR_ENABLED is true but SIMLI_API_KEY is missing")
        return None

    face_id = (os.getenv("SIMLI_FACE_ID") or "").strip()
    if not face_id:
        logger.warning("[Simli] SIMLI_FACE_ID is missing; create/upload a face at "
                       "https://app.simli.com/faces and set SIMLI_FACE_ID")
        return None

    if simli_plugin is None:
        logger.warning("[Simli] livekit.plugins.simli is not available; voice continues "
                       "without avatar video: %s", SIMLI_PLUGIN_IMPORT_ERROR)
        return None

    livekit_url = (os.getenv("LIVEKIT_URL") or "").strip()
    if not url_reachable_from_cloud(livekit_url):
        logger.error(
            "[Simli] refusing to start: LIVEKIT_URL=%s is not reachable from the public "
            "internet. Simli joins the room from its own servers, so this address points "
            "at Simli's machine and the avatar can never arrive. Use LiveKit Cloud, or a "
            "publicly reachable self-hosted deployment (signalling AND WebRTC media). "
            "Override with ARGO_AVATAR_ALLOW_LOCAL_URL=1. "
            "See AGENTS.md > External LiveKit Participants.",
            livekit_url or "<unset>",
        )
        return None
    return api_key, face_id


async def start_simli_avatar(session: AgentSession, room):
    """Start a Simli avatar, restoring direct room audio on any failure.

    ``AvatarSession.start()`` reroutes ``session.output.audio`` to the avatar
    participant, so ARGO is MUTE from that moment until the avatar joins. The
    wait is bounded and the previous output is restored on every failure path.
    """
    settings = _simli_settings()
    if settings is None:
        return None
    api_key, face_id = settings

    logger.info("[Simli] starting live avatar video face_id=%s", face_id)
    direct_audio = session.output.audio
    try:
        avatar = simli_plugin.AvatarSession(
            simli_config=simli_plugin.SimliConfig(api_key=api_key, face_id=face_id),
        )
        await avatar.start(session, room=room)
    except Exception:
        session.output.audio = direct_audio
        logger.exception("[Simli] avatar session failed; continuing without avatar video")
        return None

    if session.output.audio is direct_audio:
        # start() logs its own API errors and returns without rerouting audio.
        logger.warning("[Simli] avatar did not attach; continuing without avatar video")
        return None

    timeout = avatar_start_timeout()
    try:
        from livekit.agents import utils as lk_utils

        await asyncio.wait_for(
            lk_utils.wait_for_participant(room=room, identity=avatar.avatar_identity),
            timeout=timeout,
        )
    except Exception:
        session.output.audio = direct_audio
        logger.error("[Simli] avatar participant did not join within %ss - restored direct "
                     "room audio so ARGO keeps her voice; avatar video is off for this "
                     "session.", timeout)
        with contextlib.suppress(Exception):
            await avatar.aclose()
        return None

    logger.info("[Simli] avatar participant joined; live avatar video active")
    return avatar
