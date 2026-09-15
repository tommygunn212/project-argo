"""Orphan handling: report by default, never kill by default, and when asked
to clean, identify ARGO's own executor children by ARGO-specific evidence.

The previous sweep stopped every parentless python.exe with a connection to
the LiveKit port. That is the right shape for ARGO's zombies and the wrong
shape for anything else Tommy runs against the same server. It is replaced.

  suspected  python, parent gone, established connection to the LiveKit port
  confirmed  suspected AND cwd is I:\\argo AND (the command line references
             I:\\argo or livekit_realtime_agent, OR the process has mapped a
             file from I:\\argo\\.venv). Both halves are ARGO's, not LiveKit's.

verify_runtime() refuses to start next to ANY suspected orphan and lists them
with their evidence. Nothing is stopped unless clean_orphans(confirm=True) is
called, and that stops only confirmed ones, re-checking identity and start
time right before each kill so a recycled pid is never hit.
"""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "core" / "runtime_guard.py"
s = io.open(p, encoding="utf-8").read()

start = s.index("def zombie_workers() -> list[dict]:")
end = s.index("def venv_report() -> dict:")
new_block = '''# Injection points so the identification logic is testable against fake
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
        evidence["cwd_is_argo"] = (proc.cwd() or "").lower().rstrip("\\\\/") == root.rstrip("\\\\/")
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
                     + (f"  [{proof}]" if proof else "") + f"\\n        {z['cmdline']}")
    return "\\n      ".join(lines)


def clean_orphans(*, confirm: bool = False) -> dict:
    """Stop CONFIRMED ARGO executor orphans. Refuses unless confirm=True.

    Anything merely suspected - a parentless python talking to LiveKit that
    cannot be tied to I:\\argo - is reported and left running. Identity and
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


'''
s = s[:start] + new_block + s[end:]

# --- verify_runtime: refuse on ANY suspected orphan, list evidence, never kill --
old = s[s.index('    if role == "realtime-worker":\n        zombies = zombie_workers()'):s.index('    if role == "realtime-worker" and not report["openai_key"]:')]
new = '''    if role == "realtime-worker":
        zombies = zombie_workers()
        report["zombie_workers"] = zombies
        if zombies:
            confirmed = sum(1 for z in zombies if z.get("confirmed"))
            problems.append(
                f"{len(zombies)} parentless python process(es) are connected to LiveKit "
                f"({confirmed} confirmed as ARGO executor orphans) and would compete for "
                f"this worker's jobs:\\n      {describe_orphans(zombies)}\\n"
                "    Nothing has been stopped. Confirmed ARGO orphans can be removed with\\n"
                "      scripts\\\\start_argo_stack.ps1 -CleanOrphans\\n"
                "    Anything not confirmed is not ARGO's to stop - close it yourself."
            )
'''
s = s.replace(old, new, 1)

# --- CLI for the launcher: --report (read-only) and --clean (explicit) --------
s += '''

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
'''

io.open(p, "w", encoding="utf-8", newline="").write(s)
import ast; ast.parse(s)
for needle in ("def clean_orphans(", "def _argo_evidence(", "def describe_orphans(", "confirm: bool = False",
               "_process_iter = None", "def _cli(", "Nothing has been stopped"):
    print(f"  {'OK  ' if needle in s else 'MISS'} {needle}")
