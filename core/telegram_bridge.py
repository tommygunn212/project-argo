"""Reach ARGO from anywhere: a Telegram bot that talks to her text brain.

Safe by construction:
  * Outbound only. The bridge long-polls api.telegram.org; nothing on bigdog
    is opened to the internet - no port forwarding, no public dashboard.
  * Allowlist. Only Telegram user ids in config.json -> telegram.allowed_user_ids
    get an answer. Anyone else is told their id and ignored, so Tommy can add
    himself (and Kitty or Jesse) by id.
  * The token lives in .env as TELEGRAM_BOT_TOKEN, never in config.json.

It also carries ARGO's voice out of the house: when no Smooth Voice session is
live, due reminders are sent here instead, and background jobs started by text
report back by text.

Run: .venv\\Scripts\\python.exe telegram_bridge.py   (scripts\\start_argo_stack.ps1 starts it)
Stop: create runtime\\locks\\telegram-bridge.stop - it exits within one poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from core import text_agent

logger = logging.getLogger("ARGO.Telegram")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config.json"
LOCKS = ROOT / "runtime" / "locks"
STOP_FILE = LOCKS / "telegram-bridge.stop"
API = "https://api.telegram.org/bot{token}/{method}"
POLL_SECONDS = 25
MAX_MESSAGE = 4000
REMINDER_CHECK_S = 30


@dataclass(frozen=True)
class BridgeSettings:
    enabled: bool = True
    allowed_user_ids: tuple[int, ...] = ()
    persona: str = "argo"
    model: str = text_agent.DEFAULT_MODEL
    push_reminders: bool = True


def load_settings(config: dict | None = None) -> BridgeSettings:
    if config is None:
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    raw = config.get("telegram") or {}
    ids = []
    for value in raw.get("allowed_user_ids") or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    persona = str(raw.get("persona") or "")
    if not persona:
        try:
            from core.livekit_preferences import read_voice_personality

            persona = read_voice_personality()
        except Exception:
            persona = "argo"
    return BridgeSettings(enabled=bool(raw.get("enabled", True)), allowed_user_ids=tuple(ids),
                          persona=persona, model=str(raw.get("model") or text_agent.DEFAULT_MODEL),
                          push_reminders=bool(raw.get("push_reminders", True)))


def split_message(text: str, limit: int = MAX_MESSAGE) -> list[str]:
    text = text or "(empty)"
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


@dataclass
class Bridge:
    token: str
    settings: BridgeSettings
    http: requests.Session = field(default_factory=requests.Session)
    offset: int = 0
    conversations: dict = field(default_factory=dict)

    def call(self, method: str, timeout: float = 15, **params) -> dict:
        response = self.http.post(API.format(token=self.token, method=method),
                                  json=params, timeout=timeout)
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description', response.status_code)}")
        return data.get("result")

    async def send(self, chat_id, text: str) -> None:
        for part in split_message(text):
            try:
                await asyncio.to_thread(self.call, "sendMessage", chat_id=chat_id, text=part)
            except Exception:
                logger.warning("[Telegram] send failed", exc_info=False)

    def allowed(self, user_id) -> bool:
        return bool(user_id) and int(user_id) in self.settings.allowed_user_ids

    def conversation(self, chat_id) -> text_agent.TextConversation:
        key = str(chat_id)
        if key not in self.conversations:
            self.conversations[key] = text_agent.TextConversation(
                chat_id=key, persona=self.settings.persona, model=self.settings.model)
        return self.conversations[key]

    async def handle(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat_id = (message.get("chat") or {}).get("id")
        user_id = (message.get("from") or {}).get("id")
        if not text or chat_id is None:
            return
        if not self.allowed(user_id):
            logger.info("[Telegram] ignored a message from unlisted user %s", user_id)
            await self.send(chat_id, f"I don't know you yet. Your Telegram id is {user_id} - "
                                     "Tommy can add it to telegram.allowed_user_ids.")
            return
        if text in {"/start", "/id"}:
            await self.send(chat_id, f"ARGO here. Your id is {user_id}. Just text me.")
            return
        with_typing = asyncio.create_task(self._typing(chat_id))
        try:
            answer = await text_agent.reply(
                self.conversation(chat_id), text,
                notify=lambda note, c=chat_id: self.send(c, note))
        finally:
            with_typing.cancel()
        await self.send(chat_id, answer)

    async def _typing(self, chat_id) -> None:
        while True:
            try:
                await asyncio.to_thread(self.call, "sendChatAction", chat_id=chat_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(4)

    async def poll_forever(self) -> None:
        while not STOP_FILE.exists():
            try:
                updates = await asyncio.to_thread(
                    self.call, "getUpdates", POLL_SECONDS + 10,
                    offset=self.offset, timeout=POLL_SECONDS, allowed_updates=["message"])
            except Exception as exc:
                # requests puts the URL - which contains the bot token - in its errors.
                logger.warning("[Telegram] poll failed: %s", str(exc).replace(self.token, "***"))
                await asyncio.sleep(5)
                continue
            for update in updates or []:
                self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                asyncio.create_task(self._safe_handle(update))

    async def _safe_handle(self, update: dict) -> None:
        try:
            await self.handle(update)
        except Exception:
            logger.exception("[Telegram] handling an update failed")

    async def reminders_forever(self) -> None:
        """Due reminders go to Telegram when nobody is in a voice session."""
        owner = self.settings.allowed_user_ids[0] if self.settings.allowed_user_ids else None
        while owner and self.settings.push_reminders and not STOP_FILE.exists():
            try:
                if not voice_session_live():
                    from tools.reminders import get_due_reminders

                    for reminder in await asyncio.to_thread(get_due_reminders):
                        await self.send(owner, f"Reminder: {reminder['message']}")
            except Exception:
                logger.warning("[Telegram] reminder check failed", exc_info=True)
            await asyncio.sleep(REMINDER_CHECK_S)


def voice_session_live() -> bool:
    try:
        from core.voice_active import read_active

        record = read_active() or {}
        return bool(record.get("live"))
    except Exception:
        return False


async def run() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    settings = load_settings()
    if not token:
        logger.info("[Telegram] TELEGRAM_BOT_TOKEN not set; bridge not started")
        return 0
    if not settings.enabled:
        logger.info("[Telegram] telegram.enabled is false; bridge not started")
        return 0
    if not settings.allowed_user_ids:
        logger.warning("[Telegram] no allowed_user_ids yet - the bot will only tell people their id")
    STOP_FILE.unlink(missing_ok=True)
    bridge = Bridge(token=token, settings=settings)
    me = await asyncio.to_thread(bridge.call, "getMe")
    logger.info("[Telegram] bridge up as @%s for %d user(s)", me.get("username"),
                len(settings.allowed_user_ids))
    await asyncio.gather(bridge.poll_forever(), bridge.reminders_forever())
    logger.info("[Telegram] stop file seen; bridge exiting")
    return 0
