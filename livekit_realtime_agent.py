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
from livekit.plugins import openai

try:
    from livekit.plugins import hedra as hedra_plugin
except Exception as exc:  # pragma: no cover - optional avatar dependency
    hedra_plugin = None
    HEDRA_PLUGIN_IMPORT_ERROR = exc
else:
    HEDRA_PLUGIN_IMPORT_ERROR = None

from core.livekit_config import LiveKitRealtimeConfig, get_livekit_realtime_config
from core.livekit_config import speaker_identity_status, HEDRA_REALTIME_RETIRED, HEDRA_REALTIME_NOTICE


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("ARGO.LiveKit")




class ArgoRealtimeAgent(Agent):
    """ARGO as the realtime model sees her.

    The instructions are assembled once, in core.livekit_config, and handed
    here whole. This constructor used to append its own paragraph of tool
    directions on top of them, which meant most of what the model read was
    about machinery - and it started answering like a command parser because
    that is what it had mostly been told about.
    """

    def __init__(self, cfg: LiveKitRealtimeConfig) -> None:
        self._cfg = cfg
        super().__init__(
            instructions=cfg.instructions,
            allow_interruptions=True,
        )

    @function_tool()
    async def repair_argo(self, text: str) -> str:
        """Run ARGO's diagnostic/repair conversation using the user's verbatim request.

        Pass explicit 'approve repair', 'cancel repair', 'repair status', or
        'prepare code repair' only when the user actually says those words.
        """
        def call():
            token = (ROOT / "runtime" / "repair_bridge.token").read_text(encoding="utf-8")
            port = int(os.getenv("ARGO_HTTP_PORT", "8000"))
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/repair-voice",
                data=json.dumps({"text": text}).encode(), headers={"Content-Type": "application/json", "X-Argo-Repair": token})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read().decode()
        try:
            return await asyncio.to_thread(call)
        except Exception as exc:
            return json.dumps({"status": "unavailable", "message": f"ARGO repair service could not be reached: {type(exc).__name__}. Open System in the dashboard."})

    @function_tool()
    async def think_deeply(self, question: str) -> str:
        """Work a hard question through properly with the deep reasoning model.

        Use for planning, research, debugging, comparing options, designing
        something, or any question where answering fast would answer worse.
        Pass the question in Tommy's own words. Not for ordinary conversation
        or quick facts.
        """
        from core import deep_think

        cfg = self._cfg
        if not cfg.deep_think_enabled:
            return json.dumps({"ok": False, "message": "Deep thinking is switched off."})

        history = []
        try:
            session = self.session
            for item in list(getattr(session.history, "items", []) or [])[-24:]:
                text = (getattr(item, "text_content", "") or "").strip()
                if text:
                    history.append({"role": getattr(item, "role", "user"), "text": text})
        except Exception:
            logger.debug("[DeepThink] could not read session history", exc_info=True)

        from core import voice_events as _ve
        _ve.emit("deep_think_start", question=question[:200], model=cfg.deep_think_model)
        result = await deep_think.think(
            question,
            history=history,
            model=cfg.deep_think_model,
            timeout=cfg.deep_think_timeout,
            persona=cfg.personality,
        )
        _ve.emit("deep_think_done", ok=result.ok, cancelled=result.cancelled,
                 elapsed_ms=result.elapsed_ms, error=result.error)
        if result.cancelled:
            # He started talking again. Saying anything here would talk over
            # the thought that cancelled this one.
            return json.dumps({"ok": False, "cancelled": True, "message": ""})
        if not result.ok:
            return json.dumps({"ok": False, "message": deep_think.spoken_failure(result)})
        return json.dumps({
            "ok": True,
            "answer": result.text,
            "model": result.model,
            "elapsed_ms": result.elapsed_ms,
        })

    # ---- Capability tools ------------------------------------------------
    # Bodies live in core.realtime_tools so they are unit-testable without a
    # LiveKit session. Each returns a dict; every call is threaded because the
    # underlying calls do blocking IO/WMI/COM.

    @staticmethod
    async def _run(fn, *args, **kwargs) -> str:
        from core import realtime_tools

        result = await asyncio.to_thread(fn, *args, **kwargs)
        return json.dumps(result, default=str)

    @function_tool()
    async def get_pc_specs(self) -> str:
        """This PC's hardware: motherboard, BIOS, CPU, memory and graphics card."""
        from core import realtime_tools as T
        return await self._run(T.pc_specs)

    @function_tool()
    async def get_drive_space(self) -> str:
        """Free and used space for every drive on this PC."""
        from core import realtime_tools as T
        return await self._run(T.drive_space)

    @function_tool()
    async def get_system_status(self) -> str:
        """Live machine health: memory use, temperatures, overall status."""
        from core import realtime_tools as T
        return await self._run(T.system_status)

    @function_tool()
    async def run_self_diagnostics(self) -> str:
        """Run ARGO's own diagnostics to find what is broken inside it."""
        from core import realtime_tools as T
        return await self._run(T.diagnostics)

    @function_tool()
    async def list_argo_files(self, subfolder: str = "") -> str:
        """List ARGO's own files and folders. Pass a subfolder like "core", or "" for the root."""
        from core import realtime_tools as T
        return await self._run(T.list_folder, subfolder)

    @function_tool()
    async def list_folder(self, path: str = "") -> str:
        """List any folder ARGO has permission to read.

        Absolute paths must be inside a folder Tommy granted in config.json.
        If it is refused, tell him it needs adding to filesystem.allowed_folders.
        """
        from core import realtime_tools as T
        return await self._run(T.list_folder, path)

    @function_tool()
    async def read_text_file(self, path: str) -> str:
        """Read a text file inside a folder ARGO has permission to read."""
        from core import realtime_tools as T
        return await self._run(T.read_text_file, path)

    @function_tool()
    async def find_files(self, query: str) -> str:
        """Search the folders ARGO can read for files matching a name or keyword."""
        from core import realtime_tools as T
        return await self._run(T.find_files, query)

    @function_tool()
    async def play_music(self, query: str = "", kind: str = "keyword") -> str:
        """Play music. kind is song, artist, genre, keyword or random."""
        from core import realtime_tools as T
        return await self._run(T.music_play, query, kind)

    @function_tool()
    async def play_music_from_era(self, era: str, genre: str = "", artist: str = "") -> str:
        """Play music from a period: "the 80s", "1975", "1990s", "1975 to 1980".

        Optionally narrow by genre or artist.
        """
        from core import realtime_tools as T
        return await self._run(T.music_play_era, era, genre, artist)

    @function_tool()
    async def list_launchable_apps(self) -> str:
        """What applications ARGO can open, including what is pinned to the taskbar.

        Use when asked what you can launch, or when an app name was not found.
        """
        from core import realtime_tools as T
        return await self._run(T.apps_launchable)

    @function_tool()
    async def stop_music(self) -> str:
        """Stop music playback."""
        from core import realtime_tools as T
        return await self._run(T.music_stop)

    @function_tool()
    async def next_track(self) -> str:
        """Skip to the next track."""
        from core import realtime_tools as T
        return await self._run(T.music_next)

    @function_tool()
    async def get_music_status(self) -> str:
        """What is playing right now, if anything."""
        from core import realtime_tools as T
        return await self._run(T.music_status)

    @function_tool()
    async def open_app(self, name: str) -> str:
        """Launch an application by name, e.g. "notepad", "chrome", "spotify"."""
        from core import realtime_tools as T
        return await self._run(T.app_open, name)

    @function_tool()
    async def close_app(self, name: str) -> str:
        """Close an application by name."""
        from core import realtime_tools as T
        return await self._run(T.app_close, name)

    @function_tool()
    async def focus_app(self, name: str) -> str:
        """Bring an application to the front."""
        from core import realtime_tools as T
        return await self._run(T.app_focus, name)

    @function_tool()
    async def list_running_apps(self) -> str:
        """What applications are running, and which one is in front."""
        from core import realtime_tools as T
        return await self._run(T.apps_running)

    @function_tool()
    async def set_volume(self, percent: int) -> str:
        """Set the system volume, 0 to 100."""
        from core import realtime_tools as T
        return await self._run(T.volume_set, percent)

    @function_tool()
    async def get_volume(self) -> str:
        """Current system volume and mute state."""
        from core import realtime_tools as T
        return await self._run(T.volume_status)

    # --- files: reading, searching, and now writing -----------------------

    @function_tool()
    async def search_drives(self, query: str, want: str = "any") -> str:
        """Find a file or FOLDER by name across every drive.

        want is any, file or folder. Most things Tommy names - "my vzbot
        build", "the davinci assets" - are folders, so search folders too.
        """
        from core import realtime_tools as T
        return await self._run(T.find_files, query, want)

    @function_tool()
    async def get_file_access(self) -> str:
        """Which drives can be read and written, and what is off limits."""
        from core import realtime_tools as T
        return await self._run(T.file_access_report)

    @function_tool()
    async def write_file(self, path: str, content: str, overwrite: bool = False) -> str:
        """Write a text file. Refuses to replace an existing file unless
        overwrite is true - say so before replacing something."""
        from core import realtime_tools as T
        return await self._run(T.write_text_file, path, content, overwrite)

    @function_tool()
    async def append_to_file(self, path: str, content: str) -> str:
        """Add text to the end of a file, creating it if needed."""
        from core import realtime_tools as T
        return await self._run(T.append_text_file, path, content)

    @function_tool()
    async def make_folder(self, path: str) -> str:
        """Create a folder."""
        from core import realtime_tools as T
        return await self._run(T.create_folder, path)

    @function_tool()
    async def move_file(self, source: str, destination: str, overwrite: bool = False) -> str:
        """Move or rename a file or folder."""
        from core import realtime_tools as T
        return await self._run(T.move_item, source, destination, overwrite)

    @function_tool()
    async def copy_file(self, source: str, destination: str, overwrite: bool = False) -> str:
        """Copy a file or folder."""
        from core import realtime_tools as T
        return await self._run(T.copy_item, source, destination, overwrite)

    @function_tool()
    async def remove_file(self, path: str) -> str:
        """Move a file or folder to quarantine. This does NOT delete it -
        say so: it goes to a quarantine folder Tommy empties himself."""
        from core import realtime_tools as T
        return await self._run(T.remove_item, path)

    @function_tool()
    async def check_music_library(self) -> str:
        """Whether the music index still matches what is on disk.

        Use this when music will not play, or before claiming the library
        has something. An index can outlive the files it points at.
        """
        from core import realtime_tools as T
        return await self._run(T.music_library_status)

    # --- movies and TV ---------------------------------------------------

    @function_tool()
    async def play_movie(self, title: str) -> str:
        """Put a movie on screen by name, full screen.

        Reports whether it STAYED playing, not just that a player launched.
        """
        from core import realtime_tools as T
        return await self._run(T.video_play, title, "movie")

    @function_tool()
    async def play_episode(self, title: str) -> str:
        """Play a TV episode by name or by the show it belongs to."""
        from core import realtime_tools as T
        return await self._run(T.video_play, title, "episode")

    @function_tool()
    async def find_something_to_watch(self, query: str, kind: str = "movie") -> str:
        """Search the movie and TV library. kind is movie, episode or series."""
        from core import realtime_tools as T
        return await self._run(T.video_search, query, kind)

    @function_tool()
    async def stop_video(self) -> str:
        """Close whatever movie or episode is on screen."""
        from core import realtime_tools as T
        return await self._run(T.video_stop)

    @function_tool()
    async def get_video_status(self) -> str:
        """What is on screen now, and how many movies and episodes exist."""
        from core import realtime_tools as T
        return await self._run(T.video_status)

    # --- writing ---------------------------------------------------------

    @function_tool()
    async def write_in_app(self, name: str, text: str) -> str:
        """Type text into an open app window. Only Notepad and Word accept text.

        Opens the app first if it is not running. For any other app this
        returns not_writable - say so rather than claiming it was written.
        """
        from core import realtime_tools as T
        return await self._run(T.app_write, name, text)

    @function_tool()
    async def list_writable_apps(self) -> str:
        """Which apps can be typed into, as opposed to merely opened."""
        from core import realtime_tools as T
        return await self._run(T.writable_apps)

    @function_tool()
    async def save_draft(self, kind: str, title: str, body: str, recipient: str = "") -> str:
        """Save a draft to disk. kind is email, document, blog or note.

        This only writes a file. It never sends anything.
        """
        from core import realtime_tools as T
        return await self._run(T.draft_write, kind, title, body, recipient)

    @function_tool()
    async def list_drafts(self, category: str = "", limit: int = 10) -> str:
        """List saved drafts, newest first."""
        from core import realtime_tools as T
        return await self._run(T.drafts_list, category, limit)

    @function_tool()
    async def read_draft(self, name: str) -> str:
        """Read back a saved draft by name."""
        from core import realtime_tools as T
        return await self._run(T.draft_read, name)

    @function_tool()
    async def check_email_sending(self) -> str:
        """Whether email sending is set up. ARGO cannot send email by voice."""
        from core import realtime_tools as T
        return await self._run(T.email_status)


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

    async def _on_shutdown(reason: str = "") -> None:
        _ve.emit("session_end", room=str(getattr(getattr(job, "room", None), "name", "") or ""),
                 job_id=str(getattr(job, "id", "") or ""), reason=str(reason or ""))
        try:
            from core.voice_active import mark_ended

            mark_ended(str(reason or ""))
        except Exception:
            pass

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
        realtime_llm = _build_realtime_model(cfg)
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

    hedra_avatar = await _maybe_start_hedra_avatar(session, ctx.room)

    noise_filter = _build_noise_filter(cfg)

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
            agent=ArgoRealtimeAgent(cfg),
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
        session.llm = _build_realtime_model(replace(cfg, model=fallback))
        await session.start(
            agent=ArgoRealtimeAgent(cfg),
            room=ctx.room,
            room_input_options=input_options,
            room_output_options=output_options,
        )
        logger.warning("[LiveKit] running on fallback model %s", fallback)

    _log_session_activity(session)
    _wire_urgent_interrupts(session, cfg)

    # The one line that answers "what is she running right now", and the
    # record the dashboard's 'Active now' is filled from.
    from core.voice_active import write_active

    room_name = str(getattr(getattr(ctx, "room", None), "name", "") or "")
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

    # Keep the optional avatar session strongly referenced for the room lifetime.
    _ = hedra_avatar


