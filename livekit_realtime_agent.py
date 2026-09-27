"""
ARGO realtime voice agent.

Run this next to the local LiveKit server for full-duplex voice conversation:

    .\\.venv\\Scripts\\python.exe livekit_realtime_agent.py dev

The browser joins a LiveKit room, publishes the mic, receives ARGO audio, and
OpenAI Realtime handles turn detection and interruption inside the audio stream.
When enabled, Hedra Live Avatar publishes a remote video track into the same
room so the browser can replace the local portrait fallback with animation.
"""

from __future__ import annotations

import logging
import os
import asyncio
import json
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from dataclasses import replace

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobExecutorType, cli, room_io, function_tool

from core.livekit_config import LiveKitRealtimeConfig, get_livekit_realtime_config
from core.livekit_config import speaker_identity_status
from core.voice.agent import ArgoRealtimeAgent
from core.voice.activity import log_session_activity
from core.voice.avatars import start_avatar
from core.voice.model import build_noise_filter, build_realtime_model
from core.voice.phrase_gates import wire_urgent_interrupts, wire_wake_sleep_gate


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("ARGO.LiveKit")




def _clear_stale_agents(cfg: LiveKitRealtimeConfig) -> None:
    """Remove agent participants left behind by a previous worker process.

    LiveKit rooms outlive the worker. A killed worker leaves its agent
    participant in the room, publishing a track nothing is behind; the next
    browser then joins a room that already has an agent, and this worker
    never receives the job. Tommy sees "connected" and gets silence.

    Only agent participants are removed, and only before this worker takes
    any job - a human in the room is left alone. Best effort: a failure here
    must never stop the worker starting.
    """
    import asyncio as _asyncio

    async def _clear() -> None:
        from livekit import api

        http_url = cfg.url.replace("ws://", "http://").replace("wss://", "https://")
        lk = api.LiveKitAPI(http_url, cfg.api_key, cfg.api_secret)
        try:
            rooms = await lk.room.list_rooms(api.ListRoomsRequest())
            for room in rooms.rooms:
                participants = await lk.room.list_participants(
                    api.ListParticipantsRequest(room=room.name)
                )
                for participant in participants.participants:
                    # kind 4 is AGENT in the LiveKit participant model.
                    if participant.kind != 4:
                        continue
                    logger.warning(
                        "[LiveKit] removing stale agent %s from room %s "
                        "(left by a previous worker)",
                        participant.identity, room.name,
                    )
                    await lk.room.remove_participant(
                        api.RoomParticipantIdentity(
                            room=room.name, identity=participant.identity
                        )
                    )
        finally:
            await lk.aclose()

    try:
        _asyncio.run(_clear())
    except Exception:
        logger.warning("[LiveKit] could not check for stale agents", exc_info=True)


def build_agent_server(cfg: LiveKitRealtimeConfig | None = None) -> AgentServer:
    cfg = cfg or get_livekit_realtime_config()
    _apply_livekit_env(cfg)
    _ensure_logging()
    _clear_stale_agents(cfg)

    server = AgentServer(
        job_executor_type=JobExecutorType.THREAD,
        ws_url=cfg.url,
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        load_threshold=float("inf"),
        # One warm executor: the first connect of a session was paying a
        # ~574 ms cold start before ARGO could hear anything.
        num_idle_processes=cfg.idle_processes,
        log_level="INFO",
    )

    server.rtc_session(_run_realtime_session, agent_name=cfg.agent_name)

    try:
        from core import voice_events as _ve

        _ve.emit("worker_built", agent_name=cfg.agent_name, url=cfg.url, model=cfg.model)
    except Exception:
        pass
    return server


def _ensure_logging() -> None:
    """Make ARGO's own log lines survive LiveKit's logging setup.

    cli.run_app configures logging after this module is imported. Loggers that
    already exist at that point can be disabled, which is why not one
    "[LiveKit] starting ARGO realtime session" line appeared in the worker log
    while sessions were demonstrably running - leaving the realtime path
    unobservable exactly when it needed diagnosing.
    """
    logger.disabled = False
    logger.propagate = True
    logger.setLevel(logging.INFO)


def _safe_error(exc: BaseException) -> str:
    """An exception message with anything key-shaped removed."""
    import re

    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)
    text = re.sub(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}", "***jwt***", text)
    return text[:400]


