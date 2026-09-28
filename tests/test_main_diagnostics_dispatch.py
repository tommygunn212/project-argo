"""Contract tests for dashboard diagnostics dispatch."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import main


@pytest.mark.asyncio
async def test_repair_service_path_runs_off_loop_and_broadcasts(monkeypatch):
    service = SimpleNamespace(handle_text=Mock(return_value={"ok": True}))
    broadcast = Mock()
    websocket = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(main, "repair_service_ref", service)
    monkeypatch.setattr(main, "broadcast_msg", broadcast)

    await main._handle_diagnostics(websocket)

    service.handle_text.assert_called_once_with("Run diagnostics")
    broadcast.assert_called_once_with("recovery_result", {"ok": True})
    websocket.send.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_diagnostics_sends_summary_logs_and_proposes_recovery(monkeypatch):
    summary = {
        "summary": "one issue",
        "errors": [{"name": "audio", "message": "device unavailable"}],
    }
    diagnostics = SimpleNamespace(
        check_all=Mock(),
        get_summary=Mock(return_value=summary),
        last_check={"audio": SimpleNamespace(recovery_action="restart audio")},
    )
    recovery = SimpleNamespace(propose=Mock())
    websocket = SimpleNamespace(send=AsyncMock())
    event = Mock()
    monkeypatch.setattr(main, "repair_service_ref", None)
    monkeypatch.setattr(main, "diagnostics_ref", diagnostics)
    monkeypatch.setattr(main, "recovery_ref", recovery)
    monkeypatch.setattr(main, "log_event", event)

    await main._handle_diagnostics(websocket)

    diagnostics.check_all.assert_called_once_with()
    websocket.send.assert_awaited_once_with(
        json.dumps({"type": "diagnostics_result", "payload": summary})
    )
    event.assert_called_once_with("DIAGNOSTICS: one issue", stage="diagnostics")
    recovery.propose.assert_called_once_with("restart audio", "device unavailable")


@pytest.mark.asyncio
async def test_legacy_diagnostics_failure_returns_structured_error(monkeypatch):
    diagnostics = SimpleNamespace(
        check_all=Mock(side_effect=RuntimeError("probe failed"))
    )
    websocket = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(main, "repair_service_ref", None)
    monkeypatch.setattr(main, "diagnostics_ref", diagnostics)

    await main._handle_diagnostics(websocket)

    payload = json.loads(websocket.send.await_args.args[0])
    assert payload == {
        "type": "diagnostics_result",
        "payload": {
            "overall": "error",
            "summary": "Diagnostics failed: probe failed",
        },
    }
