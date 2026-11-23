"""Hand open-ended work to a full coding agent and keep talking while it runs.

Two engines: OpenAI Codex (``codex exec``, the default - it runs on Tommy's
ChatGPT plan, so jobs come out of that subscription with no per-job bill) and
Claude Code (``claude -p``, per-use or Agent SDK credit depending on login).

The realtime voice model is fast but can only call the tools it was given.
Anything that needs real hands - research across the web, making folders and
files, writing and running code, finding an STL and saving it - goes here: a
Claude Code agent run headless (``claude -p``) in a working folder, in the
background. ARGO says it started, keeps the conversation going, and is told
when it finishes so she can report back.

What this is NOT: the improve_argo / work_on_project bridge. Those are for
code changes to a Git project, in an isolated checkout, with review. This is
for "go do this for me" - research and errands.

Every job leaves a folder under ``runtime/agent_jobs/<id>/`` with the task,
the agent's full JSON result and a status file, so "what did it do?" always
has an answer. Settings live in config.json -> "delegate":

    "delegate": {
      "enabled": true,
      "engine": "codex",                     # or "claude"
      "command": "",                         # path to the CLI; found automatically if empty
      "workspace": "I:/argo-workspace",
      "permission_mode": "bypassPermissions",
      "timeout_s": 1800,
      "max_running": 2,
      "model": ""
    }

Tommy chose no confirmation gates for the beta, so the default permission
mode lets the agent act without asking. Change ``permission_mode`` to
``acceptEdits`` (files only) or ``default`` to rein it in. Note: headless
Claude Code on a subscription draws from the separate Agent SDK credit.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("ARGO.Delegate")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"
JOBS_DIR = ROOT / "runtime" / "agent_jobs"

AGENT_BRIEF = """You are working for Tommy as the hands of ARGO, his voice assistant.
He asked, out loud: {task}

Do the whole job, not a plan for it. Work in the current folder unless the task
names another place. When you finish, end with a short plain-language summary
(2-4 sentences) that ARGO will read aloud: what you did, where any files are,
and anything Tommy needs to decide. Say plainly if something failed or could
not be verified. Never print or copy secrets from config.json or .env files.

If you cannot continue without an answer from Tommy, stop and make your final
message start with a line of the form "NEED_ANSWER: <the one question>" - do
not guess at a decision that is his to make.

