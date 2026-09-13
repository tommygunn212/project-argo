"""Exercise real git isolation and child processes, with no paid model or audio."""
import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.code_repair import CodeRepairManager
from core.intent_parser import detect_self_diagnostics
from core.repair_service import RepairService
from core.self_diagnostics import AssistedRecovery, ComponentHealth, HealthStatus


@pytest.mark.parametrize("text", ["ARGO, your voice isn't working, fix it", "your thing is not working properly fix it", "fix yourself", "diagnose and fix it"])
def test_self_repair_intent(text):
    assert detect_self_diagnostics(text)


@pytest.mark.parametrize("text", ["my printer is not working fix it", "diagnose and fix my car", "write code to repair a database"])
def test_external_problem_is_not_self_repair(text):
    assert not detect_self_diagnostics(text)


def test_approval_consumed_once_and_errors_not_success():
    events = []
    recovery = AssistedRecovery(broadcast_fn=lambda *x: events.append(x))
    recovery._execute_action = AsyncMock(return_value={"status": "error", "message": "Device unavailable"})
    proposal = recovery.propose("reinit_audio", "Broken input")
    result = asyncio.run(recovery.execute_if_approved(proposal.proposal_id, True))
    assert result["status"] == "error"
    assert recovery.action_log[-1]["result"] == "error"
    assert asyncio.run(recovery.execute_if_approved(proposal.proposal_id, True))["status"] == "error"
    assert recovery._execute_action.await_count == 1
    assert not any(event[1].get("status") == "success" for event in events)


@pytest.mark.parametrize("approval", [False, "true", 1, None])
def test_invalid_or_declined_approval_never_executes(approval):
    recovery = AssistedRecovery()
    recovery._execute_action = AsyncMock()
    p = recovery.propose("reinit_audio", "Broken")
    asyncio.run(recovery.execute_if_approved(p.proposal_id, approval))
    recovery._execute_action.assert_not_called()


def test_expired_approval_is_rejected():
    recovery = AssistedRecovery()
    proposal = recovery.propose("reinit_audio", "Broken")
    proposal.expires_at = 0
    assert asyncio.run(recovery.execute_if_approved(proposal.proposal_id, True))["status"] == "error"


def test_retry_calls_saved_operation_and_checks_answer():
    recovery = AssistedRecovery()
    callback = Mock(return_value="Recovered response")
    recovery.retry_callback = callback
    p = recovery.propose("retry_last", "Response failed")
    result = asyncio.run(recovery.execute_if_approved(p.proposal_id, True))
    assert result["answer"] == "Recovered response"
    callback.assert_called_once()
    assert recovery.retry_callback is None
    p = recovery.propose("retry_last", "Response failed")
    assert asyncio.run(recovery.execute_if_approved(p.proposal_id, True))["status"] == "error"


def test_spoken_diagnosis_approval_repair_and_recheck():
    state = {"broken": True}
    events = []
    class Diagnostic:
        def check_all(self):
            self.last_check = {"audio_input": ComponentHealth("audio_input",
                HealthStatus.ERROR if state["broken"] else HealthStatus.OK,
                "Audio disconnected" if state["broken"] else "Audio available", recovery_action="reinit_audio")}
        def get_summary(self):
            return {"overall": "error" if state["broken"] else "ok", "summary": "Audio unavailable" if state["broken"] else "Checks passed"}
    recovery = AssistedRecovery()
    async def repair(_):
        state["broken"] = False
        return {"status": "success", "message": "Reopened audio."}
    recovery._execute_action = repair
    service = RepairService(recovery, Mock(), lambda *x: events.append(x), Diagnostic)
    assert service.handle_text("ARGO your voice is broken fix it")["status"] == "proposed"
    assert state["broken"]
    result = service.handle_text("approve repair")
    assert result["status"] == "checks_passed" and not state["broken"]
    assert service.handle_text("repair status")["message"] == result["message"]
    assert service.handle_text("approve repair")["status"] == "error"
    assert len([e for e in events if e[0] == "diagnostics_result"]) == 2


