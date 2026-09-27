"""ArgoRealtimeAgent: ARGO as the realtime model sees her.

Her instructions are assembled once, in core.persona_briefs via
core.livekit_config, and handed here whole. The capability tools come from
core.voice.tools; the three tools defined here are the ones that need the
agent's own state - memory, the live session history, the repair bridge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from pathlib import Path

from livekit.agents import Agent, function_tool

from core import deep_think, voice_events
from core.livekit_config import LiveKitRealtimeConfig
from core.voice.tools import CapabilityTools

logger = logging.getLogger("ARGO.LiveKit")

ROOT = Path(__file__).resolve().parents[2]
REPAIR_TOKEN_FILE = ROOT / "runtime" / "repair_bridge.token"
REPAIR_TIMEOUT_S = 90
DEEP_THINK_HISTORY_TURNS = 24


def _post_repair_request(text: str) -> str:
    """Hand a repair request to the backend's /api/repair-voice bridge."""
    token = REPAIR_TOKEN_FILE.read_text(encoding="utf-8")
    port = int(os.getenv("ARGO_HTTP_PORT", "8000"))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/repair-voice",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json", "X-Argo-Repair": token},
    )
    with urllib.request.urlopen(request, timeout=REPAIR_TIMEOUT_S) as response:
        return response.read().decode()


class ArgoRealtimeAgent(CapabilityTools, Agent):
    """ARGO's realtime agent: one per room session."""

    def __init__(self, cfg: LiveKitRealtimeConfig, memory=None) -> None:
        self._cfg = cfg
        self._memory = memory
        super().__init__(instructions=self._opening_instructions(cfg, memory),
                         allow_interruptions=True)

    @staticmethod
    def _opening_instructions(cfg: LiveKitRealtimeConfig, memory) -> str:
        """The persona instructions plus any explicitly confirmed facts.

        Past conversations are deliberately NOT included - they are reached
        with the recall tool, so history cannot drown the directives that make
        her sound like herself (AGENTS.md invariant 3).
        """
        if memory is None:
            return cfg.instructions
        try:
            known = memory.opening_context()
        except Exception:
            logger.debug("[Memory] could not load opening context", exc_info=True)
            return cfg.instructions
        if not known:
            return cfg.instructions
        logger.info("[Memory] session opened with %d remembered fact line(s)",
                    known.count("\n- "))
        return f"{cfg.instructions}\n\n{known}"

    @function_tool()
    async def recall(self, about: str) -> str:
        """Search your own past conversations with Tommy.

        Call this BEFORE telling him you don't know, don't have, or don't
        remember something about him - not only when he says "remember
        when" or "what did we decide." The trigger is not a phrase, it's a
        gap: any question about a fact, preference, or detail of his life
        that isn't already sitting in your instructions ("what's my
        favorite color", "what did I say about the dog") means check here
        first, because it may well be sitting in a past turn even though
        it never became a standing fact. Only skip this for general
        knowledge that has nothing to do with him or a past conversation.
        Pass what to look for in his words.
        """
        if self._memory is None:
            return "I don't have memory wired up in this session."
        logger.info("[Recall] tool invoked: about=%r", about)
        try:
            result = await asyncio.to_thread(self._memory.recall, about)
        except Exception as exc:
            logger.warning("[Recall] tool failed", exc_info=True)
            return f"I couldn't search my memory: {type(exc).__name__}"
        logger.info("[Recall] tool returned %d char(s)", len(result))
        # Remembered text stays out of INFO logs; DEBUG is for proving a round trip.
        logger.debug("[Recall] result preview: %r", result[:200])
        return result

    @function_tool()
    async def repair_argo(self, text: str) -> str:
        """Run ARGO's diagnostic/repair conversation using the user's verbatim request.

        Pass explicit 'approve repair', 'cancel repair', 'repair status', or
        'prepare code repair' only when the user actually says those words.
        """
        try:
            return await asyncio.to_thread(_post_repair_request, text)
        except Exception as exc:
            return json.dumps({
                "status": "unavailable",
                "message": f"ARGO repair service could not be reached: {type(exc).__name__}. "
                           "Open System in the dashboard.",
            })

    @function_tool()
    async def think_deeply(self, question: str) -> str:
        """Work a hard question through properly with the deep reasoning model.

        Use for planning, research, debugging, comparing options, designing
        something, or any question where answering fast would answer worse.
        Pass the question in Tommy's own words. Not for ordinary conversation
        or quick facts.
        """
        cfg = self._cfg
        if not cfg.deep_think_enabled:
            return json.dumps({"ok": False, "message": "Deep thinking is switched off."})

        voice_events.emit("deep_think_start", question=question[:200], model=cfg.deep_think_model)
        result = await deep_think.think(
            question,
            history=self._recent_history(),
            model=cfg.deep_think_model,
            timeout=cfg.deep_think_timeout,
            persona=cfg.personality,
        )
        voice_events.emit("deep_think_done", ok=result.ok, cancelled=result.cancelled,
                          elapsed_ms=result.elapsed_ms, error=result.error)

        if result.cancelled:
            # He started talking again. Saying anything here would talk over
            # the thought that cancelled this one.
            return json.dumps({"ok": False, "cancelled": True, "message": ""})
        if not result.ok:
            return json.dumps({"ok": False, "message": deep_think.spoken_failure(result)})
        return json.dumps({"ok": True, "answer": result.text, "model": result.model,
                           "elapsed_ms": result.elapsed_ms})

    def _recent_history(self) -> list[dict]:
        """The last few spoken turns, so the deep model knows what "that" means."""
        history = []
        try:
            items = list(getattr(self.session.history, "items", []) or [])
        except Exception:
            logger.debug("[DeepThink] could not read session history", exc_info=True)
            return history
        for item in items[-DEEP_THINK_HISTORY_TURNS:]:
            text = (getattr(item, "text_content", "") or "").strip()
            if text:
                history.append({"role": getattr(item, "role", "user"), "text": text})
        return history
