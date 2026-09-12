from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUEST_DIR = ROOT / "runtime" / "code_requests"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an auditable ARGO coding-agent request.")
    parser.add_argument("request", help="What Tommy wants fixed or built.")
    parser.add_argument("--repo", default=str(ROOT), help="Target repo/workspace path.")
    parser.add_argument("--agent", default="codex", choices=("codex", "claude", "vscode"))
    parser.add_argument("--open-vscode", action="store_true", help="Open the request file in VS Code.")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser()
    if not repo.is_absolute():
        repo = (ROOT / repo).resolve()

    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = REQUEST_DIR / f"{stamp}-{args.agent}-request.md"
    target.write_text(render_request(args.request, repo, args.agent), encoding="utf-8")

    if args.open_vscode:
        try:
            subprocess.run(["code", "-r", str(repo), str(target)], check=False)
        except Exception:
            pass

    print(target)
    return 0


def render_request(request: str, repo: Path, agent: str) -> str:
    return f"""# ARGO Code Request

Created: {datetime.now().isoformat(timespec="seconds")}
Requested agent: {agent}
Target workspace: {repo}

## Request

{request.strip()}

## Operating Rules

- Read the target workspace before editing.
- Keep changes scoped to this request.
- Do not revert unrelated local changes.
- Run the smallest useful verification command.
- Report changed files, verification output, and remaining risk.

## Status

- Created by ARGO.
- Awaiting coding-agent execution.
"""


if __name__ == "__main__":
    raise SystemExit(main())
