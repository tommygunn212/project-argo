"""core/delegate_jobs.py: background agent jobs run, report, time out and never raise."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from core import delegate_jobs as D

FAKE_CLI = str(Path(__file__).parent / "fixtures" / "fake_agent_cli.py")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(D, "build_command", lambda settings, exe, result_file="": [sys.executable, FAKE_CLI])
    monkeypatch.setattr(D, "_jobs", {})
    monkeypatch.setattr(D, "_tasks", {})
    monkeypatch.delenv("ARGO_DELEGATE_ENABLED", raising=False)
    settings = D.DelegateSettings(engine="claude", command="python",
                                  workspace=str(tmp_path / "work"), timeout_s=20)
    monkeypatch.setattr(D.shutil, "which", lambda name: sys.executable)
    return settings, tmp_path


def _run_job(task, settings, folder=""):
    done = []

    async def scenario():
        result = await D.start(task, folder, settings=settings, on_done=done.append)
        if result["ok"]:
            await D._tasks[result["job_id"]]
        return result
    return asyncio.run(scenario()), done


def test_a_job_runs_in_its_folder_and_reports(setup):
    settings, tmp = setup
    result, done = _run_job("make a file", settings)
    assert result["ok"] and done
    job = done[0]
    assert job.status == "done"
    assert "made_by_agent.txt" in job.summary
    assert (tmp / "work" / "made_by_agent.txt").read_text() == "hi from argo"
    saved = json.loads((job.job_dir / "status.json").read_text())
    assert saved["status"] == "done" and (job.job_dir / "task.txt").read_text() == "make a file"


def test_a_named_folder_is_used(setup):
    settings, tmp = setup
    _run_job("make a file", settings, folder=str(tmp / "printing"))
    assert (tmp / "printing" / "made_by_agent.txt").exists()


def test_failure_is_reported_not_raised(setup):
    settings, _ = setup
    _result, done = _run_job("FAIL please", settings)
    assert done[0].status == "failed" and done[0].error


def test_timeout_kills_the_job(setup):
    settings, _ = setup
    quick = D.DelegateSettings(**{**settings.__dict__, "timeout_s": 2})
    _result, done = _run_job("SLEEP forever", quick)
    assert done[0].status == "timed_out"


def test_switched_off_means_nothing_starts(setup, monkeypatch):
    settings, tmp = setup
    monkeypatch.setenv("ARGO_DELEGATE_ENABLED", "0")
    result, done = _run_job("make a file", D.load_settings({"delegate": {"workspace": str(tmp / "w")}}))
    assert result["ok"] is False and not done


def test_missing_cli_is_a_clear_message(setup, monkeypatch):
    settings, _ = setup
    monkeypatch.setattr(D, "resolve_executable", lambda s: None)
    result, _ = _run_job("anything", settings)
    assert result["ok"] is False and "not installed" in result["message"]


def test_running_limit_is_enforced(setup):
    settings, _ = setup
    limited = D.DelegateSettings(**{**settings.__dict__, "max_running": 1})

    async def scenario():
        first = await D.start("SLEEP a while", settings=limited)
        second = await D.start("make a file", settings=limited)
        await asyncio.sleep(1)  # let the process actually spawn before cancelling
        D.cancel(first["job_id"])
        with pytest.raises(asyncio.CancelledError):
            await D._tasks[first["job_id"]]
        return first, second
    first, second = asyncio.run(scenario())
    assert first["ok"] and not second["ok"]


def test_parse_result_reads_the_cli_json():
    ok, summary, cost = D.parse_result(json.dumps(
        {"type": "result", "subtype": "success", "is_error": False, "result": "done it",
         "total_cost_usd": 0.2}))
    assert (ok, summary, cost) == (True, "done it", 0.2)
    assert D.parse_result("")[0] is False


def test_task_goes_in_on_stdin_not_the_command_line():
    cmd = D.build_command(D.DelegateSettings(engine="claude"), "claude")
    assert cmd[:2] == ["claude", "-p"] and "--permission-mode" in cmd
    assert not any("Tommy" in part for part in cmd)
    codex = D.build_command(D.DelegateSettings(), "codex", "out.txt")
    assert codex[:2] == ["codex", "exec"] and codex[-1] == "-"
    assert "workspace-write" in codex and ["-o", "out.txt"] == codex[codex.index("-o"):codex.index("-o") + 2]


def test_codex_is_the_default_engine(monkeypatch):
    monkeypatch.delenv("ARGO_DELEGATE_ENGINE", raising=False)
    assert D.load_settings({}).engine == "codex"
    assert D.load_settings({"delegate": {"engine": "claude"}}).engine == "claude"
    assert D.load_settings({"delegate": {"engine": "nonsense"}}).engine == "codex"


def test_the_agent_exposes_the_delegate_tools():
    import livekit_realtime_agent as agent_mod

    for name in ("delegate_task", "check_background_tasks", "cancel_background_task"):
        assert hasattr(agent_mod.ArgoRealtimeAgent, name)


def test_a_codex_job_reports_its_last_message(setup, monkeypatch):
    settings, tmp = setup
    codex = D.DelegateSettings(**{**settings.__dict__, "engine": "codex"})
    monkeypatch.setattr(D, "build_command",
                        lambda s, exe, result_file="": [sys.executable, FAKE_CLI, "-o", result_file])
    _result, done = _run_job("make a file", codex)
    assert done[0].status == "done" and "made_by_agent.txt" in done[0].summary
    assert done[0].cost_usd is None