_PUNCTUATION = str.maketrans("", "", ".,!?;:\"'")


def matches_urgent_phrase(transcript: str, phrases) -> str | None:
    """Is this the start of someone saying "stop"?

    Matched at the START of the utterance only. "Stop" and "stop talking"
    fire; "don't stop the music" and "wait for the render to finish" do not,
    because in those the phrase is not what the sentence opens with. That
    distinction is the whole safety margin here - a fast path that fires on
    any occurrence of the word "wait" would cut ARGO off constantly.
    """
    text = (transcript or "").strip().lower().translate(_PUNCTUATION)
    if not text:
        return None
    for phrase in phrases:
        if text == phrase or text.startswith(phrase + " "):
            return phrase
    return None


def _wire_urgent_interrupts(session: AgentSession, cfg: LiveKitRealtimeConfig) -> None:
    """Let a clear "stop" cut in without waiting for the sustained threshold.

    min_interruption_words keeps a cough, a chair creak and the AC from
    barging in - but it also means a single decisive word would sit waiting
    for a second one. So generic speech keeps the stronger threshold and
    these get their own door: interim transcripts are watched, and the first
    one that opens with an urgent phrase interrupts at once.

    Only while ARGO is actually speaking, and only once per utterance.
    """
    phrases = tuple(cfg.urgent_interrupt_phrases or ())
    if not phrases:
        logger.info("[Interrupt] no urgent phrases configured")
        return

    state = {"fired_for": ""}

    def on_transcript(event):
        transcript = getattr(event, "transcript", "") or ""
        if not transcript.strip():
            return
        if getattr(event, "is_final", False):
            state["fired_for"] = ""       # utterance over; re-arm
            return
        if state["fired_for"] and transcript.startswith(state["fired_for"]):
            return                        # already interrupted on this one

        phrase = matches_urgent_phrase(transcript, phrases)
        if not phrase:
            return
        if str(getattr(session, "agent_state", "")) != "speaking":
            return                        # nothing to interrupt

        state["fired_for"] = transcript
        logger.info("[Interrupt] urgent phrase %r -> interrupting now (heard %r)",
                    phrase, transcript[:80])
        from core import voice_events as _ve
        _ve.emit("urgent_interrupt", phrase=phrase, transcript=transcript[:120])
        try:
            session.interrupt()
        except Exception:
            logger.warning("[Interrupt] session.interrupt() failed", exc_info=True)

    try:
        session.on("user_input_transcribed", on_transcript)
        logger.info("[Interrupt] urgent phrases armed: %s", ", ".join(phrases))
    except Exception:
        logger.warning("[Interrupt] could not arm urgent phrases", exc_info=True)


