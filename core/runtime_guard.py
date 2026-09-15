"""One ARGO at a time, running out of the right interpreter.

Two failures this prevents, both of which have actually happened here.

A second realtime worker registering as "argo-realtime" is the worse one:
LiveKit hands a job to whichever worker it likes, so a stray second worker
turns "can ARGO hear me" into a coin flip, and the log looks identical either
way - a registration line and then silence.

The other is a process running outside the venv. That one needs care, because
of how Windows venvs actually work: I:\\argo\\.venv\\Scripts\\python.exe is
venvlauncher.exe, a stub that re-executes the BASE interpreter and waits. So a
correctly-launched ARGO reports

    sys.executable      C:\\...\\Python311\\python.exe     <- base, looks wrong
    sys.prefix          I:\\argo\\.venv                    <- venv, is right

Checking sys.executable would therefore fail the one process that is actually
fine. sys.prefix is the thing that decides which site-packages get imported,
so sys.prefix is what gets checked here.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("ARGO.RuntimeGuard")

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VENV = ROOT / ".venv"
LOCK_DIR = ROOT / "runtime" / "locks"

# Imported, not just present on disk: a package that is installed but broken
# fails here rather than three seconds into a voice session.
REQUIRED_IMPORTS = {
    "main": ("openai",),
    "realtime-worker": ("livekit.agents", "livekit.plugins.openai", "openai"),
}


class RuntimeProblem(RuntimeError):
    """The interpreter or the environment is wrong, and voice would fail."""


def ensure_openai_key() -> bool:
    """Make OPENAI_API_KEY available to this process, wherever it is stored.

    Order: the process environment, then .env, then the Windows User
    environment. That last one is where it actually lives on this machine,
    and it is the one a process started from a stale parent misses.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return True

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        if os.environ.get("OPENAI_API_KEY"):
            logger.info("[Runtime] OPENAI_API_KEY resolved from .env")
            return True
    except Exception:
        pass

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "OPENAI_API_KEY")
        if value:
            os.environ["OPENAI_API_KEY"] = value
            logger.info("[Runtime] OPENAI_API_KEY resolved from the Windows "
                        "User environment (not inherited from the parent process)")
            return True
    except Exception:
        pass

    return False


def livekit_port() -> int:
    try:
        from urllib.parse import urlparse

        from core.livekit_config import get_livekit_realtime_config

        return int(urlparse(get_livekit_realtime_config().url).port or 7880)
    except Exception:
        return 7880


# Injection points so the identification logic is testable against fake
# processes. Tests replace these; production never does.
_process_iter = None      # callable returning an iterable of psutil-like processes
_kill = None              # callable(pid) that stops a process


def _processes():
    if _process_iter is not None:
        return _process_iter()
    import psutil

    return psutil.process_iter()


def _stop_process(pid: int) -> None:
    if _kill is not None:
        _kill(pid)
        return
    import psutil

    psutil.Process(pid).kill()


def _argo_evidence(proc) -> dict:
    """What ties this process to ARGO specifically - not to LiveKit, not to
    Python. Each item is something an unrelated client would not have."""
    root = str(ROOT).lower()
    evidence = {"cwd_is_argo": False, "cmdline_is_argo": False, "argo_venv_mapped": False}
    try:
        evidence["cwd_is_argo"] = (proc.cwd() or "").lower().rstrip("\\/") == root.rstrip("\\/")
    except Exception:
        pass
    try:
        cmd = " ".join(proc.cmdline() or []).lower()
        evidence["cmdline_is_argo"] = root in cmd or "livekit_realtime_agent" in cmd
    except Exception:
        pass
    try:
        venv = str(ROOT / ".venv").lower()
        evidence["argo_venv_mapped"] = any(
            (m.path or "").lower().startswith(venv) for m in proc.memory_maps()
        )
    except Exception:
        pass
    evidence["confirmed"] = bool(
        evidence["cwd_is_argo"] and (evidence["cmdline_is_argo"] or evidence["argo_venv_mapped"])
    )
    return evidence


def zombie_workers() -> list[dict]:
    """Parentless python processes still connected to the LiveKit port.

    Each entry says whether it is CONFIRMED as ARGO's own executor child, by
    evidence that belongs to ARGO and to nothing else on this machine. Only
    confirmed entries can ever be stopped, and only by clean_orphans(confirm=True).
    Eight of these, from a day of force-kills, gave ARGO 2 sessions in 10.
    """
    try:
        import psutil
    except Exception:
        return []

    port = livekit_port()
    found = []
    for proc in _processes():
        try:
            name = (proc.name() or "").lower()
            if "python" not in name:
                continue
            pid = proc.pid
            if pid == os.getpid():
                continue
            ppid = proc.ppid()
            if ppid and ppid != 0 and psutil.pid_exists(ppid):
                continue
            connected = any(
                c.status == psutil.CONN_ESTABLISHED and c.raddr and c.raddr.port == port
                for c in proc.net_connections(kind="tcp")
            )
            if not connected:
                continue
            entry = {
                "pid": pid,
                "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.create_time())),
                "create_time": proc.create_time(),
                "cmdline": " ".join(proc.cmdline() or [])[:90],
            }
            entry.update(_argo_evidence(proc))
            found.append(entry)
        except Exception:
            continue
    return found