@pytest.fixture
def repo(tmp_path):
    directory = tmp_path / "argo"
    directory.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True)
    git("init")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "ARGO Test")
    (directory / ".gitignore").write_text("runtime/\n__pycache__/\n", encoding="utf-8")
    (directory / "answer.py").write_text("VALUE = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "baseline")
    return directory


def launch_fixture_agent(monkeypatch, repo, *, fail=False, test_fail=False, hang=False):
    completed = threading.Event()
    broadcasts = []
    def broadcast(kind, payload):
        broadcasts.append((kind, payload))
        if kind == "code_repair_result":
            completed.set()
    manager = CodeRepairManager(repo, broadcast, timeout=0.2 if hang else 1800,
        verify_command=[sys.executable, "-c", "import answer; assert answer.VALUE == " + ("999" if test_fail else "2")])
    # Real subprocess writes a deterministic repair in the checkout. Git clone,
    # review collection, tests, hash checking, and apply are production code.
    original_popen = subprocess.Popen
    def launch(command, **kwargs):
        if command[0] != "fixture-codex":
            return original_popen(command, **kwargs)
        assert "gpt-6-astra" in command
        assert "--approve-for-me" not in command
        assert "workspace-write" in command
        assert Path(kwargs["cwd"]).resolve() != repo.resolve()
        result_path = command[command.index("-o") + 1]
        script = ("from pathlib import Path; "
            "Path('answer.py').write_text('VALUE = 2\\n'); "
            "Path('new_file.py').write_text('NEW = True\\n'); "
            f"Path({str(result_path)!r}).write_text('Fixed VALUE; inspect verification output.'); " +
            ("import time; time.sleep(30); " if hang else "") +
            f"raise SystemExit({7 if fail else 0})")
        return original_popen([sys.executable, "-c", script], **kwargs)
    monkeypatch.setattr("core.code_repair.shutil.which", lambda _: "fixture-codex")
    monkeypatch.setattr("core.code_repair.subprocess.Popen", launch)
    proposal = manager.propose("Fix VALUE to 2")
    result = manager.dispatch_if_approved(proposal["action_id"], True)
    assert result["status"] == "running", result
    assert completed.wait(20), manager.snapshot()
    return manager, manager.snapshot()[0]


def test_isolated_repair_end_to_end_review_then_apply(monkeypatch, repo):
    manager, job = launch_fixture_agent(monkeypatch, repo)
    assert job["status"] == "review_ready", job
    assert job["test_exit"] == 0 and job["exit_code"] == 0
    assert "new_file.py" in job["changed_files"]
    assert (repo / "answer.py").read_text() == "VALUE = 1\n"
    assert not (repo / "new_file.py").exists()
    assert "VALUE = 2" in job["diff"]
    # Restart restores review evidence without relaunching the agent.
    restored = CodeRepairManager(repo)
    assert restored.snapshot()[0]["status"] == "review_ready"
    result = restored.apply_if_approved(job["action_id"], job["patch_sha256"], True)
    assert result["status"] == "applied", result
    assert (repo / "answer.py").read_text() == "VALUE = 2\n"
    assert (repo / "new_file.py").exists()
    assert restored.apply_if_approved(job["action_id"], job["patch_sha256"], True)["status"] == "error"


@pytest.mark.parametrize("agent_fail,test_fail", [(True, False), (False, True)])
def test_failed_agent_or_test_cannot_apply(monkeypatch, repo, agent_fail, test_fail):
    manager, job = launch_fixture_agent(monkeypatch, repo, fail=agent_fail, test_fail=test_fail)
    assert job["status"] == "review_failed"
    assert manager.apply_if_approved(job["action_id"], job["patch_sha256"], True)["status"] == "error"
    assert (repo / "answer.py").read_text() == "VALUE = 1\n"


def test_agent_timeout_is_terminal_and_cannot_apply(monkeypatch, repo):
    manager, job = launch_fixture_agent(monkeypatch, repo, hang=True)
    assert job["status"] == "review_failed"
    assert job["timed_out"] is True
    assert job["test_exit"] is None
    assert (repo / "answer.py").read_text() == "VALUE = 1\n"


@pytest.mark.parametrize("change", ["dirty", "patch"])
def test_apply_rejects_changed_checkout_or_reviewed_patch(monkeypatch, repo, change):
    manager, job = launch_fixture_agent(monkeypatch, repo)
    if change == "dirty":
        (repo / "answer.py").write_text("VALUE = 99\n")
    else:
        Path(job["patch_path"]).write_text("tampered")
    assert manager.apply_if_approved(job["action_id"], job["patch_sha256"], True)["status"] == "error"


def test_decline_and_duplicate_proposals(repo):
    manager = CodeRepairManager(repo)
    a, b = manager.propose("first"), manager.propose("second")
    assert a["action_id"] != b["action_id"]
    assert manager.dispatch_if_approved(a["action_id"], False)["status"] == "cancelled"
    assert manager.dispatch_if_approved(a["action_id"], True)["status"] == "error"
    assert manager.dispatch_if_approved(b["action_id"], "true")["status"] == "error"


def test_active_checks_ignore_unused_ollama_and_use_selected_devices(monkeypatch):
    from core.repair_service import ActiveDiagnostics
    import sounddevice
    checked = []
    def device(index):
        checked.append(index)
        return {"name": str(index), "max_input_channels": 1, "max_output_channels": 1}
    monkeypatch.setattr(sounddevice, "query_devices", device)
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    pipeline = SimpleNamespace(_llm_router=SimpleNamespace(provider_chain=lambda: [SimpleNamespace(provider="openai", base_url="")]),
        stt_engine_manager=SimpleNamespace(model=object()), _tts_engine="openai", _openai_tts=object(),
        audio=SimpleNamespace(_input_device_index=3, _output_device_index=4))
    diagnostic = ActiveDiagnostics(pipeline)
    diagnostic._check_ollama = Mock(side_effect=AssertionError("Unused Ollama must not be probed"))
    result = diagnostic.check_all()
    assert "ollama" not in result
    assert checked == [3, 4]
    assert result["llm"].status == HealthStatus.WARNING  # No live cloud call claimed.


def test_classic_pipeline_routes_repair_before_llm():
    from core.pipeline import ArgoPipeline
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.repair_service = Mock()
    pipeline.repair_service.handle_text.return_value = {"message": "Checks pass; retry your symptom."}
    pipeline._deliver_canonical_response = Mock()
    pipeline.handle_user_text("approve repair", confidence_hint=1.0)
    pipeline.repair_service.handle_text.assert_called_once_with("approve repair")
    assert pipeline._deliver_canonical_response.call_args.args[0] == "Checks pass; retry your symptom."


def test_spoken_failure_and_failed_verification_are_not_fixed():
    recovery = AssistedRecovery()
    recovery._execute_action = AsyncMock(return_value={"status": "success", "message": "Action completed."})
    class BrokenDiagnostic:
        def check_all(self):
            raise RuntimeError("health probe unavailable")
    service = RepairService(recovery, Mock(), Mock(), BrokenDiagnostic)
    proposal = recovery.propose("reinit_audio", "broken")
    result = service.respond(proposal.proposal_id, True)
    assert result["status"] == "unverified"
    assert "verification failed" in result["message"]


def test_runtime_recovery_uses_actual_audio_methods():
    audio = SimpleNamespace(clear_buffers=Mock(), stop=Mock(), start=Mock())
    recovery = AssistedRecovery(pipeline=SimpleNamespace(audio=audio))
    assert asyncio.run(recovery._clear_audio_buffer())["status"] == "success"
    audio.clear_buffers.assert_called_once()
    assert asyncio.run(recovery._reinit_audio())["status"] == "success"
    audio.stop.assert_called_once()
    audio.start.assert_called_once()


def test_restarted_inflight_job_is_interrupted(repo):
    manager = CodeRepairManager(repo)
    proposal = manager.propose("repair")
    job = manager.jobs[proposal["action_id"]]
    job["status"] = "running"
    manager._save(job)
    restored = CodeRepairManager(repo)
    assert restored.snapshot()[0]["status"] == "interrupted"


def test_launch_error_becomes_persisted_failure(monkeypatch, repo):
    manager = CodeRepairManager(repo)
    proposal = manager.propose("repair")
    monkeypatch.setattr("core.code_repair.shutil.which", lambda _: None)
    result = manager.dispatch_if_approved(proposal["action_id"], True)
    assert result["status"] == "failed"
    assert CodeRepairManager(repo).snapshot()[0]["status"] == "failed"


def test_livekit_tool_to_real_http_repair_endpoint(monkeypatch, tmp_path):
    import ast
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    import os
    from unittest.mock import patch
    # The sidecar loads .env at import. Keep that intentional production behavior
    # from changing the environment of other tests in this process.
    with patch.dict(os.environ):
        import livekit_realtime_agent as realtime
    # Compile the actual HTTP handler alone; importing main would initialize
    # unrelated production databases/logging. No routes are reimplemented.
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FrontendHandler")
    recovery = AssistedRecovery()
    recovery._execute_action = AsyncMock(return_value={"status": "error", "message": "Disconnected device"})
    service = RepairService(recovery, Mock(), Mock())
    recovery.propose("reinit_audio", "Input failed")
    scope = {"SimpleHTTPRequestHandler": SimpleHTTPRequestHandler, "json": json,
        "urlparse": urlparse, "parse_qs": parse_qs, "Path": Path,
        "repair_bridge_token": "test-local-token", "repair_service_ref": service}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"), scope)
    server = ThreadingHTTPServer(("127.0.0.1", 0), scope["FrontendHandler"])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/api/repair-voice"
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base, data=b'{"text":"approve repair"}', headers={"Content-Type": "application/json"}))
        assert error.value.code == 403
        recovery._execute_action.assert_not_called()
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        (runtime / "repair_bridge.token").write_text("test-local-token")
        monkeypatch.setattr(realtime, "ROOT", tmp_path)
        monkeypatch.setenv("ARGO_HTTP_PORT", str(server.server_port))
        # Call the same registered tool the LiveKit session uses, over real HTTP.
        result = json.loads(asyncio.run(realtime.ArgoRealtimeAgent.repair_argo(None, "approve repair")))
        assert result["status"] == "error"
        assert "Disconnected" in result["message"]
        assert recovery._execute_action.await_count == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