def _log_session_activity(session: AgentSession) -> None:
    """Say, in the log, whether ARGO heard anything and whether it answered.

    Without this a silent session and a deaf session look identical: one
    "starting ARGO realtime session" line and nothing after it. Every handler
    swallows its own errors - diagnostics must never be what breaks voice.
    """

    from core import voice_events

    voice_events.emit(
        "session_start",
        room=str(getattr(getattr(session, "_room", None), "name", "") or ""),
    )

    def _safe(name, handler):
        def wrapped(event):
            try:
                handler(event)
            except Exception:
                logger.debug("[Session] %s handler failed", name, exc_info=True)
        return wrapped

    def on_user_input(event):
        transcript = getattr(getattr(event, "transcript", None), "text", None)
        if transcript is None:
            transcript = getattr(event, "transcript", "")
        logger.info("[Session] heard: %r", transcript)
        voice_events.emit("heard", text=transcript,
                          final=bool(getattr(event, "is_final", False)))

    def on_user_state(event):
        old = getattr(event, "old_state", "?")
        new = getattr(event, "new_state", "?")
        logger.info("[Session] user %s -> %s", old, new)
        voice_events.emit("user_state", old=str(old), new=str(new))
        # The moment he starts talking again, any deep request in flight is
        # answering a question he has moved on from. Killing it here is the
        # difference between ARGO listening and ARGO talking over him with a
        # paragraph about something else.
        if str(new) == "speaking":
            from core import deep_think

            killed = deep_think.cancel_all(reason="user_started_speaking")
            if killed:
                voice_events.emit("deep_think_cancelled", count=killed)

    def on_agent_state(event):
        old = getattr(event, "old_state", "?")
        new = getattr(event, "new_state", "?")
        logger.info("[Session] agent %s -> %s", old, new)
        voice_events.emit("agent_state", old=str(old), new=str(new))

    def on_conversation_item(event):
        item = getattr(event, "item", None)
        logger.info("[Session] %s said: %r",
                    getattr(item, "role", "?"), (getattr(item, "text_content", "") or "")[:200])
        voice_events.emit("said", role=str(getattr(item, "role", "?")),
                          text=(getattr(item, "text_content", "") or "")[:600])

    def on_error(event):
        logger.error("[Session] error: %s", getattr(event, "error", event))
        voice_events.emit("error", detail=str(getattr(event, "error", event))[:400])

    for name, handler in (
        ("user_input_transcribed", on_user_input),
        ("user_state_changed", on_user_state),
        ("agent_state_changed", on_agent_state),
        ("conversation_item_added", on_conversation_item),
        ("error", on_error),
    ):
        try:
            session.on(name, _safe(name, handler))
        except Exception:
            logger.debug("[Session] could not subscribe to %s", name, exc_info=True)