async def _run_realtime_session(ctx: JobContext) -> None:
    _ensure_logging()
    # Emitted before anything else can fail, so "the entrypoint ran" is
    # separable from "the model built" and "the session started". The
    # lifecycle test correlates on room name; every event carries the pid.
    from core import voice_events as _ve

    job = getattr(ctx, "job", None)
    _ve.emit(
        "job_received",
        job_id=str(getattr(job, "id", "") or ""),
        dispatch_id=str(getattr(job, "dispatch_id", "") or ""),
        room=str(getattr(getattr(job, "room", None), "name", "") or ""),
    )

    # Built before the shutdown closure so the closure can flush it.
    try:
        from core.voice_memory import VoiceMemory

        voice_memory = VoiceMemory(session_id=str(getattr(job, "id", "") or ""))
        logger.info("[Memory] durable voice memory ready: %s", voice_memory.stats().get("backend"))
    except Exception:
        voice_memory = None
        logger.warning("[Memory] durable memory unavailable for this session", exc_info=True)

    async def _on_shutdown(reason: str = "") -> None:
        _ve.emit("session_end", room=str(getattr(getattr(job, "room", None), "name", "") or ""),
                 job_id=str(getattr(job, "id", "") or ""), reason=str(reason or ""))
        try:
            from core.voice_active import mark_ended

            mark_ended(str(reason or ""))
        except Exception:
            pass
        try:
            if voice_memory is not None:
                voice_memory.flush()
                logger.info("[Memory] %s", voice_memory.stats())
        except Exception:
            logger.debug("[Memory] flush failed", exc_info=True)

    try:
        ctx.add_shutdown_callback(_on_shutdown)
    except Exception:
        logger.debug("[Session] could not register shutdown callback", exc_info=True)

    cfg = get_livekit_realtime_config()
    logger.info(
        "[LiveKit] starting ARGO realtime session room=%s model=%s voice=%s personality=%s",
        getattr(ctx.job.room, "name", cfg.room),
        cfg.model,
        cfg.voice,
        cfg.personality,
    )
    # The whole live configuration in one line, so "what was actually running"
    # is answerable from the log instead of from config.json.
    logger.info(
        "[LiveKit] live config: model=%s voice=%s personality=%s turn=%s/%s "
        "noise_cancellation=%s input_reduction=%s min_interrupt=%.2fs/%dw "
        "false_interrupt=%.2fs deep_think=%s(%s)",
        cfg.model, cfg.voice, cfg.personality, cfg.turn_detection, cfg.turn_eagerness,
        cfg.noise_cancellation, cfg.input_noise_reduction,
        cfg.min_interruption_duration, cfg.min_interruption_words,
        cfg.false_interruption_timeout,
        cfg.deep_think_enabled, cfg.deep_think_model,
    )
    speaker_status = speaker_identity_status(cfg)
    logger.info(
        "[SpeakerID] enabled=%s provider=%s ready=%s mode=%s",
        speaker_status["enabled"],
        speaker_status["provider"],
        speaker_status["ready"],
        speaker_status["mode"],
    )

    await ctx.connect()

    try:
        realtime_llm = build_realtime_model(cfg)
    except Exception as exc:
        _ve.emit("model_build_failed", model=cfg.model, error=_safe_error(exc))
        raise
    _ve.emit("model_built", model=cfg.model, voice=cfg.voice)

    session = AgentSession(
        llm=realtime_llm,
        allow_interruptions=True,
        min_interruption_duration=cfg.min_interruption_duration,
        # Was 0: a cough, a chair creak or a stray "uh" cut ARGO off
        # mid-sentence. He has to actually start saying something.
        min_interruption_words=cfg.min_interruption_words,
        false_interruption_timeout=cfg.false_interruption_timeout,
        resume_false_interruption=False,
        user_away_timeout=None,
    )

    avatar = await start_avatar(session, ctx.room)

    noise_filter = build_noise_filter(cfg)

    input_options = room_io.RoomInputOptions(
        audio_enabled=True,
        text_enabled=True,
        pre_connect_audio=True,
        noise_cancellation=noise_filter,
    )
    output_options = room_io.RoomOutputOptions(
        audio_enabled=True,
        transcription_enabled=True,
    )

    try:
        await session.start(
            agent=ArgoRealtimeAgent(cfg, memory=voice_memory),
            room=ctx.room,
            room_input_options=input_options,
            room_output_options=output_options,
        )
    except Exception:
        # A model name this account or this plugin will not run must not mean
        # a silent room. Fall back to the known-good model once, loudly, and
        # keep the conversation - Tommy finds out from the log and the
        # dashboard, not from talking to nobody.
        fallback = (cfg.fallback_model or "").strip()
        if not fallback or fallback == cfg.model:
            logger.exception("[LiveKit] session failed to start and there is no fallback model")
            raise
        logger.exception(
            "[LiveKit] %s would not start; falling back to %s for this session",
            cfg.model, fallback,
        )
        session.llm = build_realtime_model(replace(cfg, model=fallback))
        await session.start(
            agent=ArgoRealtimeAgent(cfg, memory=voice_memory),
            room=ctx.room,
            room_input_options=input_options,
            room_output_options=output_options,
        )
        logger.warning("[LiveKit] running on fallback model %s", fallback)

    room_name = str(getattr(getattr(ctx, "room", None), "name", "") or "")
    log_session_activity(session, room=room_name, memory=voice_memory)
    wire_urgent_interrupts(session, cfg)
    wire_wake_sleep_gate(session, cfg)

    # The one line that answers "what is she running right now", and the
    # record the dashboard's 'Active now' is filled from.
    from core.voice_active import write_active

    logger.info(
        "[LiveKit] Active now: %s / %s / personality %s (instructions %s)",
        cfg.model, cfg.voice, cfg.personality, cfg.instruction_fingerprint,
    )
    write_active(
        model=cfg.model, voice=cfg.voice, personality=cfg.personality,
        instruction_fingerprint=cfg.instruction_fingerprint, room=room_name,
        job_id=str(getattr(getattr(ctx, "job", None), "id", "") or ""),
    )
    _ve.emit("session_config", model=cfg.model, voice=cfg.voice, personality=cfg.personality,
             instruction_fingerprint=cfg.instruction_fingerprint, room=room_name)

    if cfg.greeting:
        session.generate_reply(instructions=cfg.greeting, allow_interruptions=True)

    if avatar is not None:
        # The entrypoint returns long before the room closes, so a local
        # variable does not keep the avatar alive. The shutdown callback
        # holds the reference for the room lifetime and closes it cleanly.
        ctx.add_shutdown_callback(avatar.aclose)


