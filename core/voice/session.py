"""One Smooth Voice room session, from dispatch to shutdown.

The order matters, and every step emits an event so the lifecycle probe can
tell "the entrypoint ran" from "the model built" from "the session started"
(tools/lifecycle_test.py correlates on room name; every event carries the pid):

    job_received -> memory -> connect -> model_built -> [avatar] -> session_start
    -> phrase gates -> session_config ("Active now") -> greeting ... session_end
"""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass, replace

from livekit.agents import AgentSession, JobContext, room_io

from core import voice_active, voice_events
from core.livekit_config import (
    LiveKitRealtimeConfig,
    get_livekit_realtime_config,
    speaker_identity_status,
)
from core.voice.activity import ensure_logging, log_session_activity
from core.voice.agent import ArgoRealtimeAgent
from core.voice.avatars import start_avatar
from core.voice.model import build_noise_filter, build_realtime_model
from core.voice.phrase_gates import wire_urgent_interrupts, wire_wake_sleep_gate

logger = logging.getLogger("ARGO.LiveKit")

_OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")


def redacted_error(exc: BaseException) -> str:
    """An exception message safe for the event stream: key-shaped text removed."""
    text = f"{type(exc).__name__}: {exc}"
    text = _OPENAI_KEY.sub("sk-***", text)
    text = _JWT.sub("***jwt***", text)
    return text[:400]


@dataclass(frozen=True)
class JobIds:
    """The identifiers every lifecycle event carries."""

    job_id: str = ""
    dispatch_id: str = ""
    room: str = ""

    @classmethod
    def of(cls, ctx: JobContext) -> "JobIds":
        job = getattr(ctx, "job", None)
        return cls(
            job_id=str(getattr(job, "id", "") or ""),
            dispatch_id=str(getattr(job, "dispatch_id", "") or ""),
            room=str(getattr(getattr(job, "room", None), "name", "") or ""),
        )


async def run_realtime_session(ctx: JobContext) -> None:
    """The LiveKit entrypoint: run ARGO in the room this job was dispatched to."""
    ensure_logging()
    ids = JobIds.of(ctx)
    # First, before anything else can fail.
    voice_events.emit("job_received", job_id=ids.job_id, dispatch_id=ids.dispatch_id,
                      room=ids.room)

    memory = _open_memory(ids.job_id)
    _register_shutdown(ctx, ids, memory)

    cfg = get_livekit_realtime_config()
    _log_live_config(cfg, ids.room)

    await ctx.connect()
    session, avatar, model = await _start_with_fallback(ctx, cfg, memory, ids)
    if avatar is not None:
        # The entrypoint returns long before the room closes, so a local
        # variable would not keep the avatar alive. The shutdown callback
        # holds the reference for the room lifetime and closes it cleanly.
        ctx.add_shutdown_callback(avatar.aclose)

    log_session_activity(session, room=ids.room, memory=memory)
    wire_urgent_interrupts(session, cfg)
    wire_wake_sleep_gate(session, cfg)
    _announce_active(cfg, model, ids)

    if cfg.greeting:
        session.generate_reply(instructions=cfg.greeting, allow_interruptions=True)


def _open_memory(session_id: str):
    """Durable voice memory for this session, or None if it cannot open."""
    try:
        from core.voice_memory import VoiceMemory

        memory = VoiceMemory(session_id=session_id)
    except Exception:
        logger.warning("[Memory] durable memory unavailable for this session", exc_info=True)
        return None
    logger.info("[Memory] durable voice memory ready: %s", memory.stats().get("backend"))
    return memory


def _register_shutdown(ctx: JobContext, ids: JobIds, memory) -> None:
    async def on_shutdown(reason: str = "") -> None:
        reason = str(reason or "")
        voice_events.emit("session_end", room=ids.room, job_id=ids.job_id, reason=reason)
        with contextlib.suppress(Exception):
            voice_active.mark_ended(reason)
        if memory is not None:
            try:
                memory.flush()
                logger.info("[Memory] %s", memory.stats())
            except Exception:
                logger.debug("[Memory] flush failed", exc_info=True)

    try:
        ctx.add_shutdown_callback(on_shutdown)
    except Exception:
        logger.debug("[Session] could not register shutdown callback", exc_info=True)