def _build_noise_filter(cfg: LiveKitRealtimeConfig):
    """Background voice cancellation on the inbound mic track, or None.

    The classic path has no echo cancellation at all - the mic hears the
    speaker - and the realtime path had the plugin installed but unused. A
    missing or broken plugin must never take voice down with it, so every
    failure here degrades to raw audio and says so in the log.
    """
    if not cfg.noise_cancellation:
        logger.info("[Audio] noise cancellation disabled by config")
        return None
    try:
        from livekit.plugins import noise_cancellation

        filt = noise_cancellation.BVC()
    except Exception:
        logger.exception("[Audio] noise cancellation unavailable; continuing with raw mic audio")
        return None
    logger.info("[Audio] noise cancellation enabled (BVC)")
    return filt


def _build_turn_detection(cfg: LiveKitRealtimeConfig):
    """How the model decides Tommy has finished a thought.

    This was never configured, so the session ran on the Realtime API's plain
    silence timer: stop making noise for long enough and it answers, whether
    or not the sentence was finished. Semantic VAD reads the words as well as
    the silence, and "low" eagerness is the setting that waits longest.

    Returns a value for the `turn_detection` kwarg, or None meaning "do not
    pass the kwarg at all" - passing turn_detection=None would switch server
    turn detection OFF, which is not the same thing and would be much worse.
    """
    mode = (cfg.turn_detection or "").strip().lower()
    if mode in ("", "default", "auto_default"):
        return None
    eagerness = (cfg.turn_eagerness or "auto").strip().lower()
    if eagerness not in ("low", "medium", "high", "auto"):
        logger.warning("[Turn] unknown eagerness %r; using 'auto'", eagerness)
        eagerness = "auto"

    if mode == "semantic_vad":
        payload = {
            "type": "semantic_vad",
            "eagerness": eagerness,
            "create_response": True,
            "interrupt_response": True,
        }
    elif mode == "server_vad":
        payload = {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            # Long on purpose: a normal thinking pause is ~600ms and the old
            # default cut in under it.
            "silence_duration_ms": 900,
            "create_response": True,
            "interrupt_response": True,
        }
    else:
        logger.warning("[Turn] unknown turn_detection %r; leaving the API default", mode)
        return None

    # Prefer the SDK's typed object when this openai version exposes it, and
    # fall back to the plain dict the API accepts. Which one was used is
    # logged, because "turn detection is configured" and "turn detection
    # actually reached the session" are different claims.
    try:
        from openai.types import realtime as _realtime_types

        typed = _realtime_types.realtime_audio_input_turn_detection.SemanticVad(**payload) \
            if mode == "semantic_vad" else None
        if typed is not None:
            logger.info("[Turn] %s eagerness=%s (typed)", mode, eagerness)
            return typed
    except Exception:
        logger.debug("[Turn] typed turn-detection unavailable; sending a dict", exc_info=True)

    logger.info("[Turn] %s eagerness=%s (dict)", mode, eagerness)
    return payload


