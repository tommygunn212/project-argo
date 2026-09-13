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


def _memory_snapshot() -> tuple:
    """(total_gb, used_percent), or (None, None) if it cannot be read."""
    try:
        from system_health import get_memory_info

        total_gb, used_pct = get_memory_info()
        return total_gb, used_pct
    except Exception:
        logger.exception("[Tools] memory info unavailable")
        return None, None


class ArgoRealtimeAgent(Agent):
    def __init__(self, cfg: LiveKitRealtimeConfig) -> None:
        super().__init__(
            instructions=cfg.instructions + (
                " When the user reports ARGO is broken or requests self repair, call repair_argo with their exact words. "
                "Read the actual returned findings. Ask them to say 'approve repair' or 'cancel repair' "
                "only when a runtime proposal exists; pass that exact phrase to the tool when they do. "
                "Never invent a successful repair. Code repairs require dashboard approval and review."
                " You can inspect this PC and your own install: call get_pc_specs for hardware "
                "(motherboard, CPU, RAM, graphics), get_drive_space for disk space, get_system_status "
                "for live health and temperatures, find_files to locate a file, and list_argo_files to "
                "see your own folders. Call the tool and answer from what it returns - never guess at "
                "hardware, free space or filenames, and never say you cannot look when one of these "
                "tools would answer the question."),
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

    # ---- Machine and filesystem inspection -------------------------------
    # The classic pipeline answers these through its _respond_with_* handlers.
    # The realtime path never imports the pipeline, so without these tools the
    # model has no way to see the machine and correctly refuses to guess.
    # All read-only; each wrapped in a thread because they do blocking IO/WMI.

    @function_tool()
    async def get_pc_specs(self) -> str:
        """Report this PC's hardware: motherboard, BIOS, CPU, memory and graphics card.

        Use for any question about what the machine is or what is inside it.
        """
        def call():
            from system_profile import get_system_profile, get_gpu_profile

            p = get_system_profile() or {}
            gpus = get_gpu_profile() or []
            total_gb, used_pct = _memory_snapshot()
            return json.dumps({
                "motherboard": p.get("motherboard") or p.get("motherboard_product"),
                "motherboard_maker": p.get("motherboard_maker"),
                "bios_version": p.get("bios_version"),
                "cpu": p.get("cpu"),
                "cpu_cores": p.get("cpu_cores"),
                "cpu_threads": p.get("cpu_threads"),
                "cpu_max_mhz": p.get("cpu_max_mhz"),
                "memory_total_gb": total_gb,
                "memory_used_percent": used_pct,
                "memory_speed_mhz": p.get("memory_speed_mhz"),
                "memory_modules": p.get("memory_modules"),
                "graphics": [{"name": g.get("name"), "driver": g.get("driver_version")} for g in gpus],
                "os": p.get("os"),
            }, default=str)
        return await asyncio.to_thread(call)

    @function_tool()
    async def get_drive_space(self) -> str:
        """Report free and used space for every drive on this PC."""
        def call():
            from system_health import get_disk_info

            return json.dumps(get_disk_info() or {}, default=str)
        return await asyncio.to_thread(call)

    @function_tool()
    async def get_system_status(self) -> str:
        """Report live machine health: memory use, temperatures and overall status."""
        def call():
            from system_health import get_system_health, get_temperatures

            total_gb, used_pct = _memory_snapshot()
            return json.dumps({
                "health": get_system_health() or {},
                "temperatures_c": get_temperatures() or {},
                "memory_total_gb": total_gb,
                "memory_used_percent": used_pct,
            }, default=str)
        return await asyncio.to_thread(call)

    @function_tool()
    async def find_files(self, query: str) -> str:
        """Search this PC for files by name or keyword.

        Pass what the user is looking for, e.g. "invoice pdf" or "livekit config".
        """
        def call():
            from tools.filesystem import search_files, format_file_list_for_speech

            hits = search_files(query, max_results=12) or []
            return format_file_list_for_speech(hits, label=f"files matching {query}")
        return await asyncio.to_thread(call)

    @function_tool()
    async def list_argo_files(self, subfolder: str = "") -> str:
        """List ARGO's own files and folders. Pass a subfolder like "core" or "" for the root.

        Use when asked what files ARGO has, or what is in one of its folders.
        """
        def call():
            target = (ROOT / subfolder).resolve() if subfolder else ROOT
            # Stay inside the ARGO install; voice input must not walk the disk.
            if ROOT not in target.parents and target != ROOT:
                return f"{subfolder} is outside ARGO's folder, so I did not look there."
            if not target.is_dir():
                return f"There is no folder called {subfolder} in ARGO."
            dirs, files = [], []
            for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                if item.name.startswith((".", "__")):
                    continue
                (dirs if item.is_dir() else files).append(item.name)
            where = subfolder or "the ARGO root"
            # Cap the names, but say so. A silently truncated alphabetical list
            # makes the model report that a file is absent when it is simply
            # past the cut-off.
            cap = 200
            return json.dumps({
                "folder": where,
                "subfolders": dirs[:cap],
                "files": files[:cap],
                "counts": {"subfolders": len(dirs), "files": len(files)},
                "truncated": len(dirs) > cap or len(files) > cap,
            })
        return await asyncio.to_thread(call)


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


server = build_agent_server()


if __name__ == "__main__":
    cli.run_app(server)
