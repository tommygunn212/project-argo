"""Launcher for ARGO's Smooth Voice worker - the live conversation path.

    .\\.venv\\Scripts\\python.exe livekit_realtime_agent.py start     (or: dev)

The browser joins a LiveKit room and publishes the mic; OpenAI Realtime does
turn detection and interruption inside the audio stream; ARGO answers.

Everything lives in core/voice/ - its __init__ is the map. This file stays at
the repo root because the start/stop scripts, core.runtime_guard and the
probes in tools/ find the worker by this path.
"""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # before core.voice reads any key

from core.voice.agent import ArgoRealtimeAgent  # noqa: E402  re-exported for probes and tests
from core.voice.worker import build_agent_server, main  # noqa: E402

__all__ = ["ArgoRealtimeAgent", "build_agent_server", "main"]

if __name__ == "__main__":
    main()
