"""Persisted repair jobs: isolated checkout, verification, review, explicit apply."""
from __future__ import annotations
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


def _fallback_codex() -> str | None:
    """Codex when it isn't on PATH: the desktop app's bundled CLI, then known spots.

    The old LocalAppData install is too old for current models; delegate_jobs
    already knows the right order, so reuse it rather than guess twice.
    """
    try:
        from core.delegate_jobs import DelegateSettings, resolve_executable

        return resolve_executable(DelegateSettings(enabled=True, engine="codex"))
    except Exception:
        return None


class CodeRepairManager:
    def __init__(self, root=None, broadcast_fn=None, *, timeout=1800, verify_command=None, auto_apply=True):
        self.root = Path(root or Path(__file__).resolve().parents[1]).resolve()
        self.request_dir = self.root / "runtime" / "code_requests"
        self.broadcast = broadcast_fn or (lambda *_: None)
        self.timeout = timeout
        self.auto_apply = auto_apply
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

    def _project_root(self, project_path):
        if not project_path:
            return self.root
        from core.filesystem_access import check_read, check_write, path_shape_problem
        problem = path_shape_problem(project_path)
        if problem:
            raise ValueError(f"Project path refused: {problem}.")
        target = Path(project_path).expanduser()
        if not target.is_absolute() or not target.is_dir():
            raise ValueError("Give the absolute path to an existing local Git project.")
        target = target.resolve()
        refusal = check_read(target) or check_write(target)
        if refusal:
            raise ValueError(refusal["message"])
        try:
            git_root = Path(self._git(target, "rev-parse", "--show-toplevel").strip()).resolve()
        except RuntimeError as exc:
            raise ValueError("That folder is not a Git project.") from exc
        if git_root != target:
            raise ValueError(f"Use the Git project root: {git_root}")
        return target

    def _job_root(self, job):
        return Path(job.get("project_root", self.root)).resolve()

    def propose(self, request, project_path=None, verification_command=None, skill_name=None):
        request = str(request or "").strip()
        if not request or len(request) > 8000:
            raise ValueError("Describe the feature or repair in 1–8000 characters.")
        project = self._project_root(project_path)
        verification = str(verification_command or "").strip()
        if len(verification) > 500 or "\n" in verification or "\r" in verification:
            raise ValueError("Verification command must be one line under 500 characters.")
        try:
            verification_args = shlex.split(verification, posix=True) if verification else []
        except ValueError as exc:
            raise ValueError("Verification command has invalid quoting.") from exc
        with self.lock:
            job = {"action_id": uuid.uuid4().hex, "request": request,
                "project_root": str(project), "restart_available": project == self.root,
                "verification_command": verification, "verification_args": verification_args,
                "skill_name": skill_name or "",
                "status": "proposed", "base": self._git(project, "rev-parse", "HEAD").strip(),
                "expires_at": time.time() + 600,
                "message": "Codex will work in a separate checkout. Passing independently verified changes apply automatically; otherwise review the diff and results in System."}
            folder = self._folder(job)
            job.update(task_path=str(folder / "request.md"), result_path=str(folder / "result.md"))
            self._save(job)
            Path(job["task_path"]).write_text(f"# Code change request\n\nProject: {project}\nVerification: {verification or 'ARGO focused tests' if project == self.root else verification or 'not supplied'}\n\n{request}\n", encoding="utf-8")
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
                project = self._job_root(job)
                # Uncommitted edits used to block every request. They don't need
                # to: the work happens in a clone of the committed HEAD and never
                # touches this checkout. What stays strict is APPLYING the result
                # (apply_if_approved) - that needs a clean tree so a reviewed
                # patch can't collide with work in progress.
                dirty = bool(self._git(project, "status", "--porcelain", "--untracked-files=no").strip())
                if self._git(project, "rev-parse", "HEAD").strip() != job["base"]:
                    raise RuntimeError("The project changed since this proposal. Create a new request.")
                codex = shutil.which("codex") or _fallback_codex()
                if not codex:
                    raise RuntimeError("Codex CLI was not found on PATH or in the Codex desktop app.")
                job.update(status="preparing")
                self._save(job)
                directory = self._folder(job)
                workspace = directory / "workspace"
                self._git(project, "clone", "--no-hardlinks", "--no-local", str(project), str(workspace))
                self._git(workspace, "checkout", "--detach", job["base"])
                self._git(workspace, "remote", "remove", "origin")
                job.update(workspace=str(workspace), log_path=str(directory / "agent.log"))
                if job.get("skill_name"):
                    from core.voice.skills import SKILL_CONTRACT
                    prompt = (SKILL_CONTRACT.format(name=job["skill_name"]) +
                              "\nWhat Tommy asked for:\n" + job["request"] +
                              "\n\nDo not push, deploy, or edit anything outside the two files. Explain remaining uncertainty.")
                else:
                    prompt = (f"Implement this requested feature or repair for {project} in the current isolated checkout:\n" + job["request"] +
                    "\nDiagnose first, implement the smallest change, run tests, and report exact commands/results. "
                    "ARGO's host manager will commit the captured change; do not spend time trying to write the sandboxed .git directory. "
                    "Use available tools and documentation as needed. "
                    "Do not push, deploy, send messages, or edit outside this checkout unless Tommy's request expressly authorizes that action. "
                    "Do not start microphones or production services. Explain remaining uncertainty.")
                with Path(job["log_path"]).open("w", encoding="utf-8") as log:
                    process = subprocess.Popen([codex, "exec", "-m", "gpt-6-astra",
                        "-c", 'model_reasoning_effort="high"', "-c", 'approval_policy="never"',
                        "--sandbox", "workspace-write", "-C", str(workspace), "-o", job["result_path"], prompt],
                        cwd=workspace, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                note = (" Your uncommitted edits are not in the isolated copy; commit them before applying the result."
                        if dirty else "")
                job.update(status="running", pid=process.pid, dirty_at_start=dirty,
                           message="Codex is preparing an isolated code change." + note)
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
            if patch and self._git(workspace, "status", "--porcelain").strip():
                self._git(workspace, "add", "-A", "--", *changed)
                self._git(workspace, "-c", "user.name=ARGO", "-c", "user.email=argo@local.invalid",
                          "commit", "-m", f"Capture isolated code change {action_id[:12]}")
            isolated_commit = self._git(workspace, "rev-parse", "HEAD").strip()
            patch_path = self._folder(job) / "changes.patch"
            patch_path.write_bytes(patch.encode("utf-8"))
            result_path = Path(job["result_path"])
            report = result_path.read_text(encoding="utf-8", errors="replace")[:50000] if result_path.exists() else "No agent report was produced."
            test_path = self._folder(job) / "tests.log"
            test_exit = None
            if exit_code == 0 and not job.get("timed_out"):
                with test_path.open("w", encoding="utf-8") as log:
                    is_argo = self._job_root(job) == self.root
                    skill = job.get("skill_name") or ""
                    if skill:
                        # A skill is judged on its own test plus the real loader,
                        # not the whole ARGO suite: it can only add two files.
                        commands = [
                            [sys.executable, "-m", "pytest", f"tests/test_skill_{skill}.py", "-q"],
                            [sys.executable, "-c",
                             "from pathlib import Path; from core.voice import skills as s; "
                             "t, r = s.discover(s.builtin_tool_names(), Path('argo_skills')); "
                             f"m = [x for x in r if x['skill'] == {skill!r}]; "
                             "assert m and m[0]['ok'], m; print('loader ok', m[0]['tools'])"],
                        ]
                    else:
                        commands = self.verify_commands if is_argo else []
                        if not is_argo and job.get("verification_args"):
                            commands = [job["verification_args"]]
                        if not is_argo:
                            commands.append(["git", "diff", "--check", job["base"], "--"])
                    for command in commands:
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
            skill_name = job.get("skill_name") or ""
            if skill_name:
                allowed = {f"argo_skills/{skill_name}.py", f"tests/test_skill_{skill_name}.py"}
                stray = sorted(set(changed) - allowed)
                if stray or f"argo_skills/{skill_name}.py" not in changed:
                    ready = False
                    job["skill_problem"] = ("Touched files outside the skill: " + ", ".join(stray)
                                            if stray else "The skill file was never written.")
            with self.lock:
                job.update(status="review_ready" if ready else "review_failed", changed_files=changed,
                    isolated_commit=isolated_commit,
                    patch_path=str(patch_path), patch_sha256=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                    diff=patch[:100000], diff_truncated=len(patch) > 100000, report=report,
                    test_exit=test_exit, test_log=test_path.read_text(encoding="utf-8", errors="replace")[-30000:] if test_path.exists() else "Tests not run after agent failure.",
                    verification_scope="ARGO focused tests" if self._job_root(job) == self.root else
                    ("Project command plus Git diff check" if job.get("verification_args") else "Git diff check only; review agent-reported project tests"),
                    message="Review the diff and verification output. Changes have not been applied.")
                self._save(job)
                if ready and skill_name:
                    self._install_skill(job, workspace, changed)
                elif ready and self.auto_apply and (self._job_root(job) == self.root or job.get("verification_args")):
                    applied = self.apply_if_approved(action_id, job["patch_sha256"], True)
                    if applied["status"] == "error":
                        job["message"] = "Automatic apply stopped: " + applied["message"]
                        self._save(job)
        except Exception as exc:
            with self.lock:
                job.update(status="review_failed", message=f"Verification did not complete: {exc}")
                self._save(job)
        self.broadcast("code_repair_result", dict(job))

    def _install_skill(self, job, workspace, changed):
        """Copy a verified skill into the live folders and record it on argo-self.

        Skills are new files in their own folder, so unlike a patch this never
        collides with Tommy's uncommitted edits - which is why it needs no clean
        tree and no approval.
        """
        from core.voice import skills

        name = job["skill_name"]
        try:
            files = {rel: (Path(workspace) / rel).read_bytes() for rel in changed}
            info = skills.install(name, files, directory=self.root / "argo_skills",
                                  tests_directory=self.root / "tests")
            branch = self._record_on_branch(files, f"Argo added skill {name}: {job['request'][:120]}")
            job.update(status="applied", skill_installed=True,
                       message=f"Skill {name} installed" + (" (replaced the old version)" if info["replaced"] else "") +
                               ". It loads the next time a voice session starts." +
                               (f" Recorded on branch argo-self ({branch})." if branch else ""))
        except Exception as exc:
            job.update(status="review_failed", message=f"Skill passed its tests but could not be installed: {exc}")
        self._save(job)

    def _record_on_branch(self, files, message):
        """Commit the skill on the argo-self branch via a separate worktree.

        Best effort: it never touches Tommy's checkout, and any failure here is
        swallowed - the skill is already installed and logged.
        """
        try:
            tree = self.root / "runtime" / "argo_self_worktree"
            if not tree.exists():
                have = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--verify", "-q", "argo-self"],
                                      capture_output=True, text=True).returncode == 0
                args = ["worktree", "add", str(tree), "argo-self"] if have else \
                       ["worktree", "add", "-b", "argo-self", str(tree), "HEAD"]
                self._git(self.root, *args)
            for rel, data in files.items():
                target = tree / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self._git(tree, "add", "--", *files)
            self._git(tree, "-c", "user.name=ARGO", "-c", "user.email=argo@local.invalid",
                      "commit", "-m", message)
            return self._git(tree, "rev-parse", "--short", "HEAD").strip()
        except Exception:
            return ""

    def apply_if_approved(self, action_id, patch_sha256, approved):
        with self.lock:
            job = self.jobs.get(action_id)
            if approved is not True or not job or job["status"] != "review_ready":
                return {"status": "error", "message": "A reviewed, passing repair and explicit approval are required."}
            try:
                project = self._job_root(job)
                patch = Path(job["patch_path"]).read_bytes()
                if patch_sha256 != job["patch_sha256"] or hashlib.sha256(patch).hexdigest() != patch_sha256:
                    raise RuntimeError("Patch changed since review.")
                if self._git(project, "rev-parse", "HEAD").strip() != job["base"] or self._git(project, "status", "--porcelain", "--untracked-files=no").strip():
                    raise RuntimeError("Working checkout changed or has uncommitted edits. Commit or set them aside, "
                                       "then apply again (or re-run the request) so the reviewed patch lands on a clean base.")
                self._git(project, "apply", "--check", job["patch_path"])
                self._git(project, "apply", job["patch_path"])
                self._git(project, "add", "-A", "--", *job["changed_files"])
                self._git(project, "commit", "-m", f"Apply reviewed code change {action_id[:12]}")
                commit = self._git(project, "rev-parse", "HEAD").strip()
                job.update(status="applied", commit=commit,
                           message="Reviewed patch applied and committed. " +
                           ("Use Restart ARGO stack to load it in the voice worker." if project == self.root else "Project deployment and runtime verification remain to be done."))
                self._save(job)
            except Exception as exc:
                return {"status": "error", "message": str(exc)}
            return dict(job)

    def restart_if_applied(self, action_id):
        """Launch the existing drain-and-restart script after a reviewed apply."""
        with self.lock:
            job = self.jobs.get(action_id)
            if not job or job["status"] != "applied":
                return {"status": "error", "message": "Apply a reviewed code change before restarting ARGO."}
            if self._job_root(job) != self.root:
                return {"status": "error", "message": "This project needs its own deployment procedure, not an ARGO restart."}
            script = self.root / "scripts" / "start_argo_stack.ps1"
            if not script.is_file():
                return {"status": "error", "message": "ARGO's full-stack restart script is missing."}
            log_path = self._folder(job) / "restart.log"
            try:
                with log_path.open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                        cwd=self.root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
                        if os.name == "nt" else 0,
                    )
                job.update(status="restart_requested", restart_pid=process.pid,
                           restart_log=str(log_path),
                           message="Full-stack restart launched. Check its log for port checks and a real dispatch PASS.")
                self._save(job)
            except OSError as exc:
                return {"status": "error", "message": f"Could not launch ARGO restart: {exc}"}
            return dict(job)
