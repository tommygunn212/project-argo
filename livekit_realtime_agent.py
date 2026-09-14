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
    def __init__(self, cfg: LiveKitRealtimeConfig) -> None:
        super().__init__(
            instructions=cfg.instructions + (
                " When the user reports ARGO is broken or requests self repair, call repair_argo with their exact words. "
                "Read the actual returned findings. Ask them to say 'approve repair' or 'cancel repair' "
                "only when a runtime proposal exists; pass that exact phrase to the tool when they do. "
                "Never invent a successful repair. Code repairs require dashboard approval and review."
                " You can act on this machine, and you should. Hardware: get_pc_specs. Disk space: "
                "get_drive_space. Live health and temperatures: get_system_status. Your own faults: "
                "run_self_diagnostics. Files: list_argo_files, list_folder, read_text_file, find_files. "
                "Music: play_music, stop_music, next_track, get_music_status. Applications: open_app, "
                "close_app, focus_app, list_running_apps. Sound: set_volume, get_volume. "
                "Call the tool and answer from what it returns. Never guess at hardware, free space, "
                "filenames or what is playing, and never say you cannot look or cannot do something "
                "when one of these tools would do it. If a tool returns ok false, say plainly what it "
                "reported - if a folder was refused, tell Tommy it needs adding to "
                "filesystem.allowed_folders in config.json."),
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


async def _run_realtime_session(ctx: JobContext) -> None:
    _ensure_logging()
    cfg = get_livekit_realtime_config()
    logger.info(
        "[LiveKit] starting ARGO realtime session room=%s model=%s voice=%s personality=%s",
        getattr(ctx.job.room, "name", cfg.room),
        cfg.model,
        cfg.voice,
        cfg.personality,
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

    noise_filter = _build_noise_filter(cfg)

    await session.start(
        agent=ArgoRealtimeAgent(cfg),
        room=ctx.room,
        room_input_options=room_io.RoomInputOptions(
            audio_enabled=True,
            text_enabled=True,
            pre_connect_audio=True,
            noise_cancellation=noise_filter,
        ),
        room_output_options=room_io.RoomOutputOptions(
            audio_enabled=True,
            transcription_enabled=True,
        ),
    )

    _log_session_activity(session)

    if cfg.greeting:
        session.generate_reply(instructions=cfg.greeting, allow_interruptions=True)

    # Keep the optional avatar session strongly referenced for the room lifetime.
    _ = hedra_avatar


def _log_session_activity(session: AgentSession) -> None:
    """Say, in the log, whether ARGO heard anything and whether it answered.

    Without this a silent session and a deaf session look identical: one
    "starting ARGO realtime session" line and nothing after it. Every handler
    swallows its own errors - diagnostics must never be what breaks voice.
    """

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

    def on_user_state(event):
        logger.info("[Session] user %s -> %s",
                    getattr(event, "old_state", "?"), getattr(event, "new_state", "?"))

    def on_agent_state(event):
        logger.info("[Session] agent %s -> %s",
                    getattr(event, "old_state", "?"), getattr(event, "new_state", "?"))

    def on_conversation_item(event):
        item = getattr(event, "item", None)
        logger.info("[Session] %s said: %r",
                    getattr(item, "role", "?"), (getattr(item, "text_content", "") or "")[:200])

    def on_error(event):
        logger.error("[Session] error: %s", getattr(event, "error", event))

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
    # Built here, not at import. build_agent_server() calls _apply_livekit_env,
    # which mutates os.environ, and opens a LiveKit AgentServer - importing this
    # module to inspect its tools or to test them should do neither.
    cli.run_app(build_agent_server())
