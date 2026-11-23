"""core/job_runner.py + the disk-backed side of core/delegate_jobs.py:
jobs live in their own process, survive the voice session, and show honest states."""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core import delegate_jobs as D
from core import job_runner as R

ROOT = Path(__file__).resolve().parents[1]
FAKE_CLI = str(Path(__file__).parent / "fixtures" / "fake_agent_cli.py")


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(D, "_jobs", {})
    monkeypatch.setattr(D, "_tasks", {})
    return tmp_path


def make_job(tmp, job_id="20260101-000000-aaaaaa", cmd=None, prompt="make a file", engine="claude",
             timeout_s=30, **status):
    job_dir = tmp / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    work = tmp / "work"
    work.mkdir(exist_ok=True)
    spec = {"cmd": cmd or [sys.executable, FAKE_CLI], "cwd": str(work), "prompt": prompt,
            "timeout_s": timeout_s, "engine": engine, "result_file": "",
            "progress_file": str(work / "progress.json")}
    (job_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    base = {"id": job_id, "task": "t", "folder": str(work), "status": "starting",
            "started": time.time(), "reported": False}
    base.update(status)
    (job_dir / "status.json").write_text(json.dumps(base), encoding="utf-8")
    return job_dir


def run_runner(job_dir):
    return subprocess.run([sys.executable, "-m", "core.job_runner", str(job_dir)], cwd=str(ROOT),
                          timeout=60, capture_output=True, text=True)


def status_of(job_dir):
    return json.loads((job_dir / "status.json").read_text(encoding="utf-8"))


def test_the_runner_finishes_a_job_with_no_watcher_at_all(jobs):
    job_dir = make_job(jobs)
    run_runner(job_dir)
    saved = status_of(job_dir)
    assert saved["status"] == "done" and "made_by_agent.txt" in saved["summary"]
    assert (jobs / "work" / "made_by_agent.txt").exists()
    assert saved["pid"] and saved["runner_pid"] and saved["heartbeat"]


def test_a_blocked_agent_becomes_waiting_with_its_question(jobs):
    script = jobs / "ask.py"
    script.write_text(
        "import json,sys\nsys.stdin.read()\n"
        "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
        "'result':'Got partway.\\nNEED_ANSWER: Which folder should the recipes go in?'}))\n",
        encoding="utf-8")
    job_dir = make_job(jobs, cmd=[sys.executable, str(script)])
    run_runner(job_dir)
    saved = status_of(job_dir)
    assert saved["status"] == "waiting"
    assert saved["question"] == "Which folder should the recipes go in?"


def test_cancel_file_stops_the_agent(jobs):
    job_dir = make_job(jobs, prompt="SLEEP forever")
    proc = subprocess.Popen([sys.executable, "-m", "core.job_runner", str(job_dir)], cwd=str(ROOT))
    deadline = time.time() + 20
    while time.time() < deadline and status_of(job_dir).get("status") != "running":
        time.sleep(0.2)
    (job_dir / "cancel").write_text("1")
    proc.wait(timeout=30)
    assert status_of(job_dir)["status"] == "cancelled"


def test_timeout_is_recorded(jobs):
    job_dir = make_job(jobs, prompt="SLEEP forever", timeout_s=2)
    run_runner(job_dir)
    assert status_of(job_dir)["status"] == "timed_out"


def test_progress_file_gives_a_percent_and_finished_means_100(jobs):
    (jobs / "work").mkdir(exist_ok=True)
    (jobs / "work" / "progress.json").write_text(
        json.dumps({"done": 6, "total": 7, "step": "tests"}), encoding="utf-8")
    assert R.read_progress(str(jobs / "work" / "progress.json")) == {
        "progress_done": 6, "progress_total": 7, "step": "tests"}
    job = D.Job(id="x", task="t", folder="f", status="running", progress_done=6,
                progress_total=7, started=time.time(), last_activity=time.time())
    assert job.brief()["percent"] == 86
    job.status, job.progress_done = "done", 3
    assert job.brief()["percent"] == 100
    assert R.read_progress("") == {} and R.read_progress(str(jobs / "nope.json")) == {}


def test_quiet_job_is_stalled_but_a_fresh_one_is_not(jobs):
    now = time.time()
    fresh = D.Job(id="a", task="t", folder="f", status="running", started=now - 3600,
                  last_activity=now - 5, heartbeat=now)
    quiet = D.Job(id="b", task="t", folder="f", status="running", started=now - 3600,
                  last_activity=now - 900, heartbeat=now)
    assert fresh.brief()["state"] == "running"
    assert quiet.brief()["state"] == "stalled" and quiet.brief()["quiet_seconds"] >= 900


def test_dead_runner_is_failed_not_running_forever(jobs):
    job_dir = make_job(jobs, status="running", started=time.time() - 600,
                       heartbeat=time.time() - 600, runner_pid=2_000_000_000)
    result = D.status()
    entry = [j for j in result["jobs"] if j["id"] == "20260101-000000-aaaaaa"][0]
    assert entry["status"] == "failed" and "runner" in entry["error"]
    assert status_of(job_dir)["status"] == "failed"


def test_status_reads_jobs_from_every_session(jobs):
    make_job(jobs, "20260101-000000-aaaaaa", status="done", finished=time.time(), reported=True)
    make_job(jobs, "20260102-000000-bbbbbb", status="done", finished=time.time(), reported=True)
    ids = [j["id"] for j in D.status()["jobs"]]
    assert ids == ["20260102-000000-bbbbbb", "20260101-000000-aaaaaa"]  # newest first
    assert D.status("20260101-000000-aaaaaa")["job"]["status"] == "done"


def test_a_new_session_announces_a_job_that_finished_while_nobody_was_there(jobs):
    job_dir = make_job(jobs, status="done", finished=time.time(), reported=False, summary="did it")
    told = []

    async def scenario():
        assert D.adopt(lambda job: told.append(job.id)) == 1
        await asyncio.gather(*D._tasks.values())
        assert D.adopt(lambda job: told.append(job.id)) == 0  # already told
    asyncio.run(scenario())
    assert told == ["20260101-000000-aaaaaa"] and status_of(job_dir)["reported"] is True


def test_asleep_session_does_not_mark_a_job_as_told(jobs):
    job_dir = make_job(jobs, status="done", finished=time.time(), reported=False)

    async def scenario():
        D.adopt(lambda job: False)
        await asyncio.gather(*D._tasks.values())
    asyncio.run(scenario())
    assert status_of(job_dir)["reported"] is False


def test_jobs_from_before_this_change_are_not_news(jobs):
    job_dir = make_job(jobs, status="done", finished=time.time())
    data = status_of(job_dir)
    data.pop("reported")
    (job_dir / "status.json").write_text(json.dumps(data), encoding="utf-8")
    assert D.adopt(lambda job: None) == 0


def test_a_running_job_from_an_earlier_session_can_be_cancelled(jobs):
    job_dir = make_job(jobs, status="running", heartbeat=time.time(), runner_pid=0)
    assert D.cancel("20260101-000000-aaaaaa")["ok"]
    assert (job_dir / "cancel").exists()
    assert D.cancel("nope")["ok"] is False


def test_retry_reruns_the_task_with_extra_detail_and_short_ids_work(jobs, monkeypatch):
    job_dir = make_job(jobs, status="failed", finished=time.time(), project="ChefsByte")
    (job_dir / "task.txt").write_text("make the thing", encoding="utf-8")
    assert D.resolve_id("aaaaaa") == "20260101-000000-aaaaaa"
    seen = {}

    async def fake_start(task, folder="", **kw):
        seen.update(task=task, folder=folder, **kw)
        return {"ok": True, "job_id": "new"}
    monkeypatch.setattr(D, "start", fake_start)
    result = asyncio.run(D.retry("aaaaaa", "use the blue folder"))
    assert result["ok"] and result["retry_of"] == "20260101-000000-aaaaaa"
    assert seen["task"].startswith("make the thing") and "use the blue folder" in seen["task"]
    assert seen["project"] == "ChefsByte"
    assert asyncio.run(D.retry("nope"))["ok"] is False
