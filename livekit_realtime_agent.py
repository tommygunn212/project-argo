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
from core.voice.activity import log_session_activity
from core.voice.avatars import start_avatar
from core.voice.model import build_noise_filter, build_realtime_model
from core.voice.phrase_gates import wire_urgent_interrupts, wire_wake_sleep_gate


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

    def __init__(self, cfg: LiveKitRealtimeConfig, memory=None) -> None:
        self._cfg = cfg
        self._memory = memory
        instructions = cfg.instructions
        # Durable facts ride along with the personality. Past conversations do
        # not - they are reached with the recall tool, so history cannot drown
        # the directives that make her sound like herself.
        if memory is not None:
            try:
                known = memory.opening_context()
                if known:
                    instructions = f"{instructions}\n\n{known}"
                    logger.info("[Memory] session opened with %d remembered fact line(s)",
                                known.count("\n- "))
            except Exception:
                logger.debug("[Memory] could not load opening context", exc_info=True)
        super().__init__(
            instructions=instructions,
            allow_interruptions=True,
        )

    @function_tool()
    async def recall(self, about: str) -> str:
        """Search your own past conversations with Tommy.

        Call this BEFORE telling him you don't know, don't have, or don't
        remember something about him - not only when he says "remember
        when" or "what did we decide." The trigger is not a phrase, it's a
        gap: any question about a fact, preference, or detail of his life
        that isn't already sitting in your instructions ("what's my
        favorite color", "what did I say about the dog") means check here
        first, because it may well be sitting in a past turn even though
        it never became a standing fact. Only skip this for general
        knowledge that has nothing to do with him or a past conversation.
        Pass what to look for in his words.
        """
        if self._memory is None:
            return "I don't have memory wired up in this session."
        logger.info("[Recall] tool invoked: about=%r", about)
        try:
            result = await asyncio.to_thread(self._memory.recall, about)
            logger.info("[Recall] tool returned %d char(s): %r", len(result), result[:200])
            return result
        except Exception as exc:
            logger.warning("[Recall] tool failed", exc_info=True)
            return f"I couldn't search my memory: {type(exc).__name__}"

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

    @function_tool()
    async def set_pc_profile(self, mode: str) -> str:
        """Switch the PC between "gaming" and "editing" profiles - power
        plan, display refresh rate, and any configured background apps to
        close. mode must be "gaming" or "editing"."""
        from core import realtime_tools as T
        return await self._run(T.pc_profile_set, mode)

    @function_tool()
    async def get_pc_profile_status(self) -> str:
        """Current power plan, display refresh rate, and which PC profile -
        gaming or editing - was applied last."""
        from core import realtime_tools as T
        return await self._run(T.pc_profile_status)

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

    # --- smart home: lights, switches, climate, locks, scenes -------------

    @function_tool()
    async def control_smart_home(self, command: str) -> str:
        """Control a Home Assistant device: lights, switches, climate, locks, scenes.

        Pass the request close to how Tommy said it - "turn on Jesse's
        light", "dim the living room light to 30 percent", "make Jesse's
        light blue", "is the living room light on", "turn off the living
        room light". Also answers "what devices do I have" / "list my
        lights". If Home Assistant is not configured, say so plainly rather
        than guessing at device names.
        """
        from core import realtime_tools as T
        return await self._run(T.smart_home_command, command)

    # --- air conditioners (GE SmartHQ) -------------------------------------

    @function_tool()
    async def list_air_conditioners(self) -> str:
        """List the GE SmartHQ air conditioners ARGO can see, with their state."""
        from core import realtime_tools as T
        return await self._run(T.ac_list)

    @function_tool()
    async def get_ac_status(self, name: str) -> str:
        """Current state of one air conditioner: on/off, room temp, target, mode."""
        from core import realtime_tools as T
        return await self._run(T.ac_status, name)

    @function_tool()
    async def control_ac(self, name: str, power: str = "", temperature_f: int = 0,
                          mode: str = "", fan: str = "") -> str:
        """Turn an air conditioner on/off, or set its temperature, mode or fan speed.

        power is "on" or "off" - leave it "" if power should not change.
        temperature_f is 60-86 - leave it 0 if it should not change.
        mode and fan are whatever was said ("cool", "auto", "low", "high") -
        leave "" if they should not change. Only pass what Tommy actually
        asked to change, and report back what the unit says its state is
        now, not just that the command was sent.
        """
        from core import realtime_tools as T
        return await self._run(T.ac_control, name, power, temperature_f, mode, fan)

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

    @function_tool()
    async def search_knowledge_base(self, query: str) -> str:
        """Look up Tommy's own knowledge base for biographical or written-record answers.

        This is his AnythingLLM library - his about-me profile, wiki notes,
        blog mirrors, and book manuscript - not ordinary conversation
        history (use recall() for that). Reach for this when he asks
        something about his own life, writing, or history that isn't
        already in your instructions or memory: "what did I write about
        the Gunn Kraft build", "what's in my writing guide", "what's my
        maker background". Not for small talk or anything about right now.
        """
        from core import realtime_tools as T
        return await self._run(T.rag_search, query)


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
