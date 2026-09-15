"""Never start ARGO into a zombie worker pool again.

What the lifecycle test proved: eight orphaned executor processes, the oldest
from the previous afternoon, each still holding a LiveKit worker registration
it could never service. LiveKit shared jobs across all nine "argo-realtime"
workers and the real one got 2 in 10. Restarting the server changed nothing -
the orphans reconnected in the same millisecond.

They were created by force-stopping a worker (dev mode runs the actual worker
as a child; Stop-Process kills only the parent). So, three things:

  1. runtime_guard.zombie_workers() finds them: parentless python processes
     with an established connection to the LiveKit port.
  2. verify_runtime("realtime-worker") REFUSES to start while any exist and
     prints the list. Starting anyway is the silent lottery.
  3. The launcher drains the previous worker through the drain file, then
     removes any zombies it can prove are parentless and connected to
     LiveKit - printing each pid - because nothing else can drain those.

Nothing here ever prints an environment variable or a key.
"""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label, marker):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if marker in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label} (x{s.count(old)})"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

# --- guard: detection ----------------------------------------------------
patch("core/runtime_guard.py",
'''def venv_report() -> dict:''',
'''def livekit_port() -> int:
    try:
        from urllib.parse import urlparse

        from core.livekit_config import get_livekit_realtime_config

        return int(urlparse(get_livekit_realtime_config().url).port or 7880)
    except Exception:
        return 7880


def zombie_workers() -> list[dict]:
    """Orphaned python processes still registered with LiveKit.

    A worker that was force-stopped leaves its executor child alive: no
    parent, no console, no drain hook - and a live worker registration that
    LiveKit keeps handing jobs to. Eight of them made ARGO deaf four times
    out of five. Detected as: python.exe, parent process gone, established
    connection to the LiveKit port, not the current process.
    """
    try:
        import psutil
    except Exception:
        return []

    port = livekit_port()
    server_pids = set()
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
            server_pids.add(conn.pid)

    found = []
    for proc in psutil.process_iter(["pid", "name", "ppid", "create_time", "cmdline"]):
        try:
            info = proc.info
            if "python" not in (info["name"] or "").lower():
                continue
            if info["pid"] == os.getpid() or info["pid"] in server_pids:
                continue
            ppid = info["ppid"]
            parent_alive = ppid and psutil.pid_exists(ppid) and ppid != 0
            if parent_alive:
                continue
            connected = any(
                c.status == psutil.CONN_ESTABLISHED and c.raddr and c.raddr.port == port
                for c in proc.net_connections(kind="tcp")
            )
            if not connected:
                continue
            cmd = " ".join(info["cmdline"] or [])[:90]
            found.append({
                "pid": info["pid"],
                "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info["create_time"])),
                "cmdline": cmd,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
    return found


def venv_report() -> dict:''',
"guard: zombie_workers()", marker="def zombie_workers(")

patch("core/runtime_guard.py",
'''import logging
import os
import sys
from pathlib import Path''',
'''import logging
import os
import sys
import time
from pathlib import Path''',
"guard: import time", marker="import time\nfrom pathlib import Path")

# --- guard: refuse to start into a pool ---------------------------------------
patch("core/runtime_guard.py",
'''    problems = []
    if role == "realtime-worker" and not report["openai_key"]:''',
'''    problems = []
    if role == "realtime-worker":
        zombies = zombie_workers()
        report["zombie_workers"] = zombies
        if zombies:
            listing = "\\n      ".join(
                f"pid {z['pid']}  started {z['started']}  {z['cmdline']}" for z in zombies
            )
            problems.append(
                f"{len(zombies)} orphaned worker process(es) are still registered with "
                f"LiveKit and would take jobs this worker should get:\\n      {listing}\\n"
                "    They have no parent and no drain hook. Stop them, or start via "
                "scripts\\\\start_argo_stack.ps1 which removes them and says so"
            )
    if role == "realtime-worker" and not report["openai_key"]:''',
"guard: refuse on zombies", marker='report["zombie_workers"] = zombies')

print("\n".join(log))
s = io.open(ROOT / "core" / "runtime_guard.py", encoding="utf-8").read()
import ast; ast.parse(s)
print("runtime_guard parses; zombie_workers:", "def zombie_workers(" in s, "| refusal:", "zombie_workers = zombies" in s.replace('report["zombie_workers"]', 'zombie_workers'))
