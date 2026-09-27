"""The Smooth Voice worker process: register with LiveKit, serve room jobs.

``main()`` is what ``livekit_realtime_agent.py`` runs. Nothing here happens at
import time: importing this package to inspect or test the tools must not
mutate ``os.environ``, take the single-instance lock or open an AgentServer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from pathlib import Path

from livekit.agents import AgentServer, JobExecutorType, cli

from core import voice_events
from core.livekit_config import LiveKitRealtimeConfig, get_livekit_realtime_config
from core.voice.activity import ensure_logging
from core.voice.session import run_realtime_session

logger = logging.getLogger("ARGO.LiveKit")

ROOT = Path(__file__).resolve().parents[2]
DRAIN_FILE = ROOT / "runtime" / "locks" / "realtime-worker.drain"
INSTANCE_NAME = "realtime-worker"


def build_agent_server(cfg: LiveKitRealtimeConfig | None = None) -> AgentServer:
    """An AgentServer ready for ``cli.run_app``, after clearing stale agents."""
    cfg = cfg or get_livekit_realtime_config()
    _export_livekit_env(cfg)
    ensure_logging()
    clear_stale_agents(cfg)

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
    server.rtc_session(run_realtime_session, agent_name=cfg.agent_name)

    try:
        voice_events.emit("worker_built", agent_name=cfg.agent_name, url=cfg.url,
                          model=cfg.model)
    except Exception:
        logger.debug("[Lifecycle] could not emit worker_built", exc_info=True)
    return server


def _export_livekit_env(cfg: LiveKitRealtimeConfig) -> None:
    """The LiveKit plugins read these; explicit environment always wins."""
    os.environ.setdefault("LIVEKIT_URL", cfg.url)
    os.environ.setdefault("LIVEKIT_API_KEY", cfg.api_key)
    os.environ.setdefault("LIVEKIT_API_SECRET", cfg.api_secret)
    if cfg.agent_name:
        os.environ.setdefault("LIVEKIT_AGENT_NAME", cfg.agent_name)


def clear_stale_agents(cfg: LiveKitRealtimeConfig) -> None:
    """Remove agent participants left behind by a previous worker process.

    LiveKit rooms outlive the worker. A killed worker leaves its agent
    participant in the room; the next browser joins a room that already has
    an agent, and this worker never receives the job. Tommy sees "connected"
    and gets silence.

    Only agent participants are removed, and only before this worker takes
    any job - a human in the room is left alone. Best effort: a failure here
    must never stop the worker starting.
    """
    try:
        asyncio.run(_remove_agent_participants(cfg))
    except Exception:
        logger.warning("[LiveKit] could not check for stale agents", exc_info=True)


async def _remove_agent_participants(cfg: LiveKitRealtimeConfig) -> None:
    from livekit import api

    http_url = cfg.url.replace("ws://", "http://").replace("wss://", "https://")
    lk = api.LiveKitAPI(http_url, cfg.api_key, cfg.api_secret)
    try:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        for room in rooms.rooms:
            listing = await lk.room.list_participants(api.ListParticipantsRequest(room=room.name))
            for participant in listing.participants:
                if participant.kind != api.ParticipantInfo.Kind.AGENT:
                    continue
                logger.warning("[LiveKit] removing stale agent %s from room %s "
                               "(left by a previous worker)", participant.identity, room.name)
                await lk.room.remove_participant(
                    api.RoomParticipantIdentity(room=room.name, identity=participant.identity)
                )
    finally:
        await lk.aclose()


def _watch_for_drain(drain_file: Path = DRAIN_FILE, poll_s: float = 0.5) -> None:
    """Graceful stop on request, without a console or a kill.

    The framework shuts down cleanly on SIGINT (drain, then deregister from
    LiveKit). On Windows nothing outside the process can deliver that signal
    to a hidden, redirected process - but the process can raise it on itself.
    So: the drain file appears, this thread raises SIGINT, the main thread
    takes the normal shutdown path. The file is removed first so a stale one
    cannot stop the next start.
    """
    while True:
        time.sleep(poll_s)
        try:
            if not drain_file.exists():
                continue
            try:
                drain_file.unlink()
            except OSError:
                logger.debug("[Lifecycle] could not remove drain file", exc_info=True)
            logger.warning("[Lifecycle] drain requested - shutting down gracefully")
            voice_events.emit("drain_requested")
            signal.raise_signal(signal.SIGINT)
            return
        except Exception:
            logger.debug("[Lifecycle] drain watcher error", exc_info=True)


def main() -> None:
    """Run the worker: verify the runtime, take the lock, serve until drained.

    The lock is the important half. A second worker registering under the
    same agent_name fails silently - LiveKit hands each job to whichever it
    likes, so "can ARGO hear me" becomes a coin flip and both logs look
    identical either way.
    """
    from core.runtime_guard import SingleInstance, verify_runtime

    verify_runtime(INSTANCE_NAME)
    threading.Thread(target=_watch_for_drain, name="argo-drain-watcher", daemon=True).start()
    with SingleInstance(INSTANCE_NAME):
        cli.run_app(build_agent_server())
