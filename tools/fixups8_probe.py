"""Make the dispatch probe tell the truth, and launch the worker in a mode
that actually receives jobs.

Two findings, both from running it rather than reading it.

  1. LiveKit creates a placeholder agent participant the moment a dispatch
     exists, whether or not any worker accepts the job. The probe watched for
     that participant, so it reported PASS with ZERO workers running. It was
     measuring the dispatch record, not ARGO.

  2. `livekit_realtime_agent.py start` registers the worker and then never
     receives a job. `dev` receives it in ~0.5s. Same code, same config, same
     agent_name. That is why the room kept showing a dispatch and no agent.

The probe now waits for a session_start event that the SESSION ITSELF writes.
A placeholder cannot forge that.
"""
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label, marker):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if marker in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label}"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

patch("tools/dispatch_probe.py",
'''        started = time.time()
        while time.time() - started < WAIT_SECONDS:
            parts = (await lk.room.list_participants(
                api.ListParticipantsRequest(room=ROOM))).participants
            agents = [p for p in parts if p.kind == AGENT_KIND]
            if agents:
                joined, elapsed, identity = True, round(time.time() - started, 2), agents[0].identity
                break
            await asyncio.sleep(0.5)''',
'''        # A participant of kind AGENT appears as soon as the dispatch exists,
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
                  f"(this alone proves nothing)")''',
"probe: require a real session_start", marker="placeholder_at = None")

patch("tools/dispatch_probe.py",
'''        if joined:
            print(f"PASS - agent {identity!r} joined after {elapsed}s")
        else:
            print(f"FAIL - no agent joined {ROOM!r} within {WAIT_SECONDS:.0f}s.")
            print("       The worker registered but never took the job. Check the")
            print("       worker log for 'received job request'.")''',
'''        if joined:
            print(f"PASS - a real session started after {elapsed}s (agent {identity!r})")
        else:
            print(f"FAIL - no session started in {ROOM!r} within {WAIT_SECONDS:.0f}s.")
            if placeholder_at is not None:
                print("       An agent PLACEHOLDER appeared but no session ever began:")
                print("       the dispatch exists and no worker took it. This is the")
                print("       'dashboard says LIVE and nothing answers' fault exactly.")
            print("       Check the worker output for 'received job request'.")
            print("       NOTE: `livekit_realtime_agent.py start` registers but does")
            print("       not receive jobs here - use `dev`.")''',
"probe: honest verdict", marker="a real session started after")

print("\n".join(log))
