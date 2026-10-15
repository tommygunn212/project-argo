"""Frontend WebSocket synchronization and command dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class FrontendWebSocketDependencies:
    connected_clients: set[Any]
    get_current_status: Callable[[], str]
    get_config_hash: Callable[[], str]
    get_runtime_overrides: Callable[[], dict[str, Any]]
    get_database_status: Callable[[], Any]
    get_pipeline: Callable[[], Any]
    get_code_repair: Callable[[], Any]
    handle_text_input: Callable[[Any], None]
    handle_diagnostics: Callable[[Any], Awaitable[None]]
    handle_recovery_response: Callable[[Any], Awaitable[None]]
    handle_code_repair_request: Callable[[Any], Any]
    handle_code_repair_response: Callable[[Any], Any]
    handle_control: Callable[[Any], None]
    handle_override: Callable[[Any], None]
    handle_next_override: Callable[[Any], None]
    handle_clear_overrides: Callable[[], None]
    broadcast: Callable[[str, Any], None]
    thread_factory: Callable[..., Any]
    run_in_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread


async def _send(websocket: Any, message_type: str, payload: Any) -> None:
    await websocket.send(json.dumps({"type": message_type, "payload": payload}))


async def _sync_connected_client(
    websocket: Any,
    dependencies: FrontendWebSocketDependencies,
) -> None:
    await _send(websocket, "status", dependencies.get_current_status())
    await _send(
        websocket, "config", {"hash": dependencies.get_config_hash()}
    )
    await _send(
        websocket, "runtime_overrides", dependencies.get_runtime_overrides()
    )
    await _send(
        websocket, "audio_owner", {"owner": "UNKNOWN", "contested": False}
    )
    await _send(websocket, "db_status", dependencies.get_database_status())

    pipeline = dependencies.get_pipeline()
    if pipeline is None:
        return
    try:
        stt_name = getattr(pipeline, "stt_model_name", "unknown")
        if stt_name and stt_name != "unknown":
            await _send(websocket, "log", f"Loading Whisper Model: {stt_name}...")
        if getattr(pipeline, "stt_model", None) is not None:
            await _send(websocket, "log", "STT model warmed up")
        llm_name = getattr(pipeline, "llm_model_name", "unknown")
        if llm_name and llm_name != "unknown":
            await _send(websocket, "log", "LLM model warmed up")
        voice_key = getattr(pipeline, "current_voice_key", None)
        if voice_key:
            await _send(websocket, "log", f"Voice switched to {voice_key}")
        await _send(
            websocket,
            "engine_config",
            {
                "tts_engine": getattr(pipeline, "_tts_engine", "edge"),
                "tts_model": getattr(pipeline, "_tts_model", "tts-1"),
                "tts_voice": getattr(pipeline, "current_voice_key", "nova"),
            },
        )
    except Exception:
        pass


async def _dispatch_message(
    websocket: Any,
    message_type: str,
    payload: Any,
    dependencies: FrontendWebSocketDependencies,
) -> None:
    pipeline = dependencies.get_pipeline()
    if message_type == "set_voice" and pipeline:
        pipeline.set_voice(payload)
    if message_type == "replay" and pipeline and payload:
        dependencies.thread_factory(
            target=pipeline.replay_interaction,
            args=(payload,),
            daemon=True,
        ).start()
    if message_type == "text_input" and pipeline and payload:
        dependencies.handle_text_input(payload)
    if message_type == "run_diagnostics":
        await dependencies.handle_diagnostics(websocket)
    if message_type == "recovery_response" and payload:
        await dependencies.handle_recovery_response(payload)
    if message_type == "code_repair_request" and isinstance(payload, dict):
        await dependencies.run_in_thread(
            dependencies.handle_code_repair_request, payload
        )
    if message_type == "code_repair_response" and payload:
        await dependencies.run_in_thread(
            dependencies.handle_code_repair_response, payload
        )

    code_repair = dependencies.get_code_repair()
    if message_type == "code_repair_status" and code_repair:
        await _send(websocket, "code_repair_jobs", code_repair.snapshot())
    if (
        message_type == "code_repair_apply"
        and isinstance(payload, dict)
        and code_repair
    ):
        result = await dependencies.run_in_thread(
            code_repair.apply_if_approved,
            payload.get("action_id"),
            payload.get("patch_sha256"),
            payload.get("approved"),
        )
        dependencies.broadcast("code_repair_result", result)
    if (
        message_type == "code_repair_restart"
        and isinstance(payload, dict)
        and code_repair
    ):
        result = await dependencies.run_in_thread(
            code_repair.restart_if_applied, payload.get("action_id")
        )
        dependencies.broadcast("code_repair_result", result)
    if message_type == "control" and payload:
        dependencies.handle_control(payload)
    if message_type == "override" and payload:
        dependencies.handle_override(payload)
    if message_type == "next_override" and payload:
        dependencies.handle_next_override(payload)
    if message_type == "clear_overrides":
        dependencies.handle_clear_overrides()


async def serve_frontend_websocket(
    websocket: Any,
    dependencies: FrontendWebSocketDependencies,
) -> None:
    """Synchronize one UI connection and dispatch messages until it closes."""
    dependencies.connected_clients.add(websocket)
    try:
        await _sync_connected_client(websocket, dependencies)
        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                continue
            await _dispatch_message(
                websocket,
                data.get("type"),
                data.get("payload"),
                dependencies,
            )
    finally:
        dependencies.connected_clients.discard(websocket)
