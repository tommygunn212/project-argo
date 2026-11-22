"""ARGO by text: the same person, the same memory, the same tools - no microphone.

Smooth Voice is a realtime audio session; it cannot answer a text message
from the street. This is ARGO's brain for typed conversations (the Telegram
bridge, and anything else that sends text): a text model with her persona,
a function-calling loop over the same capabilities the voice agent uses, and
every exchange written to the same memory store, so what Tommy texts is
something voice-ARGO remembers and the other way round.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ARGO.TextAgent")

DEFAULT_MODEL = os.getenv("ARGO_TEXT_MODEL", "gpt-5.5")
MAX_TOOL_ROUNDS = 6
HISTORY_TURNS = 12

TEXT_CHANNEL_NOTE = (
    "THIS CONVERSATION IS BY TEXT MESSAGE, not voice. Tommy is away from the "
    "house, typing on his phone. Reply like a text: short, plain, no markdown "
    "headings, no bullet walls - a few lines at most unless he asks for more. "
    "Everything in your instructions about speech, listening and talking over "
    "him does not apply here; everything about who you are and how you work "
    "does. Use the tools exactly as you would by voice."
)


def _caps():
    from core import realtime_tools

    return realtime_tools


def _recall(about: str) -> dict:
    from core.voice_memory import VoiceMemory

    return {"ok": True, "found": VoiceMemory(session_id="text").recall(about)}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [],
            "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}

# name -> (description, parameters schema, function returning a dict)
TOOLS: dict[str, tuple[str, dict, Callable[..., Any]]] = {
    "what_time_is_it": ("Exact local date and time.", _obj({}), lambda: _caps().now_local()),
    "set_reminder": ("Remind Tommy at a time. when: 'in 20 minutes', 'tomorrow at 9am', or local ISO.",
                     _obj({"message": S, "when": S}, ["message", "when"]),
                     lambda message, when: _caps().reminder_set(message, when)),
    "list_reminders": ("Reminders not yet gone off.", _obj({}), lambda: _caps().reminders_upcoming()),
    "cancel_reminder": ("Cancel the next reminder containing match.", _obj({"match": S}, ["match"]),
                        lambda match: _caps().reminder_cancel(match)),
    "add_calendar_event": ("Add an event to ARGO's calendar.",
                           _obj({"title": S, "when": S, "duration_minutes": I, "location": S},
                                ["title", "when"]),
                           lambda title, when, duration_minutes=60, location="":
                           _caps().calendar_add(title, when, duration_minutes, location)),
    "list_calendar": ("Events for a day ('today', 'friday', ISO) or the next days_ahead days.",
                      _obj({"day": S, "days_ahead": I}),
                      lambda day="", days_ahead=7: _caps().calendar_list(day, days_ahead)),
    "where_we_left_off": ("What was talked about, decided and left open on a day "
                          "('yesterday', 'two days ago', 'thursday').",
                          _obj({"when": S}), lambda when="yesterday": _caps().conversation_recap(when)),
    "whats_pending": ("Open items from the last week plus upcoming reminders and events.",
                      _obj({}), lambda: _caps().pending_items()),
    "mark_pending_done": ("Mark an open item finished.", _obj({"item": S}, ["item"]),
                          lambda item: _caps().pending_done(item)),
    "morning_briefing": ("Today's rundown: calendar, reminders, pending, background jobs, last time.",
                         _obj({}), lambda: _caps().daily_briefing()),
    "recall": ("Search past conversations with Tommy by topic. Use before saying you don't know "
               "something about him.", _obj({"about": S}, ["about"]), _recall),
    "control_smart_home": ("Lights and other Home Assistant devices, in plain words "
                           "('turn off the living room light').",
                           _obj({"command": S}, ["command"]),
                           lambda command: _caps().smart_home_command(command)),
    "list_air_conditioners": ("The GE air conditioners and their state.", _obj({}),
                              lambda: _caps().ac_list()),
    "control_ac": ("Air conditioner: power on/off, temperature_f 60-86 (0 = leave), mode, fan.",
                   _obj({"name": S, "power": S, "temperature_f": I, "mode": S, "fan": S}, ["name"]),
                   lambda name, power="", temperature_f=0, mode="", fan="":
                   _caps().ac_control(name, power, temperature_f, mode, fan)),
    "get_system_status": ("bigdog's health: CPU, memory, uptime.", _obj({}),
                          lambda: _caps().system_status()),
    "search_knowledge_base": ("Tommy's own written knowledge base.", _obj({"query": S}, ["query"]),
                              lambda query: _caps().rag_search(query)),
    "check_background_tasks": ("Background agent jobs and their results.", _obj({"job_id": S}),
                               lambda job_id="": __import__("core.delegate_jobs",
                                                            fromlist=["x"]).status(job_id)),
}

DELEGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_task",
        "description": ("Hand a real job to the background agent: web research, finding or "
                        "downloading files, writing documents or scripts, multi-step errands. "
                        "Use it instead of saying you can't. Returns at once; Tommy gets a "
                        "message when it finishes."),
        "parameters": _obj({"task": S, "folder": S}, ["task"]),
    },
}


def tool_specs() -> list[dict]:
    specs = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}}
             for n, (d, p, _f) in TOOLS.items()]
    return specs + [DELEGATE_TOOL]


Notify = Callable[[str], Awaitable[None]]


@dataclass
class TextConversation:
    """One person's text thread with ARGO."""

    chat_id: str
    persona: str = "argo"
    model: str = DEFAULT_MODEL
    history: list[dict] = field(default_factory=list)


