"""Does a dispatch actually put ARGO in a room?

The dashboard saying LIVE proves nothing: the browser joins, publishes a mic
track, and if no agent takes the job it is talking to an empty room. This
proves the other half without needing a human or a browser - it creates a
throwaway room, dispatches the worker into it, and watches for an agent
participant to appear.

    .venv\\Scripts\\python tools\\dispatch_probe.py

Exit 0 means an agent joined and a realtime session started. The room is
deleted afterwards either way.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

ROOM = "argo-dispatch-probe"
WAIT_SECONDS = 30.0
AGENT_KIND = 4


async def probe() -> int:
    from livekit import api

    from core.livekit_config import ensure_livekit_agent_dispatch, get_livekit_realtime_config

    cfg = get_livekit_realtime_config()
    print(f"server   : {cfg.url}")
    print(f"agent    : {cfg.agent_name}")
    print(f"model    : {cfg.model} / {cfg.voice}")
    print(f"room     : {ROOM}")
    print("-" * 62)

    lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
    joined, elapsed, identity = False, None, None
    try:
        await lk.room.create_room(api.CreateRoomRequest(name=ROOM, empty_timeout=120))
        print(f"created room {ROOM!r}")

        dispatch_id = await asyncio.to_thread(ensure_livekit_agent_dispatch, room_name=ROOM, config=cfg)
        print(f"dispatched   {dispatch_id or '(no id returned)'}")

        # A participant of kind AGENT appears as soon as the dispatch exists,
        # with no worker running at all - this probe used to PASS on that.
        # The only thing that cannot be faked is the session writing its own
        # start event, so that is what is waited for. The placeholder is still
        # recorded, because "placeholder yes, session no" is the exact shape
        # of the real fault.
        from core import voice_events

        offset = voice_events.tail_position()
        started = time.time()
        placeholder_at = None
        while time.time() - started < WAIT_SECONDS:
            parts = (await lk.room.list_participants(
                api.ListParticipantsRequest(room=ROOM))).participants
            agents = [p for p in parts if p.kind == AGENT_KIND]
            if agents and placeholder_at is None:
                placeholder_at = round(time.time() - started, 2)
                identity = agents[0].identity

            if any(e.get("kind") == "session_start"
                   for e in voice_events.read_since(offset)):
                joined, elapsed = True, round(time.time() - started, 2)
                break
            await asyncio.sleep(0.4)

        if placeholder_at is not None:
            print(f"placeholder  agent participant appeared after {placeholder_at}s "
                  f"(this alone proves nothing)")

        print("-" * 62)
        if joined:
            print(f"PASS - a real session started after {elapsed}s (agent {identity!r})")
        else:
            print(f"FAIL - no session started in {ROOM!r} within {WAIT_SECONDS:.0f}s.")
            if placeholder_at is not None:
                print("       An agent PLACEHOLDER appeared but no session ever began:")
                print("       the dispatch exists and no worker took it. This is the")
                print("       'dashboard says LIVE and nothing answers' fault exactly.")
            print("       Check the worker output for 'received job request'.")
            print("       NOTE: `livekit_realtime_agent.py start` registers but does")
            print("       not receive jobs here - use `dev`.")
    finally:
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=ROOM))
            print(f"cleaned up {ROOM!r}")
        except Exception as exc:
            print(f"could not delete {ROOM!r}: {type(exc).__name__}")
        await lk.aclose()

    return 0 if joined else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(probe()))
