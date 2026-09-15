"""Wire the event sink into the live session. Verifies by reading back."""
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
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label} (x{s.count(old)})"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

AGENT = "livekit_realtime_agent.py"

patch(AGENT,
'''    def _safe(name, handler):''',
'''    from core import voice_events

    voice_events.emit(
        "session_start",
        room=str(getattr(getattr(session, "_room", None), "name", "") or ""),
    )

    def _safe(name, handler):''',
"session_start event", marker='voice_events.emit(\n        "session_start"')

patch(AGENT,
'''        logger.info("[Session] heard: %r", transcript)''',
'''        logger.info("[Session] heard: %r", transcript)
        voice_events.emit("heard", text=transcript,
                          final=bool(getattr(event, "is_final", False)))''',
"heard event", marker='voice_events.emit("heard"')

patch(AGENT,
'''        logger.info("[Session] user %s -> %s", old, new)''',
'''        logger.info("[Session] user %s -> %s", old, new)
        voice_events.emit("user_state", old=str(old), new=str(new))''',
"user_state event", marker='voice_events.emit("user_state"')

patch(AGENT,
'''    def on_agent_state(event):
        logger.info("[Session] agent %s -> %s",
                    getattr(event, "old_state", "?"), getattr(event, "new_state", "?"))''',
'''    def on_agent_state(event):
        old = getattr(event, "old_state", "?")
        new = getattr(event, "new_state", "?")
        logger.info("[Session] agent %s -> %s", old, new)
        voice_events.emit("agent_state", old=str(old), new=str(new))''',
"agent_state event", marker='voice_events.emit("agent_state"')

patch(AGENT,
'''        logger.info("[Session] %s said: %r",
                    getattr(item, "role", "?"), (getattr(item, "text_content", "") or "")[:200])''',
'''        logger.info("[Session] %s said: %r",
                    getattr(item, "role", "?"), (getattr(item, "text_content", "") or "")[:200])
        voice_events.emit("said", role=str(getattr(item, "role", "?")),
                          text=(getattr(item, "text_content", "") or "")[:600])''',
"said event", marker='voice_events.emit("said"')

patch(AGENT,
'''        logger.error("[Session] error: %s", getattr(event, "error", event))''',
'''        logger.error("[Session] error: %s", getattr(event, "error", event))
        voice_events.emit("error", detail=str(getattr(event, "error", event))[:400])''',
"error event", marker='voice_events.emit("error"')

patch(AGENT,
'''            deep_think.cancel_all(reason="user_started_speaking")''',
'''            killed = deep_think.cancel_all(reason="user_started_speaking")
            if killed:
                voice_events.emit("deep_think_cancelled", count=killed)''',
"deep-think cancel event", marker='voice_events.emit("deep_think_cancelled"')

patch(AGENT,
'''        logger.info("[Interrupt] urgent phrase %r -> interrupting now (heard %r)",
                    phrase, transcript[:80])''',
'''        logger.info("[Interrupt] urgent phrase %r -> interrupting now (heard %r)",
                    phrase, transcript[:80])
        from core import voice_events as _ve
        _ve.emit("urgent_interrupt", phrase=phrase, transcript=transcript[:120])''',
"urgent-interrupt event", marker='_ve.emit("urgent_interrupt"')

patch(AGENT,
'''        result = await deep_think.think(''',
'''        from core import voice_events as _ve
        _ve.emit("deep_think_start", question=question[:200], model=cfg.deep_think_model)
        result = await deep_think.think(''',
"deep-think start event", marker='_ve.emit("deep_think_start"')

patch(AGENT,
'''        if result.cancelled:
            # He started talking again. Saying anything here would talk over
            # the thought that cancelled this one.''',
'''        _ve.emit("deep_think_done", ok=result.ok, cancelled=result.cancelled,
                 elapsed_ms=result.elapsed_ms, error=result.error)
        if result.cancelled:
            # He started talking again. Saying anything here would talk over
            # the thought that cancelled this one.''',
"deep-think done event", marker='_ve.emit("deep_think_done"')

print("\n".join(log))

print("\n--- read-back audit ---")
s = io.open(ROOT / AGENT, encoding="utf-8").read()
for needle, label in [
    ('voice_events.emit(\n        "session_start"', "session_start"),
    ('voice_events.emit("heard"', "heard"),
    ('voice_events.emit("user_state"', "user_state"),
    ('voice_events.emit("agent_state"', "agent_state"),
    ('voice_events.emit("said"', "said"),
    ('voice_events.emit("error"', "error"),
    ('voice_events.emit("deep_think_cancelled"', "deep_think_cancelled"),
    ('_ve.emit("urgent_interrupt"', "urgent_interrupt"),
    ('_ve.emit("deep_think_start"', "deep_think_start"),
    ('_ve.emit("deep_think_done"', "deep_think_done"),
]:
    print(f"  {'OK  ' if needle in s else 'MISS'} {label}")

import ast
ast.parse(s)
print("\nagent parses cleanly")
