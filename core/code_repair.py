"""Persisted repair jobs: isolated checkout, verification, review, explicit apply."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


class CodeRepairManager:
    def __init__(self, root=None, broadcast_fn=None, *, timeout=1800, verify_command=None):
        self.root = Path(root or Path(__file__).resolve().parents[1]).resolve()
        self.request_dir = self.root / "runtime" / "code_requests"
        self.broadcast = broadcast_fn or (lambda *_: None)
        self.timeout = timeout
        self.verify_command = verify_command or [sys.executable, "-m", "pytest",
            "tests/test_self_repair_and_code_repair.py", "tests/test_voice_audit_repairs.py",
            "tests/test_llm_router.py", "-q"]
        self.verify_commands = [self.verify_command]
        if verify_command is None:
            self.verify_commands.append(["node", "--test", "tests/test_cortana_avatar.cjs", "tests/test_repair_ui.cjs"])
        self.lock = threading.RLock()
        self.jobs = {}
        if self.request_dir.exists():
            for path in self.request_dir.glob("*/job.json"):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                    if job["action_id"] != path.parent.name:
                        continue
                    self.jobs[job["action_id"]] = job
                    if job["status"] in ("preparing", "running", "verifying"):
                        job.update(status="interrupted", message="ARGO restarted; retained checkout and logs need review. No automatic resume or apply.")
                        self._save(job)
                except (ValueError, KeyError, OSError):
                    continue

    def _git(self, directory, *args):
        result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True,
            encoding="utf-8", errors="replace", timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Git operation failed")
        return result.stdout

    def _folder(self, job):
        return self.request_dir / job["action_id"]

    def _save(self, job):
        directory = self._folder(job)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "job.json.tmp"
        temporary.write_text(json.dumps(job, indent=2), encoding="utf-8")
        temporary.replace(directory / "job.json")

    def snapshot(self):
        with self.lock:
            return [dict(job) for job in self.jobs.values()][-20:]

    def propose(self, request):
        request = str(request or "").strip()
        if not request or len(request) > 8000:
            raise ValueError("Describe the repair in 1–8000 characters.")
        with self.lock:
            job = {"action_id": uuid.uuid4().hex, "request": request,
                "status": "proposed", "base": self._git(self.root, "rev-parse", "HEAD").strip(),
                "expires_at": time.time() + 600,
                "message": "Astra will prepare changes in a separate checkout. Review the diff and test results before applying."}
            folder = self._folder(job)
            job.update(task_path=str(folder / "request.md"), result_path=str(folder / "result.md"))
            self._save(job)
            Path(job["task_path"]).write_text("# ARGO repair request\n\n" + request + "\n", encoding="utf-8")
            self.jobs[job["action_id"]] = job
        self.broadcast("code_repair_proposal", dict(job))
        return dict(job)

    def dispatch_if_approved(self, action_id, approved):
        with self.lock:
            job = self.jobs.get(action_id)
            if not job or job["status"] != "proposed" or job["expires_at"] < time.time():
                return {"status": "error", "message": "No current code-repair proposal."}
            if type(approved) is not bool:
                return {"status": "error", "message": "Approval must be a boolean."}
            if not approved:
                job.update(status="cancelled", message="Declined. Request retained.")
                self._save(job)
                return dict(job)
            try:
                if self._git(self.root, "status", "--porcelain").strip():
                    raise RuntimeError("Commit or set aside current changes before starting an isolated repair.")
                if self._git(self.root, "rev-parse", "HEAD").strip() != job["base"]:
                    raise RuntimeError("ARGO changed since this proposal. Create a new request.")
                codex = shutil.which("codex")
                if not codex:
                    raise RuntimeError("Codex CLI is unavailable on PATH.")
                job.update(status="preparing")
                self._save(job)
                directory = self._folder(job)
                workspace = directory / "workspace"
                self._git(self.root, "clone", "--no-hardlinks", "--no-local", str(self.root), str(workspace))
                self._git(workspace, "checkout", "--detach", job["base"])
                self._git(workspace, "remote", "remove", "origin")
                job.update(workspace=str(workspace), log_path=str(directory / "agent.log"))
                prompt = ("Repair this reported ARGO problem in the current isolated checkout:\n" + job["request"] +
                    "\nDiagnose first, implement the smallest change, run tests, and report exact commands/results. "
                    "Do not commit, push, access external systems, or edit outside this checkout. "
                    "Do not start microphones or production services. Explain remaining uncertainty.")
                with Path(job["log_path"]).open("w", encoding="utf-8") as log:
                    process = subprocess.Popen([codex, "exec", "--ignore-user-config", "-m", "gpt-6-astra",
                        "-c", 'model_reasoning_effort="high"', "-c", 'approval_policy="never"',
                        "--sandbox", "workspace-write", "-C", str(workspace), "-o", job["result_path"], prompt],
                        cwd=workspace, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                job.update(status="running", pid=process.pid, message="Astra is preparing an isolated repair.")
                self._save(job)
                threading.Thread(target=self._monitor, args=(action_id, process), daemon=True).start()
            except Exception as exc:
                job.update(status="failed", message=str(exc))
                self._save(job)
            return dict(job)

    def _monitor(self, action_id, process):
        with self.lock:
            job = self.jobs[action_id]
        try:
            try:
                exit_code = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                import psutil
                parent = psutil.Process(process.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
                exit_code = process.wait(timeout=10)
                job["timed_out"] = True
            with self.lock:
                job.update(exit_code=exit_code, status="verifying")
                self._save(job)
            workspace = Path(job["workspace"])
            self._git(workspace, "add", "-N", "--", ".")
            patch = self._git(workspace, "diff", "--binary", job["base"], "--")
            changed = self._git(workspace, "diff", "--name-only", job["base"], "--").splitlines()
            patch_path = self._folder(job) / "changes.patch"
            patch_path.write_bytes(patch.encode("utf-8"))
            result_path = Path(job["result_path"])
            report = result_path.read_text(encoding="utf-8", errors="replace")[:50000] if result_path.exists() else "No agent report was produced."
            test_path = self._folder(job) / "tests.log"
            test_exit = None
            if exit_code == 0 and not job.get("timed_out"):
                with test_path.open("w", encoding="utf-8") as log:
                    for command in self.verify_commands:
                        log.write("Command: " + subprocess.list2cmdline(command) + "\n")
                        log.flush()
                        check = subprocess.run(command, cwd=workspace, stdout=log,
                            stderr=subprocess.STDOUT, timeout=180, stdin=subprocess.DEVNULL)
                        test_exit = check.returncode
                        if test_exit:
                            break
            ready = exit_code == 0 and test_exit == 0 and bool(patch) and result_path.exists() and not job.get("timed_out")
            # Tests may themselves write files. Any drift requires a fresh review.
            self._git(workspace, "add", "-N", "--", ".")
            after = self._git(workspace, "diff", "--binary", job["base"], "--")
            ready = ready and after == patch
            with self.lock:
                job.update(status="review_ready" if ready else "review_failed", changed_files=changed,
                    patch_path=str(patch_path), patch_sha256=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                    diff=patch[:100000], diff_truncated=len(patch) > 100000, report=report,
                    test_exit=test_exit, test_log=test_path.read_text(encoding="utf-8", errors="replace")[-30000:] if test_path.exists() else "Tests not run after agent failure.",
                    message="Review the diff and verification output. Changes have not been applied.")
                self._save(job)
        except Exception as exc:
            with self.lock:
                job.update(status="review_failed", message=f"Verification did not complete: {exc}")
                self._save(job)
        self.broadcast("code_repair_result", dict(job))

    def apply_if_approved(self, action_id, patch_sha256, approved):
        with self.lock:
            job = self.jobs.get(action_id)
            if approved is not True or not job or job["status"] != "review_ready":
                return {"status": "error", "message": "A reviewed, passing repair and explicit approval are required."}
            try:
                patch = Path(job["patch_path"]).read_bytes()
                if patch_sha256 != job["patch_sha256"] or hashlib.sha256(patch).hexdigest() != patch_sha256:
                    raise RuntimeError("Patch changed since review.")
                if self._git(self.root, "rev-parse", "HEAD").strip() != job["base"] or self._git(self.root, "status", "--porcelain").strip():
                    raise RuntimeError("Working checkout changed. Rebase and review the repair before applying.")
                self._git(self.root, "apply", "--check", job["patch_path"])
                self._git(self.root, "apply", job["patch_path"])
                job.update(status="applied", message="Reviewed patch applied. Restart ARGO when ready; no automatic deployment or commit.")
                self._save(job)
            except Exception as exc:
                return {"status": "error", "message": str(exc)}
            return dict(job)