def _log_live_config(cfg: LiveKitRealtimeConfig, room: str) -> None:
    """The whole live configuration in one line, so "what was actually
    running" is answerable from the log instead of from config.json."""
    logger.info(
        "[LiveKit] starting ARGO realtime session room=%s model=%s voice=%s personality=%s",
        room or cfg.room, cfg.model, cfg.voice, cfg.personality,
    )
    logger.info(
        "[LiveKit] live config: model=%s voice=%s personality=%s turn=%s/%s "
        "noise_cancellation=%s input_reduction=%s min_interrupt=%.2fs/%dw "
        "false_interrupt=%.2fs deep_think=%s(%s)",
        cfg.model, cfg.voice, cfg.personality, cfg.turn_detection, cfg.turn_eagerness,
        cfg.noise_cancellation, cfg.input_noise_reduction,
        cfg.min_interruption_duration, cfg.min_interruption_words,
        cfg.false_interruption_timeout, cfg.deep_think_enabled, cfg.deep_think_model,
    )
    speaker = speaker_identity_status(cfg)
    logger.info("[SpeakerID] enabled=%s provider=%s ready=%s mode=%s",
                speaker["enabled"], speaker["provider"], speaker["ready"], speaker["mode"])


def _new_session(cfg: LiveKitRealtimeConfig) -> AgentSession:
    try:
        llm = build_realtime_model(cfg)
    except Exception as exc:
        voice_events.emit("model_build_failed", model=cfg.model, error=redacted_error(exc))
        raise
    voice_events.emit("model_built", model=cfg.model, voice=cfg.voice)
    return AgentSession(
        llm=llm,
        allow_interruptions=True,
        min_interruption_duration=cfg.min_interruption_duration,
        # Was 0: a cough, a chair creak or a stray "uh" cut ARGO off
        # mid-sentence. He has to actually start saying something.
        min_interruption_words=cfg.min_interruption_words,
        false_interruption_timeout=cfg.false_interruption_timeout,
        resume_false_interruption=False,
        user_away_timeout=None,
    )


async def _start_in_room(ctx: JobContext, cfg: LiveKitRealtimeConfig, memory):
    """Build a session on cfg.model, attach any avatar, and start it in the room."""
    session = _new_session(cfg)
    avatar = await start_avatar(session, ctx.room)
    try:
        await session.start(
            agent=ArgoRealtimeAgent(cfg, memory=memory),
            room=ctx.room,
            room_input_options=room_io.RoomInputOptions(
                audio_enabled=True,
                text_enabled=True,
                pre_connect_audio=True,
                noise_cancellation=build_noise_filter(cfg),
            ),
            room_output_options=room_io.RoomOutputOptions(
                audio_enabled=True,
                transcription_enabled=True,
            ),
        )
    except Exception:
        if avatar is not None:
            with contextlib.suppress(Exception):
                await avatar.aclose()
        with contextlib.suppress(Exception):
            await session.aclose()
        raise
    return session, avatar


async def _start_with_fallback(ctx: JobContext, cfg: LiveKitRealtimeConfig, memory,
                               ids: JobIds):
    """Start on the configured model, or once on the fallback model.

    A model name this account or plugin will not run must not mean a silent
    room. Tommy finds out from the log and the dashboard, not from talking to
    nobody. Returns (session, avatar, model actually running).
    """
    try:
        session, avatar = await _start_in_room(ctx, cfg, memory)
        return session, avatar, cfg.model
    except Exception:
        fallback = (cfg.fallback_model or "").strip()
        if not fallback or fallback == cfg.model:
            logger.exception("[LiveKit] session failed to start and there is no fallback model")
            raise
        logger.exception("[LiveKit] %s would not start; falling back to %s for this session",
                         cfg.model, fallback)
        voice_events.emit("model_fallback", model=cfg.model, fallback=fallback, room=ids.room)

    session, avatar = await _start_in_room(ctx, replace(cfg, model=fallback), memory)
    logger.warning("[LiveKit] running on fallback model %s", fallback)
    return session, avatar, fallback


def _announce_active(cfg: LiveKitRealtimeConfig, model: str, ids: JobIds) -> None:
    """The one line that answers "what is she running right now", and the
    record the dashboard's 'Active now' is filled from."""
    logger.info("[LiveKit] Active now: %s / %s / personality %s (instructions %s)",
                model, cfg.voice, cfg.personality, cfg.instruction_fingerprint)
    voice_active.write_active(
        model=model, voice=cfg.voice, personality=cfg.personality,
        instruction_fingerprint=cfg.instruction_fingerprint, room=ids.room, job_id=ids.job_id,
    )
    voice_events.emit("session_config", model=model, voice=cfg.voice,
                      personality=cfg.personality,
                      instruction_fingerprint=cfg.instruction_fingerprint, room=ids.room)
