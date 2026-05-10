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


server = build_agent_server()


if __name__ == "__main__":
    cli.run_app(server)
