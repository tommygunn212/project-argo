"""Characterization tests for frontend WebSocket lifecycle and dispatch."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import main


class _WebSocket:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


@pytest.mark.asyncio
async def test_websocket_syncs_baseline_and_removes_disconnected_client(monkeypatch):
    websocket = _WebSocket()
    main.connected_clients.clear()
    monkeypatch.setattr(main, "pipeline_ref", None)
    monkeypatch.setattr(main, "CURRENT_STATUS", "LISTENING")
    monkeypatch.setattr(main, "get_config_hash", Mock(return_value="cfg-hash"))
    monkeypatch.setattr(main, "get_runtime_overrides", Mock(return_value={"x": 1}))
    monkeypatch.setattr(main, "get_db_status", Mock(return_value={"ready": True}))

    await main.websocket_handler(websocket)

    assert [message["type"] for message in websocket.sent] == [
        "status",
        "config",
        "runtime_overrides",
        "audio_owner",
        "db_status",
    ]
    assert websocket.sent[0]["payload"] == "LISTENING"
    assert websocket not in main.connected_clients


@pytest.mark.asyncio
async def test_websocket_ignores_bad_json_and_dispatches_voice_and_text(monkeypatch):
    websocket = _WebSocket(
        [
            "not-json",
            json.dumps({"type": "set_voice", "payload": "nova"}),
            json.dumps({"type": "text_input", "payload": "hello"}),
        ]
    )
    pipeline = SimpleNamespace(
        set_voice=Mock(),
        stt_model_name="unknown",
        stt_model=None,
        llm_model_name="unknown",
        current_voice_key=None,
        _tts_engine="edge",
        _tts_model="tts-1",
    )
    main.connected_clients.clear()
    monkeypatch.setattr(main, "pipeline_ref", pipeline)
    monkeypatch.setattr(main, "_handle_text_input", Mock())
    monkeypatch.setattr(main, "get_config_hash", Mock(return_value="hash"))
    monkeypatch.setattr(main, "get_runtime_overrides", Mock(return_value={}))
    monkeypatch.setattr(main, "get_db_status", Mock(return_value={}))

    await main.websocket_handler(websocket)

    pipeline.set_voice.assert_called_once_with("nova")
    main._handle_text_input.assert_called_once_with("hello")
    assert websocket not in main.connected_clients


@pytest.mark.asyncio
async def test_websocket_cleanup_runs_when_initial_sync_fails(monkeypatch):
    websocket = _WebSocket()
    websocket.send = AsyncMock(side_effect=RuntimeError("connection closed"))
    main.connected_clients.clear()

    with pytest.raises(RuntimeError, match="connection closed"):
        await main.websocket_handler(websocket)

    assert websocket not in main.connected_clients
