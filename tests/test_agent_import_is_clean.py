"""Importing the realtime agent must not touch the environment.

livekit_realtime_agent.py used to call build_agent_server() at module
scope, which runs os.environ.setdefault for LIVEKIT_URL, API key and
secret and opens an AgentServer. That leaked LiveKit settings into any
process that merely imported the module - including pytest, where it
broke an unrelated test about livekit_status being safe with no server.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = """
import os, sys
sys.path.insert(0, r"{root}")
before = {{k: os.environ.get(k) for k in
          ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_AGENT_NAME")}}
import livekit_realtime_agent  # noqa: F401
after = {{k: os.environ.get(k) for k in before}}
changed = sorted(k for k in before if before[k] != after[k])
print("CHANGED:" + ",".join(changed))
print("HAS_BUILDER:" + str(hasattr(livekit_realtime_agent, "build_agent_server")))
print("HAS_SERVER_AT_IMPORT:" + str(hasattr(livekit_realtime_agent, "server")))
"""


def _run_probe():
    result = subprocess.run(
        [sys.executable, "-c", PROBE.format(root=str(ROOT))],
        capture_output=True, text=True, timeout=180, cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return dict(
        line.split(":", 1) for line in result.stdout.strip().splitlines() if ":" in line
    )


def test_import_does_not_mutate_the_environment():
    out = _run_probe()
    assert out["CHANGED"] == "", f"import set {out['CHANGED']}"


def test_the_server_is_built_on_demand_not_at_import():
    out = _run_probe()
    assert out["HAS_BUILDER"] == "True"
    assert out["HAS_SERVER_AT_IMPORT"] == "False"