If the job has several steps, early on write {progress_file} (in the current
folder) as JSON like {{"done": 0, "total": 5, "step": "what you're on"}} and
update "done" as each step finishes, so Tommy can see it moving."""


CODEX_DEFAULT_MODEL = "gpt-6-astra"
CODEX_FALLBACK_PATHS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin" / "codex.exe",
)


@dataclass(frozen=True)
class DelegateSettings:
    enabled: bool = True
    engine: str = "codex"
    command: str = ""
    workspace: str = str(ROOT / "runtime" / "agent_workspace")
    permission_mode: str = "bypassPermissions"
    timeout_s: float = 1800.0
    max_running: int = 2
    model: str = ""


def load_settings(config: dict | None = None) -> DelegateSettings:
    if config is None:
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    raw = config.get("delegate") or {}
    base = DelegateSettings()
    env = os.getenv("ARGO_DELEGATE_ENABLED")
    enabled = bool(raw.get("enabled", base.enabled))
    if env is not None and env.strip():
        enabled = env.strip().lower() in {"1", "true", "yes", "on"}
    engine = str(os.getenv("ARGO_DELEGATE_ENGINE") or raw.get("engine") or base.engine).lower()
    return DelegateSettings(
        enabled=enabled,
        engine=engine if engine in {"codex", "claude"} else "codex",
        command=str(raw.get("command") or base.command),
        workspace=str(raw.get("workspace") or base.workspace),
        permission_mode=str(raw.get("permission_mode") or base.permission_mode),
        timeout_s=float(raw.get("timeout_s") or base.timeout_s),
        max_running=int(raw.get("max_running") or base.max_running),
        model=str(raw.get("model") or ""),
    )


@dataclass
class Job:
    id: str
    task: str
    folder: str
    status: str = "starting"  # starting, running, done, failed, timed_out, cancelled
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    summary: str = ""
    error: str = ""
    cost_usd: float | None = None
    project: str = ""
    heartbeat: float = 0.0
    last_activity: float = 0.0
    pid: int = 0
    runner_pid: int = 0
    question: str = ""
    progress_done: int = 0
    progress_total: int = 0
    step: str = ""
    reported: bool = False  # the voice session has told Tommy how it ended

    @property
    def job_dir(self) -> Path:
        return JOBS_DIR / self.id

    def save(self) -> None:
        with contextlib.suppress(Exception):
            self.job_dir.mkdir(parents=True, exist_ok=True)
            (self.job_dir / "status.json").write_text(json.dumps(asdict(self), indent=2),
                                                      encoding="utf-8")

    def brief(self) -> dict:
        now = time.time()
        elapsed = (self.finished or now) - self.started
        state = self.status
        # The runner's heartbeat only says the runner is alive; "quiet" is how long
        # since the agent itself wrote output or changed a file.
        quiet_s = now - max(self.last_activity, self.started)
        if state == "running" and quiet_s > STALL_AFTER_S:
            state = "stalled"
        percent = None
        if self.status == "done" and self.progress_total:
            percent = 100
        elif self.progress_total:
            percent = round(100 * self.progress_done / self.progress_total)
        return {"id": self.id, "task": self.task[:200], "status": self.status, "state": state,
                "minutes": round(elapsed / 60, 1), "summary": self.summary[:1500],
                "error": self.error[:300], "folder": self.folder, "project": self.project,
                "percent": percent, "step": self.step, "question": self.question,
                "quiet_seconds": int(quiet_s) if self.status in ACTIVE else 0}


ACTIVE = {"starting", "running"}
FINAL = {"done", "failed", "timed_out", "cancelled", "waiting"}
STALL_AFTER_S = 300.0  # no output or file change for this long = "stalled"


OnDone = Callable[[Job], Awaitable[None] | None]
_jobs: dict[str, Job] = {}
_tasks: dict[str, asyncio.Task] = {}


def resolve_executable(settings: DelegateSettings) -> str | None:
    """The engine's CLI: the configured path, then PATH, then known install spots."""
    if settings.command:
        found = shutil.which(settings.command)
        if found:
            return found
        return settings.command if Path(settings.command).exists() else None
    name = "codex" if settings.engine == "codex" else "claude"
    found = shutil.which(name)
    if found:
        return found
    if settings.engine == "codex":
        bundled = _codex_from_desktop_app()
        if bundled:
            return bundled
        for candidate in CODEX_FALLBACK_PATHS:
            if candidate.exists():
                return str(candidate)
    return None


def _codex_from_desktop_app() -> str | None:
    """The CLI bundled with the Codex desktop app (kept current by the app's own
    updates). Its folder name changes with every version and WindowsApps can't
    be listed, so ask Windows where the package lives."""
    if os.name != "nt":
        return None
    try:
        import subprocess

        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-AppxPackage OpenAI.Codex).InstallLocation"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except Exception:
        return None
    candidate = Path(out.splitlines()[0]) / "app" / "resources" / "codex.exe" if out else None
    return str(candidate) if candidate and candidate.exists() else None


def build_command(settings: DelegateSettings, executable: str,
                  result_file: str = "") -> list[str]:
    """The headless agent command line. The task itself goes in on stdin, so no
    shell quoting (cmd.exe on Windows) can mangle or inject into it."""
    if settings.engine == "codex":
        # Files only inside the job's folder, but the network is open so it can
        # research and download. "-" = read the task from stdin.
        cmd = [executable, "exec", "--skip-git-repo-check",
               "-c", 'approval_policy="never"', "--sandbox", "workspace-write",
               "-c", "sandbox_workspace_write.network_access=true"]
        if result_file:
            cmd += ["-o", result_file]
        # Tommy's own Codex default (gpt-6-sol) is refused on a ChatGPT-plan
        # login; gpt-6-astra is what ARGO's code-repair bridge already runs on.
        cmd += ["-m", settings.model or CODEX_DEFAULT_MODEL]
        return cmd + ["-"]
    cmd = [executable, "-p", "--output-format", "json",
           "--permission-mode", settings.permission_mode]
    if settings.model:
        cmd += ["--model", settings.model]
    return cmd