def _instructions(persona: str) -> str:
    from core.persona_briefs import compose_instructions

    return compose_instructions(persona, deep_think=False) + "\n\n" + TEXT_CHANNEL_NOTE


async def _run_tool(name: str, raw_args: str, notify: Notify | None) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except ValueError:
        args = {}
    try:
        if name == "delegate_task":
            from core import delegate_jobs

            async def done(job) -> None:
                if notify is None:
                    return
                if job.status == "done":
                    await notify(f"Done: {job.task[:120]}\n\n{job.summary[:3000]}")
                else:
                    await notify(f"That job didn't finish ({job.status}): {job.error[:300]}")

            result = await delegate_jobs.start(args.get("task", ""), args.get("folder", ""),
                                               on_done=done)
        elif name in TOOLS:
            result = await asyncio.to_thread(TOOLS[name][2], **args)
        else:
            result = {"ok": False, "error": f"unknown tool {name}"}
    except Exception as exc:
        logger.warning("[TextAgent] tool %s failed", name, exc_info=True)
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        from core.voice.action_log import record

        record(name, args, result, room="text")
    except Exception:
        pass
    return json.dumps(result, default=str)[:12000]


def _client():
    from openai import AsyncOpenAI

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    return AsyncOpenAI()


async def reply(conv: TextConversation, text: str, *, notify: Notify | None = None,
                client=None) -> str:
    """ARGO's answer to one text message. Never raises."""
    try:
        client = client or _client()
        messages = [{"role": "system", "content": _instructions(conv.persona)}]
        messages += conv.history[-HISTORY_TURNS * 2:]
        messages.append({"role": "user", "content": text})
        answer = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=conv.model, messages=messages, tools=tool_specs())
            msg = response.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                answer = (msg.content or "").strip()
                break
            messages.append({"role": "assistant", "content": msg.content or "",
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.function.name,
                                                          "arguments": c.function.arguments}}
                                            for c in calls]})
            for call in calls:
                output = await _run_tool(call.function.name, call.function.arguments, notify)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
        else:
            answer = "That took more steps than I'm allowed in one go - ask me again more simply?"
        answer = answer or "Done."
    except Exception as exc:
        logger.warning("[TextAgent] reply failed", exc_info=True)
        return f"I couldn't think that through just now ({type(exc).__name__})."
    conv.history += [{"role": "user", "content": text}, {"role": "assistant", "content": answer}]
    conv.history = conv.history[-HISTORY_TURNS * 2:]
    _remember(text, answer)
    return answer


def _remember(text: str, answer: str) -> None:
    """Texts go in the same memory as speech, so voice-ARGO knows about them."""
    try:
        from core.memory_store import get_memory_store

        get_memory_store().add_turn(text, answer, source="telegram")
    except Exception:
        logger.debug("[TextAgent] could not save the exchange", exc_info=True)
