"""
ARGO realtime voice agent.

Run this next to the local LiveKit server for full-duplex voice conversation:

    .\\.venv\\Scripts\\python.exe livekit_realtime_agent.py dev

The browser joins a LiveKit room, publishes the mic, receives ARGO audio, and
OpenAI Realtime handles turn detection and interruption inside the audio stream.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobExecutorType, cli, room_io
from livekit.plugins import openai

from core.livekit_config import LiveKitRealtimeConfig, get_livekit_realtime_config


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("ARGO.LiveKit")


class ArgoRealtimeAgent(Agent):
    def __init__(self, cfg: LiveKitRealtimeConfig) -> None:
        super().__init__(
            instructions=cfg.instructions,
            allow_interruptions=True,
        )


def build_agent_server(cfg: LiveKitRealtimeConfig | None = None) -> AgentServer:
    cfg = cfg or get_livekit_realtime_config()
    _apply_livekit_env(cfg)

    server = AgentServer(
        job_executor_type=JobExecutorType.THREAD,
        ws_url=cfg.url,
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        load_threshold=float("inf"),
        num_idle_processes=0,
        log_level="INFO",
    )

    server.rtc_session(_run_realtime_session, agent_name=cfg.agent_name)
    return server


async def _run_realtime_session(ctx: JobContext) -> None:
    cfg = get_livekit_realtime_config()
    logger.info(
        "[LiveKit] starting ARGO realtime session room=%s model=%s voice=%s",
        getattr(ctx.job.room, "name", cfg.room),
        cfg.model,
        cfg.voice,
    )

    await ctx.connect()

    session = AgentSession(
        llm=_build_realtime_model(cfg),
        allow_interruptions=True,
        min_interruption_duration=cfg.min_interruption_duration,
        min_interruption_words=0,
        false_interruption_timeout=cfg.false_interruption_timeout,
        resume_false_interruption=False,
        user_away_timeout=None,
    )

    hedra_avatar = await _maybe_start_hedra_avatar(session, ctx.room)

    await session.start(
        agent=ArgoRealtimeAgent(cfg),
        room=ctx.room,
        room_input_options=room_io.RoomInputOptions(
            audio_enabled=True,
            text_enabled=True,
            pre_connect_audio=True,
        ),
        room_output_options=room_io.RoomOutputOptions(
            audio_enabled=True,
            transcription_enabled=True,
        ),
    )

    if cfg.greeting:
        session.generate_reply(instructions=cfg.greeting, allow_interruptions=True)

    # Keep the optional avatar session strongly referenced for the room lifetime.
    _ = hedra_avatar


def _build_realtime_model(cfg: LiveKitRealtimeConfig) -> openai.realtime.RealtimeModel:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI Realtime voice.")

    return openai.realtime.RealtimeModel(
        model=cfg.model,
        voice=cfg.voice,
        modalities=["text", "audio"],
        api_key=api_key,
        temperature=cfg.temperature,
        speed=cfg.speed,
    )


def _apply_livekit_env(cfg: LiveKitRealtimeConfig) -> None:
    os.environ.setdefault("LIVEKIT_URL", cfg.url)
    os.environ.setdefault("LIVEKIT_API_KEY", cfg.api_key)
    os.environ.setdefault("LIVEKIT_API_SECRET", cfg.api_secret)
    if cfg.agent_name:
        os.environ.setdefault("LIVEKIT_AGENT_NAME", cfg.agent_name)


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


async def _maybe_start_hedra_avatar(session: AgentSession, room):
    """Start a legacy Hedra LiveKit avatar when explicitly enabled."""

    if not _env_enabled("ARGO_HEDRA_AVATAR_ENABLED", False):
        return None

    if not os.getenv("HEDRA_API_KEY"):
        logger.warning("[Hedra] ARGO_HEDRA_AVATAR_ENABLED is true but HEDRA_API_KEY is missing")
        return None

    avatar_id = (os.getenv("HEDRA_AVATAR_ID") or "").strip()
    avatar_image_path = (os.getenv("HEDRA_AVATAR_IMAGE") or "").strip()
    if not avatar_id and not avatar_image_path:
        logger.warning("[Hedra] Set HEDRA_AVATAR_ID or HEDRA_AVATAR_IMAGE to start a Hedra avatar")
        return None

    try:
        from livekit.plugins import hedra
    except ImportError:
        logger.warning(
            "[Hedra] livekit.plugins.hedra is not installed; the core realtime voice path will continue"
        )
        return None

    kwargs = {}
    participant_identity = (os.getenv("HEDRA_AVATAR_PARTICIPANT_IDENTITY") or "").strip()
    if participant_identity:
        kwargs["avatar_participant_identity"] = participant_identity

    participant_name = (os.getenv("HEDRA_AVATAR_PARTICIPANT_NAME") or "").strip()
    if participant_name:
        kwargs["avatar_participant_name"] = participant_name

    if avatar_id:
        kwargs["avatar_id"] = avatar_id
    else:
        from PIL import Image

        image_path = Path(avatar_image_path).expanduser()
        if not image_path.is_absolute():
            image_path = ROOT / image_path
        if not image_path.exists():
            logger.warning("[Hedra] avatar image not found: %s", image_path)
            return None
        with Image.open(image_path) as img:
            kwargs["avatar_image"] = img.convert("RGB").copy()

    logger.warning("[Hedra] attempting legacy Hedra avatar path; if it fails, voice continues")
    try:
        avatar = hedra.AvatarSession(**kwargs)
        await avatar.start(session, room=room)
        logger.info("[Hedra] avatar session started")
        return avatar
    except Exception:
        logger.exception("[Hedra] avatar session failed; continuing without avatar video")
        return None


server = build_agent_server()


if __name__ == "__main__":
    cli.run_app(server)