def parse_result(stdout: str) -> tuple[bool, str, float | None]:
    """(ok, summary, cost) from ``claude -p --output-format json`` output."""
    text = (stdout or "").strip()
    if not text:
        return False, "", None
    try:
        data = json.loads(text.splitlines()[-1] if not text.startswith("{") else text)
    except ValueError:
        return True, text[-1500:], None
    ok = not data.get("is_error") and data.get("subtype", "success") == "success"
    return ok, str(data.get("result") or ""), data.get("total_cost_usd")


def _read_job(job_id: str) -> Job | None:
    """A job as its runner last wrote it (None if there is no such job)."""
    try:
        data = json.loads((JOBS_DIR / job_id / "status.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    known = {f for f in Job.__dataclass_fields__}
    data.setdefault("reported", True)  # jobs from before this field existed are not news
    try:
        return Job(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return None


def _alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return True  # cannot tell; do not declare a live job dead


def _reconcile(job: Job) -> Job:
    """A job that says it is running but whose runner is gone is failed, not 'running forever'."""
    if job.status not in ACTIVE:
        return job
    last_sign = max(job.heartbeat, job.started)
    if time.time() - last_sign > 30 and not _alive(job.runner_pid):
        job.status = "failed"
        job.error = job.error or "The job's runner stopped before it finished."
        job.finished = time.time()
        job.save()
    return job


def _all_jobs(limit: int = 10) -> list[Job]:
    try:
        names = sorted((p.name for p in JOBS_DIR.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return []
    jobs = []
    for name in names[:max(limit, 1)]:
        job = _read_job(name)
        if job is not None:
            jobs.append(_reconcile(job))
    return jobs


def running_count() -> int:
    return sum(1 for j in _all_jobs(50) if j.status in ACTIVE)


def _spawn_runner(job: Job) -> None:
    flags = 0
    if os.name == "nt":  # own process group, no console, not tied to the voice worker
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    subprocess.Popen([sys.executable, "-m", "core.job_runner", str(job.job_dir)],
                     cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


async def start(task: str, folder: str = "", *, settings: DelegateSettings | None = None,
                on_done: OnDone | None = None, project: str = "") -> dict:
    """Start a background agent job. Returns at once; never raises.

    The job runs in its own detached process (core.job_runner), so it keeps going
    when the voice session ends. This worker only starts it and watches for the end."""
    settings = settings or load_settings()
    if not settings.enabled:
        return {"ok": False, "message": "Background agent jobs are switched off."}
    task = (task or "").strip()
    if not task:
        return {"ok": False, "message": "No task given."}
    if running_count() >= settings.max_running:
        return {"ok": False, "message": f"{running_count()} jobs are already running; "
                                        "wait for one to finish or cancel one."}
    executable = resolve_executable(settings)
    if not executable:
        return {"ok": False, "message": f"The {settings.engine} agent CLI is not installed or "
                                        "not on PATH."}
    workdir = Path(folder).expanduser() if folder else Path(settings.workspace)
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"ok": False, "message": f"Could not use folder {workdir}: {type(exc).__name__}"}

    job = Job(id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], task=task,
              folder=str(workdir), project=(project or "").strip()[:60])
    progress_name = f".argo_progress_{job.id}.json"
    result_file = str(job.job_dir / "last_message.txt")
    try:
        job.save()
        spec = {"cmd": build_command(settings, executable, result_file), "cwd": job.folder,
                "prompt": AGENT_BRIEF.format(task=job.task, progress_file=progress_name),
                "timeout_s": settings.timeout_s, "engine": settings.engine,
                "result_file": result_file if settings.engine == "codex" else "",
                "progress_file": str(workdir / progress_name)}
        (job.job_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        (job.job_dir / "task.txt").write_text(task, encoding="utf-8")
        _spawn_runner(job)
    except Exception as exc:
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        job.finished = time.time()
        job.save()
        return {"ok": False, "message": f"Could not start the job: {type(exc).__name__}"}
    _jobs[job.id] = job
    _tasks[job.id] = asyncio.create_task(_watch(job, on_done))
    logger.info("[Delegate] job %s started in %s: %r", job.id, workdir, task[:160])
    return {"ok": True, "job_id": job.id, "folder": str(workdir),
            "message": "Started in the background. I'll report back when it's done."}


async def _watch(job: Job, on_done: OnDone | None) -> None:
    """Wait for the detached runner to finish, then report. Cancelling this task
    cancels the job; the voice session simply ending does not."""
    try:
        while True:
            await asyncio.sleep(0.5)
            fresh = _read_job(job.id)
            if fresh is not None:
                job.__dict__.update(fresh.__dict__)
            _reconcile(job)
            if job.status in FINAL:
                break
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            (job.job_dir / "cancel").write_text("1", encoding="utf-8")
        for _ in range(20):
            await asyncio.sleep(0.25)
            fresh = _read_job(job.id)
            if fresh is not None:
                job.__dict__.update(fresh.__dict__)
            if job.status in FINAL:
                break
        raise
    logger.info("[Delegate] job %s %s", job.id, job.status)
    told = True
    if on_done is not None and job.status != "cancelled":
        with contextlib.suppress(Exception):
            maybe = on_done(job)
            if asyncio.iscoroutine(maybe):
                maybe = await maybe
            told = maybe is not False  # a callback returns False when it could not speak
    if told:
        job.reported = True
        with contextlib.suppress(Exception):
            from core.job_runner import update_status
            update_status(job.job_dir, reported=True)


def adopt(on_done: OnDone | None = None) -> int:
    """Watch jobs a previous voice session started and that are still running,
    so their completion is reported by this session. Returns how many."""
    count = 0
    for job in _all_jobs(30):
        task = _tasks.get(job.id)
        unannounced = (job.status in FINAL and job.status != "cancelled" and not job.reported
                       and time.time() - (job.finished or 0) < 24 * 3600)
        if (job.status in ACTIVE or unannounced) and (task is None or task.done()):
            _jobs[job.id] = job
            _tasks[job.id] = asyncio.create_task(_watch(job, on_done))
            count += 1
    return count


def status(job_id: str = "", limit: int = 10) -> dict:
    """One job, or the newest jobs (from every session, newest first)."""
    if job_id:
        job_id = resolve_id(job_id)
        job = _read_job(job_id)
        return {"ok": bool(job), "job": _reconcile(job).brief() if job else None}
    jobs = _all_jobs(limit)
    return {"ok": True, "running": sum(1 for j in jobs if j.status in ACTIVE),
            "jobs": [j.brief() for j in jobs]}


def resolve_id(text: str) -> str:
    """A full job id, or the last few characters of one ("6256fa"), to the full id."""
    text = (text or "").strip()
    if not text or (JOBS_DIR / text).is_dir():
        return text
    try:
        matches = [p.name for p in JOBS_DIR.iterdir() if p.is_dir() and p.name.endswith(text)]
    except OSError:
        return text
    return matches[0] if len(matches) == 1 else text


async def retry(job_id: str, detail: str = "", *, on_done: OnDone | None = None,
                settings: DelegateSettings | None = None) -> dict:
    """Run a job again (stopping it first if it is still going), optionally with
    more detail from Tommy. The old job is kept as the record."""
    job_id = resolve_id(job_id)
    job = _read_job(job_id)
    if job is None:
        return {"ok": False, "message": "No job with that id."}
    if job.status in ACTIVE:
        cancel(job_id)
        for _ in range(24):
            await asyncio.sleep(0.25)
            fresh = _read_job(job_id)
            if fresh is None or fresh.status not in ACTIVE:
                break
    try:
        task = (job.job_dir / "task.txt").read_text(encoding="utf-8")
    except OSError:
        task = job.task
    if (detail or "").strip():
        task += "\n\nMore detail from Tommy for this retry: " + detail.strip()
    result = await start(task, job.folder, settings=settings, on_done=on_done, project=job.project)
    if result.get("ok"):
        result["retry_of"] = job_id
    return result


def cancel(job_id: str) -> dict:
    job_id = resolve_id(job_id)
    task = _tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        return {"ok": True, "message": "Cancelled."}
    job = _read_job(job_id)
    if job is not None and job.status in ACTIVE:  # started by an earlier session
        with contextlib.suppress(Exception):
            (job.job_dir / "cancel").write_text("1", encoding="utf-8")
        return {"ok": True, "message": "Cancelling."}
    return {"ok": False, "message": "No running job with that id."}
