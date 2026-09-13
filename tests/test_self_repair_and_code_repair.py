import asyncio
from pathlib import Path
from unittest.mock import patch

from core.code_repair import CodeRepairManager
from core.intent_parser import detect_self_diagnostics
from core.self_diagnostics import AssistedRecovery


def test_plain_language_fix_request_reaches_diagnostics():
    assert detect_self_diagnostics("ARGO, something is not working properly, fix yourself")


def test_recovery_rejects_approval_without_visible_proposal():
    manager = AssistedRecovery()
    result = asyncio.run(manager.execute_if_approved("restart_ollama", True))
    assert result["status"] == "error"
    assert "proposal" in result["message"].lower()


def test_code_repair_writes_task_then_dispatches_only_after_approval(tmp_path: Path):
    manager = CodeRepairManager(root=tmp_path)
    proposal = manager.propose("Voice output is silent after start.")
    task = Path(proposal["task_path"])
    assert task.exists()
    assert "Voice output is silent" in task.read_text(encoding="utf-8")

    with patch("core.code_repair.shutil.which", return_value="codex"), patch("core.code_repair.subprocess.Popen") as popen:
        popen.return_value.pid = 4242
        result = manager.dispatch_if_approved(proposal["action_id"], True)

    assert result["status"] == "started"
    command = popen.call_args.args[0]
    assert command[:5] == ["codex", "exec", "-m", "gpt-6-astra", "-c"]
    assert 'model_reasoning_effort="high"' in command
    assert "--sandbox" in command and "workspace-write" in command


def test_code_repair_decline_never_starts_codex(tmp_path: Path):
    manager = CodeRepairManager(root=tmp_path)
    proposal = manager.propose("Repair a test failure")
    with patch("core.code_repair.subprocess.Popen") as popen:
        result = manager.dispatch_if_approved(proposal["action_id"], False)
    assert result["status"] == "cancelled"
    popen.assert_not_called()
