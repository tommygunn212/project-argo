"""ARGO speaking first: due reminders, and the morning briefing offer.

Everything else in Smooth Voice waits to be asked. This is the part that
doesn't - the Jarvis/Dot behaviour of "sir, it's time for..." - kept small
and well-behaved:

  * One loop per room session, every ``interval_s`` seconds, cancelled when
    the session ends. It never raises into the session.
  * Due reminders are claimed atomically (tools/reminders.py), so two rooms
    never announce the same one. A reminder that came due while nobody was
    connected is announced at the next session, marked as late.
  * The first session of each day (from 5am) offers the morning briefing in
    one line - it does not recite it unasked.
  * The wake/sleep gate still applies: while ARGO is asleep the gate cuts off
    anything she starts to say, so a reminder never wakes a sleeping house.

config.json -> "proactive": {"enabled": true, "interval_s": 30,
"morning_offer": true}. ARGO_PROACTIVE=0 switches it off.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core import voice_events

logger = logging.getLogger("ARGO.Proactive")

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "config.json"
BRIEFING_MARKER = ROOT / "runtime" / "last_briefing_offer.txt"
LATE_AFTER_MINUTES = 5
MORNING_FROM_HOUR = 5


@dataclass(frozen=True)
class ProactiveSettings:
    enabled: bool = True
    interval_s: float = 30.0
    morning_offer: bool = True
    morning_delay_s: float = 8.0


def load_settings(config: dict | None = None) -> ProactiveSettings:
    if config is None:
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    raw = config.get("proactive") or {}
    base = ProactiveSettings()
    enabled = bool(raw.get("enabled", base.enabled))
    env = os.getenv("ARGO_PROACTIVE")
    if env is not None and env.strip():
        enabled = env.strip().lower() in {"1", "true", "yes", "on"}
    return ProactiveSettings(
        enabled=enabled,
        interval_s=max(5.0, float(raw.get("interval_s") or base.interval_s)),
        morning_offer=bool(raw.get("morning_offer", base.morning_offer)),
        morning_delay_s=float(raw.get("morning_delay_s", base.morning_delay_s)),
    )


def _due_reminders() -> list[dict]:
    from tools.reminders import get_due_reminders

    return get_due_reminders()


def reminder_instruction(reminder: dict, *, now: datetime | None = None) -> str:
    now = now or datetime.now()
    message = str(reminder.get("message", "")).strip()
    late = ""
    try:
        due = datetime.fromisoformat(str(reminder.get("due_at")))
        minutes = int((now - due).total_seconds() // 60)
        if minutes >= LATE_AFTER_MINUTES:
            late = (f" It was due {minutes} minutes ago, while you weren't connected - "
                    "say it's a late reminder.")
    except ValueError:
        pass
    return (f"A reminder Tommy set has come due: \"{message}\". Tell him now, in one "
            f"natural sentence, as yourself - not 'Reminder:'.{late}")


def morning_offer_due(now: datetime | None = None, marker: Path | None = None) -> bool:
    now = now or datetime.now()
    marker = marker or BRIEFING_MARKER
    if now.hour < MORNING_FROM_HOUR:
        return False
    try:
        return marker.read_text(encoding="utf-8").strip() != now.date().isoformat()
    except FileNotFoundError:
        return True
    except Exception:
        return False


def _mark_morning_offer(now: datetime | None = None, marker: Path | None = None) -> None:
    marker = marker or BRIEFING_MARKER
    with contextlib.suppress(Exception):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text((now or datetime.now()).date().isoformat(), encoding="utf-8")


MORNING_INSTRUCTION = (
    "This is your first conversation with Tommy today. In one short line, let him "
    "know his morning briefing is ready whenever he wants it. Do not give the "
    "briefing unless he says yes - then call morning_briefing."
)


async def _say(session, instructions: str) -> bool:
    try:
        session.generate_reply(instructions=instructions, allow_interruptions=True)
        return True
    except Exception:
        logger.debug("[Proactive] could not speak", exc_info=True)
        return False


async def run_loop(session, settings: ProactiveSettings, *, due=_due_reminders,
                   stop: asyncio.Event | None = None) -> None:
    """Check for due reminders until cancelled (or until `stop` is set)."""
    stop = stop or asyncio.Event()
    if settings.morning_offer and morning_offer_due():
        await asyncio.sleep(settings.morning_delay_s)
        if await _say(session, MORNING_INSTRUCTION):
            _mark_morning_offer()
            voice_events.emit("proactive_morning_offer")
    while not stop.is_set():
        try:
            for reminder in await asyncio.to_thread(due):
                logger.info("[Proactive] reminder due: %s", reminder.get("message"))
                voice_events.emit("proactive_reminder", id=reminder.get("id"))
                await _say(session, reminder_instruction(reminder))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[Proactive] reminder check failed", exc_info=True)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.interval_s)


def start_proactive(ctx, session, settings: ProactiveSettings | None = None):
    """Start the loop for this room session; it stops when the room closes."""
    try:
        settings = settings or load_settings()
        if not settings.enabled:
            logger.info("[Proactive] off")
            return None
        task = asyncio.create_task(run_loop(session, settings), name="argo-proactive")

        async def stop_loop(*_):
            task.cancel()
            with contextlib.suppress(BaseException):
                await task

        ctx.add_shutdown_callback(stop_loop)
        logger.info("[Proactive] on (every %.0fs, morning offer %s)",
                    settings.interval_s, settings.morning_offer)
        return task
    except Exception:
        logger.warning("[Proactive] could not start; continuing without it", exc_info=True)
        return None
