"""Is dispatch deterministic? Ten times in a row, with receipts.

    .venv\\Scripts\\python tools\\lifecycle_test.py            # 10 dispatches
    .venv\\Scripts\\python tools\\lifecycle_test.py -n 25

The test owns the worker for its whole life: starts it, reads every line it
prints, drains it gracefully at the end, and refuses to force-kill anything.
For each dispatch it records, from independent sources:

  server    the dispatch id it created, the placeholder participant LiveKit
            adds (which proves NOTHING), room state at failure
  worker    the framework's own "received job request" line for this room
  ARGO      job_received / model_built / session_start / session_end events
            written by the session itself, each stamped with the real pid

A dispatch PASSES only when session_start arrives. A placeholder with no
session is the exact shape of "dashboard says LIVE and nothing answers", and
is reported as a failure with the worker log window and server state.

Nothing key-shaped reaches any artifact: everything written goes through
redact(), which also strips the LiveKit API secret literally.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOCK = ROOT / "runtime" / "locks" / "realtime-worker.lock"
DRAIN = ROOT / "runtime" / "locks" / "realtime-worker.drain"
OUT_ROOT = ROOT / "runtime" / "voice_tests"
SERVER_LOG_CANDIDATES = [ROOT / "runtime" / "logs" / "livekit-server.log",
                         ROOT / "livekit-server" / "livekit-server.log"]
AGENT_KIND = 4


# --- redaction -----------------------------------------------------------

_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "***jwt***"),
    (re.compile(r"(?i)(api[_-]?key|api[_-]?secret|authorization|token)(\s*[=:]\s*)([^\s,;\"'}\]]{8,})"),
     r"\1\2***"),
]
_LITERALS: list[str] = []


def redact(text: str) -> str:
    if not text:
        return text
    for literal in _LITERALS:
        if literal and len(literal) >= 8:
            text = text.replace(literal, "***")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# --- the worker under test -----------------------------------------------

class Worker:
    """One realtime worker, owned end to end. Never force-killed."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self.lines: list[tuple[float, str]] = []
        self._lock = threading.Lock()
        self.stub_pid: int | None = None
        self.real_pid: int | None = None
        self.worker_id: str = ""

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        with self.log_path.open("a", encoding="utf-8") as sink:
            for raw in self.proc.stdout:
                line = redact(raw.rstrip("\r\n"))
                stamp = time.time()
                with self._lock:
                    self.lines.append((stamp, line))
                sink.write(f"{datetime.fromtimestamp(stamp).isoformat(timespec='milliseconds')} {line}\n")
                sink.flush()

    def start(self, timeout: float = 40.0) -> dict:
        from core.runtime_guard import ensure_openai_key

        ensure_openai_key()   # the child inherits it; the value is never printed
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"

        self.proc = subprocess.Popen(
            [str(PY), "-u", str(ROOT / "livekit_realtime_agent.py"), "start"],
            cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.stub_pid = self.proc.pid
        threading.Thread(target=self._pump, name="worker-stdout", daemon=True).start()

        started = time.time()
        while time.time() - started < timeout:
            if self.proc.poll() is not None:
                return {"ok": False, "error": f"worker exited early with code {self.proc.returncode}",
                        "tail": self.tail(30)}
            for _, line in self.snapshot():
                if "registered worker" in line:
                    match = re.search(r'"id":\s*"(AW_[A-Za-z0-9]+)"', line)
                    if match:
                        self.worker_id = match.group(1)
            if self.worker_id:
                break
            time.sleep(0.3)
        if not self.worker_id:
            return {"ok": False, "error": "worker never registered", "tail": self.tail(30)}

        # The lock records the pid of the REAL interpreter, not the venv
        # launcher stub that Popen returned.
        for _ in range(20):
            try:
                self.real_pid = int(json.loads(LOCK.read_text(encoding="utf-8"))["pid"])
                break
            except Exception:
                time.sleep(0.25)
        return {"ok": True, "worker_id": self.worker_id, "stub_pid": self.stub_pid,
                "real_pid": self.real_pid, "registered_after_s": round(time.time() - started, 2)}

    def snapshot(self) -> list[tuple[float, str]]:
        with self._lock:
            return list(self.lines)

    def tail(self, n: int) -> list[str]:
        return [line for _, line in self.snapshot()[-n:]]

    def window(self, since: float, until: float | None = None) -> list[str]:
        until = until or time.time() + 1
        return [f"{datetime.fromtimestamp(t).strftime('%H:%M:%S.%f')[:-3]} {line}"
                for t, line in self.snapshot() if since - 0.5 <= t <= until]

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def drain(self, timeout: float = 45.0) -> dict:
        """Ask the worker to shut itself down the framework's way."""
        if not self.alive():
            return {"ok": True, "note": "already exited", "exit_code": self.proc.returncode if self.proc else None}
        DRAIN.parent.mkdir(parents=True, exist_ok=True)
        DRAIN.write_text("drain\n", encoding="utf-8")
        started = time.time()
        while time.time() - started < timeout:
            if not self.alive():
                return {"ok": True, "exit_code": self.proc.returncode,
                        "drained_in_s": round(time.time() - started, 2),
                        "drain_logged": any("drain" in l.lower() for l in self.tail(40))}
            time.sleep(0.3)
        return {"ok": False, "error": f"worker did not exit within {timeout:.0f}s of a drain request",
                "stub_pid": self.stub_pid, "real_pid": self.real_pid, "tail": self.tail(30)}


# --- LiveKit side ----------------------------------------------------------

def _api():
    from livekit import api

    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    return api, api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret), cfg


