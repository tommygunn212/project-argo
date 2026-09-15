"""Wire core.voice_memory into the live realtime agent.

Applied on-box with a read-back audit, because file syncs into this repo have
silently written stale bytes while reporting success.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "livekit_realtime_agent.py"

EDITS: list[tuple[str, str, str]] = []


def patch(marker: str, old: str, new: str) -> None:
    EDITS.append((marker, old, new))


# ---------------------------------------------------------------- 1. Agent
patch(
    "agent constructor takes memory",
    """    def __init__(self, cfg: LiveKitRealtimeConfig) -> None:
        self._cfg = cfg
        super().__init__(
            instructions=cfg.instructions,
            allow_interruptions=True,
        )
""",
    '''    def __init__(self, cfg: LiveKitRealtimeConfig, memory=None) -> None:
        self._cfg = cfg
        self._memory = memory
        instructions = cfg.instructions
        # Durable facts ride along with the personality. Past conversations do
        # not - they are reached with the recall tool, so history cannot drown
        # the directives that make her sound like herself.
        if memory is not None:
            try:
                known = memory.opening_context()
                if known:
                    instructions = f"{instructions}\\n\\n{known}"
                    logger.info("[Memory] session opened with %d remembered fact line(s)",
                                known.count("\\n- "))
            except Exception:
                logger.debug("[Memory] could not load opening context", exc_info=True)
        super().__init__(
            instructions=instructions,
            allow_interruptions=True,
        )

    @function_tool()
    async def recall(self, about: str) -> str:
        """Search your own past conversations with Tommy.

        Use when he refers to something you talked about before - "what did we
        decide about", "you said", "remember when", "what was that thing" - or
        when you need what was agreed earlier to answer properly. Pass what to
        look for in his words. Not for general knowledge.
        """
        if self._memory is None:
            return "I don't have memory wired up in this session."
        try:
            return await asyncio.to_thread(self._memory.recall, about)
        except Exception as exc:
            return f"I couldn't search my memory: {type(exc).__name__}"
''',
)

# ---------------------------------------------- 2. capture committed turns
patch(
    "conversation items reach memory",
    """        voice_events.emit("said", role=str(getattr(item, "role", "?")),
                          text=(getattr(item, "text_content", "") or "")[:600])
""",
    """        voice_events.emit("said", role=str(getattr(item, "role", "?")),
                          text=(getattr(item, "text_content", "") or "")[:600])
        if memory is not None:
            memory.note(str(getattr(item, "role", "")), getattr(item, "text_content", "") or "")
""",
)

patch(
    "activity logger accepts memory",
    "def _log_session_activity(session: AgentSession) -> None:",
    "def _log_session_activity(session: AgentSession, memory=None) -> None:",
)

patch(
    "activity logger is given the memory",
    "    _log_session_activity(session)\n",
    "    _log_session_activity(session, voice_memory)\n",
)

# ------------------------------------------------- 3. build it per session
patch(
    "memory created before shutdown closure",
    """    async def _on_shutdown(reason: str = "") -> None:
""",
    '''    # Built before the shutdown closure so the closure can flush it.
    try:
        from core.voice_memory import VoiceMemory

        voice_memory = VoiceMemory(session_id=str(getattr(job, "id", "") or ""))
        logger.info("[Memory] durable voice memory ready: %s", voice_memory.stats().get("backend"))
    except Exception:
        voice_memory = None
        logger.warning("[Memory] durable memory unavailable for this session", exc_info=True)

    async def _on_shutdown(reason: str = "") -> None:
''',
)

patch(
    "half turns dropped at shutdown",
    """            mark_ended(str(reason or ""))
        except Exception:
            pass
""",
    """            mark_ended(str(reason or ""))
        except Exception:
            pass
        try:
            if voice_memory is not None:
                voice_memory.flush()
                logger.info("[Memory] %s", voice_memory.stats())
        except Exception:
            logger.debug("[Memory] flush failed", exc_info=True)
""",
)

# ------------------------------------------------ 4. hand it to the agent
patch(
    "agent gets memory (both start paths)",
    "            agent=ArgoRealtimeAgent(cfg),",
    "            agent=ArgoRealtimeAgent(cfg, memory=voice_memory),",
)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    original = text
    applied, skipped = [], []

    for marker, old, new in EDITS:
        count = text.count(old)
        if count == 0:
            if new in text:
                skipped.append(f"{marker} (already applied)")
                continue
            print(f"  FAIL  {marker}: anchor not found")
            return 1
        text = text.replace(old, new)
        applied.append(f"{marker} x{count}")

    if text == original:
        print("  nothing to do")
        return 0

    TARGET.write_text(text, encoding="utf-8")

    # Read back from disk. Never trust the write.
    check = TARGET.read_text(encoding="utf-8")
    print("  applied:")
    for item in applied:
        print(f"    + {item}")
    for item in skipped:
        print(f"    = {item}")
    print()
    print("  read-back audit:")
    for probe in (
        "def __init__(self, cfg: LiveKitRealtimeConfig, memory=None)",
        "async def recall(self, about: str)",
        "memory.note(str(getattr(item,",
        "voice_memory = VoiceMemory(session_id=",
        "voice_memory.flush()",
        "ArgoRealtimeAgent(cfg, memory=voice_memory)",
        "_log_session_activity(session, voice_memory)",
    ):
        print(f"    {'OK ' if probe in check else 'MISSING'} {probe}")

    import py_compile

    py_compile.compile(str(TARGET), doraise=True)
    print("    OK  compiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