def _apply_livekit_env(cfg: LiveKitRealtimeConfig) -> None:
    os.environ.setdefault("LIVEKIT_URL", cfg.url)
    os.environ.setdefault("LIVEKIT_API_KEY", cfg.api_key)
    os.environ.setdefault("LIVEKIT_API_SECRET", cfg.api_secret)
    if cfg.agent_name:
        os.environ.setdefault("LIVEKIT_AGENT_NAME", cfg.agent_name)


if __name__ == "__main__":
    # Guarded here rather than in build_agent_server(): the framework's idle
    # job executors import this module, and they must not each take the lock
    # or re-run the environment check.
    #
    # The lock is the important half. A second worker registering under the
    # same agent_name fails silently - LiveKit just hands the job to whichever
    # it likes, so "can ARGO hear me" becomes a coin flip and both workers'
    # logs look identical either way.
    from core.runtime_guard import SingleInstance, verify_runtime

    verify_runtime("realtime-worker")

    def _watch_for_drain() -> None:
        """Graceful stop on request, without a console or a kill.

        The framework shuts down on SIGINT: _ExitCli -> server.drain() ->
        server.aclose(), which deregisters this worker from LiveKit. On
        Windows nothing outside the process can deliver that signal to a
        hidden, redirected process - but the process can raise it on itself.
        So: a file appears, this thread raises SIGINT, the main thread takes
        the normal shutdown path. The file is removed first so a stale one
        cannot stop the next start.
        """
        import signal
        import time as _time

        drain_file = ROOT / "runtime" / "locks" / "realtime-worker.drain"
        while True:
            _time.sleep(0.5)
            try:
                if drain_file.exists():
                    try:
                        drain_file.unlink()
                    except Exception:
                        pass
                    logger.warning("[Lifecycle] drain requested - shutting down gracefully")
                    from core import voice_events as _ve
                    _ve.emit("drain_requested")
                    signal.raise_signal(signal.SIGINT)
                    return
            except Exception:
                logger.debug("[Lifecycle] drain watcher error", exc_info=True)

    import threading as _threading

    _threading.Thread(target=_watch_for_drain, name="argo-drain-watcher", daemon=True).start()

    with SingleInstance("realtime-worker"):
        # Built here, not at import. build_agent_server() calls
        # _apply_livekit_env, which mutates os.environ, and opens a LiveKit
        # AgentServer - importing this module to inspect its tools or to test
        # them should do neither.
        cli.run_app(build_agent_server())