async def server_state(room: str) -> dict:
    api, lk, _ = _api()
    try:
        rooms = [r.name for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms]
        parts, dispatches = [], []
        if room in rooms:
            parts = [{"identity": p.identity, "kind": int(p.kind), "state": int(getattr(p, "state", -1))}
                     for p in (await lk.room.list_participants(api.ListParticipantsRequest(room=room))).participants]
            try:
                dispatches = [{"id": d.id, "agent": d.agent_name}
                              for d in await lk.agent_dispatch.list_dispatch(room)]
            except Exception as exc:
                dispatches = [{"error": redact(f"{type(exc).__name__}: {exc}")}]
        return {"rooms": rooms, "participants": parts, "dispatches": dispatches}
    finally:
        await lk.aclose()


async def cleanup_rooms(prefix: str) -> list[str]:
    api, lk, _ = _api()
    removed = []
    try:
        for r in (await lk.room.list_rooms(api.ListRoomsRequest())).rooms:
            if r.name.startswith(prefix):
                await lk.room.delete_room(api.DeleteRoomRequest(room=r.name))
                removed.append(r.name)
    finally:
        await lk.aclose()
    return removed


def server_log_tail(n: int = 40) -> list[str]:
    for path in SERVER_LOG_CANDIDATES:
        if path.exists():
            try:
                return [redact(l) for l in path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]]
            except Exception:
                pass
    return ["(livekit-server output is not being captured to a file; server STATE above is from its API)"]


# --- one dispatch ------------------------------------------------------------