def describe_orphans(orphans: list[dict]) -> str:
    lines = []
    for z in orphans:
        tag = "ARGO executor (confirmed)" if z.get("confirmed") else "NOT confirmed as ARGO - left alone"
        proof = ", ".join(k for k in ("cwd_is_argo", "cmdline_is_argo", "argo_venv_mapped") if z.get(k))
        lines.append(f"pid {z['pid']}  started {z['started']}  {tag}"
                     + (f"  [{proof}]" if proof else "") + f"\n        {z['cmdline']}")
    return "\n      ".join(lines)


def clean_orphans(*, confirm: bool = False) -> dict:
    """Stop CONFIRMED ARGO executor orphans. Refuses unless confirm=True.

    Anything merely suspected - a parentless python talking to LiveKit that
    cannot be tied to I:\argo - is reported and left running. Identity and
    start time are re-checked immediately before each kill.
    """
    orphans = zombie_workers()
    result = {"stopped": [], "left_alone": [z for z in orphans if not z.get("confirmed")],
              "confirmed": [z for z in orphans if z.get("confirmed")]}
    if not confirm:
        result["refused"] = "clean_orphans() requires confirm=True; nothing was stopped"
        logger.warning("[Orphans] %s", result["refused"])
        return result

    import psutil

    for z in result["confirmed"]:
        try:
            proc = psutil.Process(z["pid"])
            if abs(proc.create_time() - z["create_time"]) > 1.0:
                z["skipped"] = "pid was recycled since it was identified"
                continue
            if not _argo_evidence(proc).get("confirmed"):
                z["skipped"] = "no longer identifiable as ARGO at kill time"
                continue
            _stop_process(z["pid"])
            result["stopped"].append(z)
            logger.warning("[Orphans] stopped confirmed ARGO executor orphan pid %s (started %s)",
                           z["pid"], z["started"])
        except Exception as exc:
            z["skipped"] = f"{type(exc).__name__}"
    return result


def venv_report() -> dict:
    """Where this interpreter is actually importing from."""
    prefix = Path(sys.prefix).resolve()
    try:
        in_venv = prefix == EXPECTED_VENV.resolve()
    except Exception:
        in_venv = False
    return {
        "executable": sys.executable,
        "base_executable": getattr(sys, "_base_executable", sys.executable),
        "prefix": str(prefix),
        "expected_prefix": str(EXPECTED_VENV),
        "in_expected_venv": in_venv,
        # True for a normally-launched process on Windows. Recorded because it
        # looks alarming in a process list and is not.
        "launched_via_venv_stub": Path(sys.executable).resolve()
        != Path(getattr(sys, "_base_executable", sys.executable)).resolve(),
    }


def check_imports(role: str) -> dict[str, str]:
    """Import what this role needs. Returns {module: error} for failures."""
    import importlib

    broken: dict[str, str] = {}
    for module in REQUIRED_IMPORTS.get(role, ()):
        try:
            importlib.import_module(module)
        except Exception as exc:
            broken[module] = f"{type(exc).__name__}: {exc}"
    return broken


def verify_runtime(role: str, *, fatal: bool = True) -> dict:
    """Say loudly, at startup, whether this process can do its job.

    A worker that cannot import livekit.plugins still registers with LiveKit
    and still takes jobs - it just cannot run them. Better to refuse to start.
    """
    report = venv_report()
    report["role"] = role
    report["broken_imports"] = check_imports(role)

    # Checked at STARTUP, not at first use. Missing it used to surface as a
    # job that died after being accepted, which is indistinguishable from the
    # outside from a job that was never delivered.
    report["openai_key"] = ensure_openai_key()

    problems = []
    if role == "realtime-worker":
        zombies = zombie_workers()
        report["zombie_workers"] = zombies
        if zombies:
            confirmed = sum(1 for z in zombies if z.get("confirmed"))
            problems.append(
                f"{len(zombies)} parentless python process(es) are connected to LiveKit "
                f"({confirmed} confirmed as ARGO executor orphans) and would compete for "
                f"this worker's jobs:\n      {describe_orphans(zombies)}\n"
                "    Nothing has been stopped. Confirmed ARGO orphans can be removed with\n"
                "      scripts\\start_argo_stack.ps1 -CleanOrphans\n"
                "    Anything not confirmed is not ARGO's to stop - close it yourself."
            )
    if role == "realtime-worker" and not report["openai_key"]:
        problems.append(
            "OPENAI_API_KEY is not set anywhere this process can see it "
            "(process env, .env, or the Windows User environment). The worker "
            "would register, accept a job, and then fail inside it - which "
            "looks exactly like never receiving the job at all"
        )
    if not report["in_expected_venv"]:
        problems.append(
            f"running with sys.prefix={report['prefix']} but ARGO's packages "
            f"live in {report['expected_prefix']}"
        )
    for module, error in report["broken_imports"].items():
        problems.append(f"cannot import {module} ({error})")
    report["problems"] = problems

    logger.info(
        "[Runtime] role=%s prefix=%s in_venv=%s via_stub=%s imports_ok=%s",
        role, report["prefix"], report["in_expected_venv"],
        report["launched_via_venv_stub"], not report["broken_imports"],
    )

    if problems:
        message = (
            f"ARGO {role} cannot run in this environment:\n  - "
            + "\n  - ".join(problems)
            + f"\n\nStart it with: {EXPECTED_VENV / 'Scripts' / 'python.exe'}"
        )
        logger.error("[Runtime] %s", message)
        if fatal:
            raise RuntimeProblem(message)
    return report


