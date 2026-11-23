"""Detached job runner: ``python -m core.job_runner <job_dir>``.

A background agent job (Codex etc.) must not die when the voice session that
asked for it ends, so the job runs here, in its own process, and the voice
worker only starts it and reads what it writes. Everything lives in the job
folder:

    spec.json      what to run (written by core.delegate_jobs.start)
    status.json    this runner keeps it current: status, pid, heartbeat,
                   last_activity, progress, question, summary, error
    cancel         create this file and the runner stops the agent
    out.txt/err.txt  the agent's own output (files, not pipes, so nothing blocks)

Status values: starting, running, done, failed, timed_out, cancelled, waiting.
"waiting" = the agent could not continue without an answer from Tommy; its
final message started with NEED_ANSWER:.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HEARTBEAT_EVERY_S = 5.0
FINAL = {"done", "failed", "timed_out", "cancelled", "waiting"}


def update_status(job_dir: Path, **fields) -> None:
    """Merge fields into status.json atomically; a reader never sees half a file."""
    path = job_dir / "status.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.update(fields)
    tmp = job_dir / "status.json.tmp"
    for _ in range(5):
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.1)


def kill_tree(pid: int) -> None:
    try:
        import psutil
        parent = psutil.Process(pid)
        procs = parent.children(recursive=True) + [parent]
        for proc in procs:
            try:
                proc.kill()
            except Exception:
                pass
        return
    except Exception:
        pass
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def read_progress(path: str) -> dict:
    """{"done": n, "total": m, "step": "..."} from the file the agent keeps, if any."""
    if not path:
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        done, total = int(raw.get("done", 0)), int(raw.get("total", 0))
        if total > 0 and 0 <= done <= total:
            return {"progress_done": done, "progress_total": total,
                    "step": str(raw.get("step", ""))[:120]}
    except Exception:
        pass
    return {}


def newest_mtime(paths: list[Path]) -> float:
    latest = 0.0
    for p in paths:
        try:
            latest = max(latest, p.stat().st_mtime)
        except OSError:
            pass
    return latest


def split_question(summary: str) -> str:
    """The question if the agent's final message says it is blocked, else ''."""
    for line in (summary or "").splitlines():
        if line.strip().upper().startswith("NEED_ANSWER:"):
            return line.split(":", 1)[1].strip() or "Needs an answer."
    return ""


def run(job_dir: Path) -> None:
    spec = json.loads((job_dir / "spec.json").read_text(encoding="utf-8"))
    out_file, err_file = job_dir / "out.txt", job_dir / "err.txt"
    result_file = Path(spec.get("result_file") or "")
    watch = [out_file, err_file] + ([result_file] if spec.get("result_file") else [])
    update_status(job_dir, runner_pid=os.getpid(), heartbeat=time.time())
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = None
    try:
        with open(out_file, "wb") as out, open(err_file, "wb") as err:
            process = subprocess.Popen(spec["cmd"], cwd=spec["cwd"], stdin=subprocess.PIPE,
                                       stdout=out, stderr=err, creationflags=flags)
            try:
                process.stdin.write(spec["prompt"].encode("utf-8"))
                process.stdin.close()
            except OSError:
                pass
            update_status(job_dir, status="running", pid=process.pid, heartbeat=time.time())
            started = time.time()
            timeout_s = float(spec.get("timeout_s") or 1800)
            last_beat = 0.0
            outcome = ""
            while process.poll() is None:
                time.sleep(0.5)
                if (job_dir / "cancel").exists():
                    outcome = "cancelled"
                    break
                if time.time() - started > timeout_s:
                    outcome = "timed_out"
                    break
                if time.time() - last_beat >= HEARTBEAT_EVERY_S:
                    last_beat = time.time()
                    update_status(job_dir, heartbeat=last_beat,
                                  last_activity=newest_mtime(watch) or started,
                                  **read_progress(spec.get("progress_file", "")))
            if outcome:
                kill_tree(process.pid)
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass
    except Exception as exc:  # could not even start
        update_status(job_dir, status="failed", finished=time.time(),
                      error=f"{type(exc).__name__}: {exc}"[:500])
        return

    out_text = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
    err_text = err_file.read_text(encoding="utf-8", errors="replace") if err_file.exists() else ""
    (job_dir / "result.json").write_text(out_text, encoding="utf-8")
    final = {"finished": time.time(), "heartbeat": time.time(),
             "last_activity": newest_mtime(watch) or time.time(),
             **read_progress(spec.get("progress_file", ""))}
    if outcome == "cancelled":
        update_status(job_dir, status="cancelled", **final)
        return
    if outcome == "timed_out":
        update_status(job_dir, status="timed_out",
                      error=f"stopped after {int(float(spec.get('timeout_s') or 1800))}s", **final)
        return
    if spec.get("engine") == "codex":
        try:
            summary = result_file.read_text(encoding="utf-8").strip()
        except OSError:
            summary = ""
        ok, cost = bool(summary), None
    else:
        from core.delegate_jobs import parse_result
        ok, summary, cost = parse_result(out_text)
    ok = ok and process.returncode == 0
    question = split_question(summary) if ok else ""
    if question:
        update_status(job_dir, status="waiting", summary=summary, question=question,
                      cost_usd=cost, **final)
        return
    if ok:
        done_total = read_progress(spec.get("progress_file", ""))
        if done_total:  # a finished job is 100%, whatever the agent last wrote
            final["progress_done"] = final["progress_total"] = done_total["progress_total"]
        update_status(job_dir, status="done", summary=summary, cost_usd=cost, **final)
    else:
        update_status(job_dir, status="failed", summary=summary, cost_usd=cost,
                      error=(err_text.strip() or summary or f"exit code {process.returncode}")[-500:],
                      **final)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m core.job_runner <job_dir>", file=sys.stderr)
        return 2
    run(Path(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