async def run_one(index: int, room: str, worker: Worker, timeout: float, settle: float) -> dict:
    from core import voice_events

    api, lk, cfg = _api()
    result = {"index": index, "room": room, "verdict": "", "classification": "",
              "dispatch_id": "", "t": {}, "worker_pid_for_job": None,
              "job_id": "", "framework_ack": False, "model": "", "model_error": "",
              "session_end": None}
    offset = voice_events.tail_position()
    log_from = time.time()
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=90))
        t0 = time.time()
        created = await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(room=room, agent_name=cfg.agent_name, metadata="lifecycle-test"))
        result["dispatch_id"] = created.id
        result["t"]["dispatch"] = 0.0

        seen = {"placeholder": None, "job_received": None, "model": None, "session_start": None}
        while time.time() - t0 < timeout:
            if not worker.alive():
                result["classification"] = "worker_died"
                break
            now = time.time() - t0

            if seen["placeholder"] is None:
                parts = (await lk.room.list_participants(api.ListParticipantsRequest(room=room))).participants
                if any(p.kind == AGENT_KIND for p in parts):
                    seen["placeholder"] = round(now, 2)

            for ev in voice_events.read_since(offset):
                if ev.get("room") not in (room, "", None) and ev.get("kind") in ("job_received", "session_end"):
                    continue
                kind = ev.get("kind")
                if kind == "job_received" and ev.get("room") == room and seen["job_received"] is None:
                    seen["job_received"] = round(now, 2)
                    result["job_id"] = ev.get("job_id", "")
                    result["worker_pid_for_job"] = ev.get("pid")
                    if ev.get("dispatch_id") and ev["dispatch_id"] != created.id:
                        result["dispatch_id_mismatch"] = ev["dispatch_id"]
                elif kind == "model_built" and seen["job_received"] is not None and seen["model"] is None:
                    seen["model"] = round(now, 2); result["model"] = ev.get("model", "")
                elif kind == "model_build_failed" and seen["job_received"] is not None and seen["model"] is None:
                    seen["model"] = round(now, 2); result["model"] = ev.get("model", "")
                    result["model_error"] = redact(ev.get("error", ""))
                elif kind == "session_start" and seen["job_received"] is not None and seen["session_start"] is None:
                    seen["session_start"] = round(now, 2)

            if seen["session_start"] is not None:
                break
            await asyncio.sleep(0.25)

        result["framework_ack"] = any(
            "received job request" in line and room in line for _, line in worker.snapshot()
            if _ >= log_from)
        result["t"].update({k: v for k, v in seen.items() if v is not None})

        if seen["session_start"] is not None:
            result["verdict"] = "PASS"
            result["classification"] = "session_started"
        elif result["classification"] == "worker_died":
            result["verdict"] = "FAIL"
        elif seen["job_received"] is None:
            result["verdict"] = "FAIL"
            result["classification"] = ("placeholder_only_no_job" if seen["placeholder"] is not None
                                        else "no_placeholder_no_job")
        elif result["model_error"]:
            result["verdict"] = "FAIL"; result["classification"] = "model_build_failed"
        elif seen["model"] is None:
            result["verdict"] = "FAIL"; result["classification"] = "job_received_no_model"
        else:
            result["verdict"] = "FAIL"; result["classification"] = "model_ok_no_session"

        if result["verdict"] == "FAIL":
            result["server_state_at_failure"] = await server_state(room)
            result["worker_log_window"] = worker.window(log_from)
            result["server_log_tail"] = server_log_tail()
    except Exception as exc:
        result["verdict"] = "FAIL"
        result["classification"] = "test_error"
        result["error"] = redact(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room))
        except Exception:
            pass
        await lk.aclose()

    # Did the job actually end, or is it still occupying the worker?
    end_deadline = time.time() + settle
    while time.time() < end_deadline:
        if any(e.get("kind") == "session_end" and e.get("room") == room
               for e in voice_events.read_since(offset)):
            result["session_end"] = round(time.time() - log_from, 2)
            break
        await asyncio.sleep(0.25)
    if result["session_end"] is None and result["verdict"] == "PASS":
        result["note"] = f"session_start seen but no session_end within {settle:.0f}s of room deletion"
    return result


# --- the run -------------------------------------------------------------

