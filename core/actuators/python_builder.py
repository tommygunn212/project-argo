"""
Python Builder Actuator

Responsibilities:
- Write a Python file into the sandbox/ folder.
- Open the file in VS Code for review (code -r).
- Execute the file and capture output for reporting.

This is a simple local actuator with explicit boundaries.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Tuple


class PythonBuilder:
    """Local actuator for drafting and running Python scripts in sandbox."""

    def __init__(self, sandbox_dir: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[2]
        self.sandbox_dir = sandbox_dir or (base_dir / "sandbox")

    def _resolve_path(self, filename: str) -> Path:
        if not filename.endswith(".py"):
            filename = f"{filename}.py"
        return self.sandbox_dir / filename

    def write_script(self, filename: str, code: str) -> Path:
        """Write a Python file to the sandbox folder and return its path."""
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        target = self._resolve_path(filename)
        target.write_text(code, encoding="utf-8")
        return target

    def open_in_vscode(self, filename: str) -> None:
        """Open the file in VS Code for review using code -r."""
        file_path = self._resolve_path(filename)
        try:
            subprocess.run(["code", "-r", str(file_path)], check=False)
        except Exception:
            # Non-fatal: opening the editor is best-effort
            pass

    def test_run(self, filename: str) -> str:
        """Execute the file and return combined output as a string."""
        file_path = self._resolve_path(filename)
        process = subprocess.run(
            [sys.executable, str(file_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = process.stdout or ""
        stderr = process.stderr or ""
        result = [f"Exit code: {process.returncode}"]
        if stdout:
            result.append("STDOUT:\n" + stdout)
        if stderr:
            result.append("STDERR:\n" + stderr)
        return "\n".join(result)
