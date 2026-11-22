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
not be verified. Never print or copy secrets from config.json or .env files."""


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

    @property
    def job_dir(self) -> Path:
        return JOBS_DIR / self.id

    def save(self) -> None:
        with contextlib.suppress(Exception):
            self.job_dir.mkdir(parents=True, exist_ok=True)
            (self.job_dir / "status.json").write_text(json.dumps(asdict(self), indent=2),
                                                      encoding="utf-8")

    def brief(self) -> dict:
        elapsed = (self.finished or time.time()) - self.started
        return {"id": self.id, "task": self.task[:200], "status": self.status,
                "minutes": round(elapsed / 60, 1), "summary": self.summary[:1500],
                "error": self.error[:300], "folder": self.folder}


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


def running_count() -> int:
    return sum(1 for j in _jobs.values() if j.status in {"starting", "running"})


async def start(task: str, folder: str = "", *, settings: DelegateSettings | None = None,
                on_done: OnDone | None = None) -> dict:
    """Start a background agent job. Returns at once; never raises."""
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
              folder=str(workdir))
    _jobs[job.id] = job
    job.save()
    with contextlib.suppress(Exception):
        (job.job_dir / "task.txt").write_text(task, encoding="utf-8")
    _tasks[job.id] = asyncio.create_task(_run(job, settings, executable, on_done))
    logger.info("[Delegate] job %s started in %s: %r", job.id, workdir, task[:160])
    return {"ok": True, "job_id": job.id, "folder": str(workdir),
            "message": "Started in the background. I'll report back when it's done."}


async def _run(job: Job, settings: DelegateSettings, executable: str,
               on_done: OnDone | None) -> None:
    prompt = AGENT_BRIEF.format(task=job.task)
    process = None
    try:
        result_file = str(job.job_dir / "last_message.txt")
        process = await asyncio.create_subprocess_exec(
            *build_command(settings, executable, result_file), cwd=job.folder,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        job.status = "running"
        job.save()
        stdout, stderr = await asyncio.wait_for(process.communicate(prompt.encode("utf-8")),
                                                timeout=settings.timeout_s)
        out, err = stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")
        with contextlib.suppress(Exception):
            (job.job_dir / "result.json").write_text(out, encoding="utf-8")
            if err.strip():
                (job.job_dir / "stderr.txt").write_text(err, encoding="utf-8")
        if settings.engine == "codex":
            try:
                summary = Path(result_file).read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                summary = ""
            ok, cost = bool(summary), None
        else:
            ok, summary, cost = parse_result(out)
        job.summary, job.cost_usd = summary, cost
        job.status = "done" if ok and process.returncode == 0 else "failed"
        if job.status == "failed":
            job.error = (err.strip() or summary or f"exit code {process.returncode}")[-500:]
    except asyncio.TimeoutError:
        job.status, job.error = "timed_out", f"stopped after {int(settings.timeout_s)}s"
        await _stop(process)
    except asyncio.CancelledError:
        job.status = "cancelled"
        await _stop(process)
        raise
    except Exception as exc:
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        await _stop(process)
    finally:
        job.finished = time.time()
        job.save()
        logger.info("[Delegate] job %s %s", job.id, job.status)
        if on_done is not None and job.status != "cancelled":
            with contextlib.suppress(Exception):
                maybe = on_done(job)
                if asyncio.iscoroutine(maybe):
                    await maybe


async def _stop(process) -> None:
    """Kill the agent process and reap it, so no pipes outlive the job."""
    if process is None or process.returncode is not None:
        return
    with contextlib.suppress(Exception):
        process.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=5)


def status(job_id: str = "") -> dict:
    """One job, or every job from this run (newest first)."""
    if job_id:
        job = _jobs.get(job_id)
        return {"ok": bool(job), "job": job.brief() if job else None}
    jobs = sorted(_jobs.values(), key=lambda j: j.started, reverse=True)
    return {"ok": True, "running": running_count(), "jobs": [j.brief() for j in jobs[:10]]}


def cancel(job_id: str) -> dict:
    task = _tasks.get(job_id)
    if task is None or task.done():
        return {"ok": False, "message": "No running job with that id."}
    task.cancel()
    return {"ok": True, "message": "Cancelled."}