def _build_realtime_model(cfg: LiveKitRealtimeConfig) -> openai.realtime.RealtimeModel:
    from core.runtime_guard import ensure_openai_key

    ensure_openai_key()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for OpenAI Realtime voice, and it was "
            "not found in this process, in .env, or in the Windows User "
            "environment. ARGO will have accepted this job and then failed "
            "inside it, which from the room looks like no agent ever arrived."
        )

    kwargs = dict(
        model=cfg.model,
        voice=cfg.voice,
        modalities=["text", "audio"],
        api_key=api_key,
        temperature=cfg.temperature,
        speed=cfg.speed,
    )

    turn_detection = _build_turn_detection(cfg)
    if turn_detection is not None:
        kwargs["turn_detection"] = turn_detection

    # Pin the input transcription language. Without it, two of thirty turns in
    # the first real mic run came back as Chinese characters (the AC was on)
    # and ARGO answered one. Typed object first, dict fallback, logged either
    # way - same pattern as turn detection.
    try:
        from openai.types import realtime as _rt

        transcription = _rt.AudioTranscription(model="gpt-4o-mini-transcribe", language="en")
        logger.info("[Audio] input transcription: gpt-4o-mini-transcribe language=en (typed)")
    except Exception:
        transcription = {"model": "gpt-4o-mini-transcribe", "language": "en"}
        logger.info("[Audio] input transcription: gpt-4o-mini-transcribe language=en (dict)")
    kwargs["input_audio_transcription"] = transcription

    reduction = (cfg.input_noise_reduction or "").strip().lower()
    if reduction in ("near_field", "far_field"):
        kwargs["input_audio_noise_reduction"] = reduction
        logger.info("[Audio] server-side input noise reduction: %s", reduction)
    elif reduction not in ("", "off", "none"):
        logger.warning("[Audio] unknown input_noise_reduction %r; leaving it off", reduction)

    logger.info(
        "[LiveKit] realtime model=%s voice=%s temp=%.2f speed=%.2f turn_detection=%s",
        cfg.model, cfg.voice, cfg.temperature, cfg.speed,
        (turn_detection if isinstance(turn_detection, dict) else type(turn_detection).__name__)
        if turn_detection is not None else "api-default",
    )

    try:
        return openai.realtime.RealtimeModel(**kwargs)
    except TypeError:
        # An older plugin that does not know one of these kwargs must not take
        # voice down - drop the optional ones and say so, loudly.
        logger.exception(
            "[LiveKit] realtime model rejected the tuning kwargs; retrying without "
            "turn_detection/noise-reduction. Turn-taking will be the API default."
        )
        for optional in ("turn_detection", "input_audio_noise_reduction", "input_audio_transcription"):
            kwargs.pop(optional, None)
        return openai.realtime.RealtimeModel(**kwargs)


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
    """Start a Hedra LiveKit avatar when explicitly enabled."""

    # Do not retry the retired endpoint or redirect working voice to a dead avatar.
    if HEDRA_REALTIME_RETIRED:
        logger.info("[Avatar] %s", HEDRA_REALTIME_NOTICE)
        return None

    if not _env_enabled("ARGO_HEDRA_AVATAR_ENABLED", False):
        logger.info("[Hedra] avatar disabled; using local portrait fallback")
        return None

    hedra_api_key = (os.getenv("HEDRA_API_KEY") or "").strip()
    if not hedra_api_key:
        logger.warning("[Hedra] ARGO_HEDRA_AVATAR_ENABLED is true but HEDRA_API_KEY is missing")
        return None

    avatar_id = (os.getenv("HEDRA_AVATAR_ID") or "").strip()
    avatar_image_path = (os.getenv("HEDRA_AVATAR_IMAGE") or "").strip()
    if not avatar_id and not avatar_image_path:
        logger.warning("[Hedra] Set HEDRA_AVATAR_ID or HEDRA_AVATAR_IMAGE to start a Hedra avatar")
        return None

    if hedra_plugin is None:
        logger.warning(
            "[Hedra] livekit.plugins.hedra is not available; the core realtime voice path will continue: %s",
            HEDRA_PLUGIN_IMPORT_ERROR,
        )
        return None

    kwargs = {"api_key": hedra_api_key}
    api_url = (os.getenv("HEDRA_API_URL") or "").strip()
    if api_url:
        kwargs["api_url"] = api_url

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

    logger.info(
        "[Hedra] starting live avatar video source=%s participant=%s api_url=%s",
        "asset_id" if avatar_id else "local_image",
        participant_identity or "hedra-avatar-agent",
        api_url or "default",
    )
    try:
        avatar = hedra_plugin.AvatarSession(**kwargs)
        await avatar.start(session, room=room)
        logger.info("[Hedra] live avatar session started; waiting for remote video track")
        return avatar
    except Exception:
        logger.exception("[Hedra] avatar session failed; continuing without avatar video")
        return None


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
