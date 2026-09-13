"""Auditable, approval-gated handoff of a code repair to local Codex."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


class CodeRepairManager:
    """Create a repair record first; dispatch only after a UI approval."""

    def __init__(self, root: Path | None = None, broadcast_fn: Callable = None) -> None:
        self.root = (root or Path(__file__).resolve().parents[1]).resolve()
        self.request_dir = self.root / "runtime" / "code_requests"
        self.broadcast = broadcast_fn or (lambda *_: None)
        self.pending: dict[str, dict[str, Any]] = {}

    def propose(self, request: str) -> dict[str, Any]:
        request = str(request or "").strip()
        if not request:
            raise ValueError("Describe the problem before requesting a code repair.")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        action_id = f"code-repair-{stamp}"
        self.request_dir.mkdir(parents=True, exist_ok=True)
        task_path = self.request_dir / f"{action_id}.md"
        result_path = self.request_dir / f"{action_id}-result.md"
        task_path.write_text(self._render_task(request, result_path), encoding="utf-8")
        proposal = {
            "action_id": action_id,
            "request": request,
            "task_path": str(task_path),
            "result_path": str(result_path),
            "message": "Codex will inspect ARGO, make only scoped changes, run focused tests, and write its result to the task record. No commit or push is requested.",
        }
        self.pending[action_id] = proposal
        self.broadcast("code_repair_proposal", proposal)
        return proposal

    def dispatch_if_approved(self, action_id: str, approved: bool) -> dict[str, Any]:
        proposal = self.pending.pop(action_id, None)
        if proposal is None:
            return {"status": "error", "message": "No pending code-repair proposal."}
        if not approved:
            return {"status": "cancelled", "message": "Code repair declined; task record retained.", **proposal}
        codex = shutil.which("codex")
        if not codex:
            return {"status": "error", "message": "Codex CLI is not available on PATH.", **proposal}
        prompt = (
            f"Read {proposal['task_path']}. Work only in {self.root}. Diagnose the reported issue, "
            "make the smallest safe repair, run focused tests, and write a concise result to the "
            f"requested result path. Do not commit, push, delete unrelated files, or change external systems."
        )
        log_path = Path(proposal["result_path"]).with_suffix(".log")
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [codex, "exec", "-m", "gpt-6-astra", "-c", 'model_reasoning_effort="high"', "--sandbox", "workspace-write", "--approve-for-me", "-C", str(self.root), "-o", proposal["result_path"], prompt],
                cwd=self.root,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if __import__("os").name == "nt" else 0,
            )
        result = {"status": "started", "pid": process.pid, "log_path": str(log_path), **proposal}
        self.broadcast("code_repair_result", result)
        return result

    def _render_task(self, request: str, result_path: Path) -> str:
        return f"""# ARGO Code Repair Request

Created: {datetime.now().isoformat(timespec='seconds')}
Workspace: {self.root}

## Reported problem

{request}

## Guardrails

- Diagnose before editing and state the evidence for the root cause.
- Keep edits scoped to this request; preserve unrelated work.
- Run the smallest useful verification.
- Do not commit, push, delete unrelated files, or change external systems.

## Required result

Write changed files, test output, remaining risk, and any blocker to:
`{result_path}`
"""