# ---------------------------------------------------------------------------
# One at a time
# ---------------------------------------------------------------------------

def _process_is_alive(pid: int, started: float | None) -> bool:
    """Is that PID still the process that wrote the lock?

    Windows recycles PIDs, so a bare "does this PID exist" check will
    eventually treat an unrelated process as a live ARGO and refuse to start.
    The recorded start time is what makes the answer trustworthy.
    """
    try:
        import psutil

        proc = psutil.Process(pid)
        if started is not None and abs(proc.create_time() - started) > 1.0:
            return False
        return proc.is_running()
    except Exception:
        return False


class SingleInstance:
    """A PID lock that refuses a second copy of one role.

    Used as a context manager. Releasing is best effort; a stale lock left by
    a killed process is detected by liveness, not by trusting the file.
    """

    def __init__(self, role: str, *, takeover: bool = False) -> None:
        self.role = role
        self.takeover = takeover
        self.path = LOCK_DIR / f"{role}.lock"
        self.holder: dict | None = None
        self._held = False

    def _read(self) -> dict | None:
        try:
            import json

            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def acquire(self) -> "SingleInstance":
        import json
        import time

        if self._held:
            return self          # re-acquiring the same lock object is a no-op

        LOCK_DIR.mkdir(parents=True, exist_ok=True)
        existing = self._read()
        if existing:
            pid = int(existing.get("pid", -1))
            started = existing.get("started")
            # Deliberately NOT exempting our own pid. The threat being
            # guarded is a second holder of this ROLE, and exempting the pid
            # made the guard pass its own test for the wrong reason - a
            # second SingleInstance sailed straight through. A process that
            # legitimately re-takes its own lock holds the same object, which
            # is handled by the _held short-circuit above.
            if _process_is_alive(pid, started):
                self.holder = existing
                if not self.takeover:
                    raise RuntimeProblem(
                        f"another ARGO {self.role} is already running (pid {pid}, "
                        f"started {existing.get('started_human', '?')}).\n"
                        f"Two {self.role} processes is how ARGO ends up answering "
                        f"twice, or not at all.\n"
                        f"Stop that one first, or delete {self.path} if you are "
                        f"certain it is dead."
                    )
                logger.warning("[Lock] taking over %s from pid %s", self.role, pid)

        try:
            import psutil

            started = psutil.Process().create_time()
        except Exception:
            started = time.time()

        self.path.write_text(json.dumps({
            "role": self.role,
            "pid": os.getpid(),
            "started": started,
            "started_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
            "executable": sys.executable,
            "prefix": sys.prefix,
        }, indent=2), encoding="utf-8")
        self._held = True
        logger.info("[Lock] holding %s (pid %s)", self.role, os.getpid())
        return self

    def release(self) -> None:
        existing = self._read()
        if existing and int(existing.get("pid", -1)) == os.getpid():
            try:
                self.path.unlink()
            except Exception:
                logger.debug("[Lock] could not remove %s", self.path, exc_info=True)
        self._held = False

    def __enter__(self) -> "SingleInstance":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def _cli(argv: list[str]) -> int:
    """python -m core.runtime_guard --report | --clean

    --report never stops anything and exits 2 if any orphan is suspected.
    --clean stops only CONFIRMED ARGO executor orphans and prints every
    decision, including what it left alone and why.
    """
    import json as _json

    if "--clean" in argv:
        result = clean_orphans(confirm=True)
        for z in result["stopped"]:
            print(f"  stopped  pid {z['pid']}  started {z['started']}  (confirmed ARGO executor)")
        for z in result["confirmed"]:
            if z.get("skipped"):
                print(f"  skipped  pid {z['pid']}  {z['skipped']}")
        for z in result["left_alone"]:
            print(f"  left     pid {z['pid']}  started {z['started']}  not confirmed as ARGO: {z['cmdline']}")
        if not result["stopped"] and not result["left_alone"] and not result["confirmed"]:
            print("  no orphans found")
        return 0 if not result["left_alone"] else 2

    orphans = zombie_workers()
    if "--json" in argv:
        print(_json.dumps(orphans, indent=2, default=str))
    elif orphans:
        print("  suspected orphans connected to LiveKit (nothing stopped):")
        print("      " + describe_orphans(orphans))
    else:
        print("  no orphans")
    return 2 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
