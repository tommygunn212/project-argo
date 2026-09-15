"""The deep-thinking half of ARGO's brain.

The realtime model is fast because it answers from the audio stream. That is
exactly what you want for conversation and exactly what you do not want when
Tommy asks something that deserves real work - a plan, a comparison, a bug,
a design. Those go to a bigger text model with the conversation so far, and
the spoken answer is ARGO reading back what it found, in her own voice.

Two rules shape everything here.

  1. It must be cancellable the instant he speaks again. A deep answer that
     arrives after he has moved on is worse than no answer: it talks over the
     new thought. Every request runs under a task that `cancel_all()` kills.

  2. It must never take voice down with it. A timeout, a bad key, a model
     that does not exist - all of them come back as a short spoken line ARGO
     can say, never as an exception into the session.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger("ARGO.DeepThink")

# How much of the conversation travels with the question. Enough for the model
# to know what "it" and "that approach" refer to, not so much that the handoff
# costs more than the thinking.
CONTEXT_TURNS = 12
CONTEXT_CHARS = 6000

SYSTEM_PROMPT = (
    "You are the reasoning half of ARGO, a voice assistant talking with Tommy. "
    "He asked something that needs real work, so the fast conversational model "
    "handed it to you. Think it through properly.\n\n"
    "Your answer will be READ ALOUD by the conversational model, so write it "
    "the way a sharp person would say it out loud: no headings, no bullet "
    "lists, no markdown, no numbered steps unless the steps genuinely are the "
    "answer and there are few of them. Lead with the conclusion, then the "
    "reasoning that actually carries weight. Name the tradeoff you would worry "
    "about. If the question has a wrong premise, say so first.\n\n"
    "Length: as long as the problem needs and no longer. Most answers should "
    "be under 200 words spoken. Do not pad, do not restate the question, do "
    "not describe your process."
)


@dataclass
class DeepThinkResult:
    ok: bool
    text: str
    model: str
    elapsed_ms: int
    cancelled: bool = False
    error: str = ""


@dataclass
class _State:
    tasks: set = field(default_factory=set)
    last_started: float = 0.0
    last_cancelled: float = 0.0
    in_flight: int = 0


_state = _State()


def is_thinking() -> bool:
    """True while a deep request is actually outstanding.

    The dashboard reads this to show Deep Think rather than asking Tommy to
    track which model is answering.
    """
    return _state.in_flight > 0


def cancel_all(reason: str = "user_spoke") -> int:
    """Kill every outstanding deep request. Returns how many were killed.

    Called the moment Tommy starts speaking. Cancelling nothing is the normal
    case and costs nothing, so callers never have to check first.
    """
    killed = 0
    for task in list(_state.tasks):
        if not task.done():
            task.cancel()
            killed += 1
    _state.tasks.clear()
    if killed:
        _state.last_cancelled = time.time()
        logger.info("[DeepThink] cancelled %d in-flight request(s): %s", killed, reason)
    return killed


def _trim_context(history: Iterable[dict] | None) -> list[dict]:
    """The tail of the conversation, oldest first, inside a character budget."""
    if not history:
        return []
    turns = [
        {"role": ("assistant" if str(h.get("role")) == "assistant" else "user"),
         "content": str(h.get("text") or h.get("content") or "").strip()}
        for h in history
    ]
    turns = [t for t in turns if t["content"]][-CONTEXT_TURNS:]

    total = 0
    kept: list[dict] = []
    for turn in reversed(turns):
        total += len(turn["content"])
        if total > CONTEXT_CHARS and kept:
            break
        kept.append(turn)
    kept.reverse()
    return kept


async def think(
    question: str,
    *,
    history: Iterable[dict] | None = None,
    model: str = "gpt-5.5",
    timeout: float = 90.0,
    persona: str | None = None,
) -> DeepThinkResult:
    """Answer `question` with the deep model, carrying the conversation.

    Never raises. Cancellation returns a result with cancelled=True and empty
    text, which the caller should say nothing about - he already moved on.
    """
    started = time.time()
    question = (question or "").strip()
    if not question:
        return DeepThinkResult(False, "", model, 0, error="empty question")

    task = asyncio.current_task()
    if task is not None:
        _state.tasks.add(task)
    _state.in_flight += 1
    _state.last_started = started

    try:
        # Same person, thinking longer. The persona's voice and collaboration
        # style ride along so the answer read back aloud is still HER answer.
        from core.persona_briefs import deep_think_system_prompt

        messages = [{"role": "system", "content": deep_think_system_prompt(persona)}]
        messages.extend(_trim_context(history))
        messages.append({"role": "user", "content": question})

        logger.info(
            "[DeepThink] model=%s persona=%s context_turns=%d question=%r",
            model, persona or "argo", len(messages) - 2, question[:160],
        )
        text = await asyncio.wait_for(_call_openai(messages, model), timeout=timeout)
        elapsed = int((time.time() - started) * 1000)
        logger.info("[DeepThink] answered in %dms (%d chars)", elapsed, len(text))
        return DeepThinkResult(True, text, model, elapsed)

    except asyncio.CancelledError:
        elapsed = int((time.time() - started) * 1000)
        logger.info("[DeepThink] cancelled after %dms - Tommy spoke again", elapsed)
        return DeepThinkResult(False, "", model, elapsed, cancelled=True)

    except asyncio.TimeoutError:
        elapsed = int((time.time() - started) * 1000)
        logger.warning("[DeepThink] timed out after %dms", elapsed)
        return DeepThinkResult(
            False, "", model, elapsed,
            error=f"the deep model took longer than {timeout:.0f} seconds",
        )

    except Exception as exc:
        elapsed = int((time.time() - started) * 1000)
        logger.exception("[DeepThink] failed")
        return DeepThinkResult(False, "", model, elapsed, error=f"{type(exc).__name__}: {exc}")

    finally:
        _state.in_flight = max(0, _state.in_flight - 1)
        if task is not None:
            _state.tasks.discard(task)


async def _call_openai(messages: list[dict], model: str) -> str:
    """One completion from the deep model. Split out so tests can replace it."""
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = AsyncOpenAI(api_key=api_key)
    try:
        response = await client.chat.completions.create(model=model, messages=messages)
        return (response.choices[0].message.content or "").strip()
    finally:
        try:
            await client.close()
        except Exception:
            pass


def spoken_failure(result: DeepThinkResult) -> str:
    """One short line ARGO can say when the deep model did not come back.

    Never a stack trace, never an apology loop - just enough that he knows it
    failed and can decide whether to ask again.
    """
    if result.cancelled:
        return ""
    if "longer than" in result.error:
        return "That one's taking too long to work through - want me to keep going on it?"
    return "I couldn't get the deep model to answer that one just now."
