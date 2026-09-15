"""ARGO Smooth Voice doctor.

Answers one question: when the dashboard says LIVE, is anything actually
listening?

Run it from the ARGO root while Smooth Voice is connected in the browser:

    .venv\\Scripts\\python tools\\livekit_doctor.py

It reports, for the configured LiveKit server: which rooms exist, who is in
them (human vs agent), and which agent dispatches are registered. If the room
has a human publishing a mic track and no agent participant, ARGO cannot hear
you no matter what the STT/TTS settings say - the job was never dispatched.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.livekit_config import get_livekit_realtime_config  # noqa: E402

KIND_NAMES = {0: "STANDARD", 1: "INGRESS", 2: "EGRESS", 3: "SIP", 4: "AGENT"}


async def main() -> int:
    from livekit import api

    cfg = get_livekit_realtime_config()
    print(f"server        : {cfg.url}")
    print(f"configured room: {cfg.room}")
    print(f"agent_name     : {cfg.agent_name or '(none - automatic dispatch)'}")
    print(f"model / voice  : {cfg.model} / {cfg.voice}")
    print("-" * 60)

    lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
    problems: list[str] = []
    try:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
        if not rooms:
            print("no rooms on the server")
            problems.append("No room exists - the browser is not connected.")
        for room in rooms:
            print(f"room {room.name!r}  participants={room.num_participants}")
            parts = (
                await lk.room.list_participants(api.ListParticipantsRequest(room=room.name))
            ).participants
            humans = agents = 0
            for p in parts:
                kind = KIND_NAMES.get(p.kind, str(p.kind))
                tracks = ", ".join(t.type and f"{t.source}" or "?" for t in p.tracks) or "no tracks"
                print(f"   - {p.identity:<32} kind={kind:<8} [{tracks}]")
                if p.kind == 4:
                    agents += 1
                else:
                    humans += 1

            try:
                dispatches = await lk.agent_dispatch.list_dispatch(room.name)
            except Exception as exc:
                dispatches = []
                print(f"   ! dispatch API error: {type(exc).__name__}: {exc}")
                problems.append(
                    f"Room {room.name!r}: the agent dispatch API failed "
                    f"({type(exc).__name__}). Explicit dispatch cannot work."
                )
            for d in dispatches:
                print(f"   dispatch id={d.id} agent={d.agent_name!r}")
            if not dispatches:
                print("   dispatch: none")

            if humans and not agents:
                problems.append(
                    f"Room {room.name!r} has {humans} human participant(s) and NO agent. "
                    "ARGO cannot hear you: the worker was never dispatched into this room."
                )
    finally:
        await lk.aclose()

    print("-" * 60)
    if problems:
        print("PROBLEMS:")
        for line in problems:
            print(f"  * {line}")
        return 1
    print("OK: every occupied room has an agent participant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