def port_open(port: int) -> bool:
    import socket

    s = socket.socket(); s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def existing_worker() -> dict | None:
    try:
        held = json.loads(LOCK.read_text(encoding="utf-8"))
        import psutil

        p = psutil.Process(int(held["pid"]))
        if abs(p.create_time() - float(held.get("started", 0))) < 1.0 and p.is_running():
            return held
    except Exception:
        return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for session_start")
    parser.add_argument("--settle", type=float, default=15.0, help="seconds to wait for session_end")
    args = parser.parse_args()

    from core.livekit_config import get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    _LITERALS.append(cfg.api_secret)
    _LITERALS.append(os.environ.get("OPENAI_API_KEY", ""))

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_ROOT / f"lifecycle-{run_id}"
    out.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def say(text: str = "") -> None:
        text = redact(text); print(text); lines.append(text)

    say(f"ARGO worker lifecycle test - {run_id}")
    say(f"  agent={cfg.agent_name} model={cfg.model} url={cfg.url} dispatches={args.n}")
    say("=" * 70)

    # Preconditions - and no killing to satisfy them.
    if not port_open(7880):
        say("ABORT: nothing listening on 7880 - start livekit-server first."); return 2
    held = existing_worker()
    if held:
        say(f"a worker is already running (pid {held['pid']}, started {held.get('started_human')}).")
        say("  asking it to drain gracefully...")
        DRAIN.parent.mkdir(parents=True, exist_ok=True); DRAIN.write_text("drain\n", encoding="utf-8")
        for _ in range(90):
            time.sleep(0.5)
            if not existing_worker():
                break
        if existing_worker():
            say(f"ABORT: pid {held['pid']} ignored the drain request. It is an OLD worker without the")
            say("       drain watcher. Stop it yourself (Ctrl+C in its window), then re-run. Not killing it.")
            return 2
        say("  drained.")
    removed = asyncio.run(cleanup_rooms("argo-lc-"))
    if removed:
        say(f"  removed leftover rooms: {', '.join(removed)}")

    worker = Worker(out / "worker.log")
    say("\nstarting worker...")
    started = worker.start()
    say(f"  {json.dumps(started)}")
    if not started["ok"]:
        for l in started.get("tail", []): say("    " + l)
        return 1

    results = []
    for i in range(1, args.n + 1):
        room = f"argo-lc-{run_id}-{i:02d}"
        r = asyncio.run(run_one(i, room, worker, args.timeout, args.settle))
        results.append(r)
        t = r["t"]
        say(f"[{r['verdict']}] #{i:02d} {room}  dispatch={r['dispatch_id'] or '-'}  "
            f"placeholder={t.get('placeholder', '-')}s  ack={'y' if r['framework_ack'] else 'n'}  "
            f"job_received={t.get('job_received', '-')}s  model={t.get('model', '-')}s  "
            f"session_start={t.get('session_start', '-')}s  session_end={r['session_end'] if r['session_end'] is not None else '-'}s  "
            f"pid={r['worker_pid_for_job'] or '-'}  [{r['classification']}]")
        if r["verdict"] == "FAIL":
            (out / f"fail-{i:02d}.json").write_text(redact(json.dumps(r, indent=2)), encoding="utf-8")
            if r.get("model_error"): say(f"       model error: {r['model_error']}")
            if r.get("error"): say(f"       error: {r['error']}")
        if r["classification"] == "worker_died":
            say("worker died - stopping the run."); break

    say("\ndraining worker...")
    drained = worker.drain()
    say(f"  {json.dumps(drained)}")

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = [r for r in results if r["verdict"] != "PASS"]
    say("\n" + "=" * 70)
    say(f"{passed}/{len(results)} dispatches started a real session")
    by_class: dict[str, int] = {}
    for r in failed:
        by_class[r["classification"]] = by_class.get(r["classification"], 0) + 1
    for cls, n in sorted(by_class.items()):
        say(f"  {n:2d} x {cls}")
    if not drained["ok"]:
        say(f"  DRAIN FAILED: {drained.get('error')}  (real pid {drained.get('real_pid')} left running on purpose)")
    say(f"\nworker: id={started.get('worker_id')} stub_pid={started.get('stub_pid')} real_pid={started.get('real_pid')}")
    say(f"artifacts: {out}")

    (out / "report.json").write_text(redact(json.dumps({
        "run_id": run_id, "config": {"agent": cfg.agent_name, "model": cfg.model, "url": cfg.url},
        "worker": started, "drain": drained, "results": results,
    }, indent=2, default=str)), encoding="utf-8")
    (out / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if (passed == len(results) and drained["ok"] and results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
