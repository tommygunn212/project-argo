"""ARGO by text: the text brain's tool loop, and the Telegram bridge's guard rails."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from core import telegram_bridge as TB
from core import text_agent as TA


# --- fake OpenAI ---------------------------------------------------------------------

def _msg(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=content, tool_calls=calls))])


def _call(name, args, cid="c1"):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.seen = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.seen.append(kwargs)
        return self.scripted.pop(0)


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    monkeypatch.setattr(TA, "_remember", lambda text, answer: None)
    import core.voice.action_log as AL
    monkeypatch.setattr(AL, "record", lambda *a, **k: None)


def test_a_plain_answer(monkeypatch):
    conv = TA.TextConversation(chat_id="1")
    client = FakeClient([_msg("Kettle's on, guv.")])
    answer = asyncio.run(TA.reply(conv, "you up?", client=client))
    assert answer == "Kettle's on, guv."
    system = client.seen[0]["messages"][0]["content"]
    assert "TEXT MESSAGE" in system and "WHAT YOU ALREADY KNOW ABOUT TOMMY" in system
    assert len(conv.history) == 2


def test_tools_run_and_their_results_go_back_to_the_model(monkeypatch):
    seen = {}
    monkeypatch.setitem(TA.TOOLS, "what_time_is_it",
                        ("time", TA._obj({}), lambda: seen.setdefault("called", True) and
                         {"ok": True, "spoken": "Sunday 5:30 AM"}))
    client = FakeClient([_msg(calls=[_call("what_time_is_it", {})]), _msg("It's half five.")])
    answer = asyncio.run(TA.reply(TA.TextConversation(chat_id="1"), "time?", client=client))
    assert answer == "It's half five." and seen["called"]
    tool_msg = client.seen[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "Sunday 5:30 AM" in tool_msg["content"]


def test_delegate_reports_back_by_text(monkeypatch):
    from core import delegate_jobs

    notes = []

    async def fake_start(task, folder="", *, on_done=None, settings=None):
        await on_done(SimpleNamespace(status="done", task=task, summary="Saved cup_holder.stl", error=""))
        return {"ok": True, "job_id": "j1"}

    async def notify(text):
        notes.append(text)

    monkeypatch.setattr(delegate_jobs, "start", fake_start)
    client = FakeClient([_msg(calls=[_call("delegate_task", {"task": "find a skadis cup holder"})]),
                         _msg("On it.")])
    asyncio.run(TA.reply(TA.TextConversation(chat_id="1"), "find one", client=client, notify=notify))
    assert notes and "cup_holder.stl" in notes[0]


def test_a_broken_model_never_raises():
    class Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

    async def explode(**kwargs):
        raise RuntimeError("api down")

    Boom.chat.completions.create = explode
    answer = asyncio.run(TA.reply(TA.TextConversation(chat_id="1"), "hi", client=Boom()))
    assert "couldn't" in answer


def test_every_tool_spec_is_well_formed():
    names = [s["function"]["name"] for s in TA.tool_specs()]
    assert len(names) == len(set(names)) and "delegate_task" in names
    for spec in TA.tool_specs():
        assert spec["function"]["parameters"]["type"] == "object"


# --- telegram bridge -----------------------------------------------------------------

def _bridge(monkeypatch, allowed=(42,)):
    sent = []
    bridge = TB.Bridge(token="123:SECRET", settings=TB.BridgeSettings(allowed_user_ids=tuple(allowed)))
    monkeypatch.setattr(bridge, "call", lambda method, timeout=15, **p: sent.append((method, p)) or {})
    return bridge, sent


def _update(user_id, text):
    return {"update_id": 1, "message": {"text": text, "chat": {"id": 7}, "from": {"id": user_id}}}


def test_strangers_get_their_id_and_nothing_else(monkeypatch):
    bridge, sent = _bridge(monkeypatch)
    called = []

    async def never(*a, **k):
        called.append(1)
        return "x"

    monkeypatch.setattr(TB.text_agent, "reply", never)
    asyncio.run(bridge.handle(_update(999, "turn off the AC")))
    texts = [p["text"] for m, p in sent if m == "sendMessage"]
    assert called == [] and "999" in texts[0]


def test_the_owner_gets_an_answer(monkeypatch):
    bridge, sent = _bridge(monkeypatch)

    async def answer(conv, text, notify=None, client=None):
        return f"echo {text}"

    monkeypatch.setattr(TB.text_agent, "reply", answer)
    asyncio.run(bridge.handle(_update(42, "status?")))
    assert ("sendMessage", {"chat_id": 7, "text": "echo status?"}) in sent


def test_long_replies_are_split_under_telegrams_limit():
    parts = TB.split_message("line\n" * 2000)
    assert len(parts) > 1 and all(len(p) <= TB.MAX_MESSAGE for p in parts)


def test_settings_and_no_token_means_no_bridge(monkeypatch):
    s = TB.load_settings({"telegram": {"allowed_user_ids": ["42", "x", 7], "persona": "cockney"}})
    assert s.allowed_user_ids == (42, 7) and s.persona == "cockney"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert asyncio.run(TB.run()) == 0


def test_reminders_stay_in_the_room_while_a_voice_session_is_live(monkeypatch):
    bridge, sent = _bridge(monkeypatch)
    monkeypatch.setattr(TB, "voice_session_live", lambda: True)
    claimed = []
    import tools.reminders as R
    monkeypatch.setattr(R, "get_due_reminders", lambda: claimed.append(1) or [])

    async def one_round():
        task = asyncio.create_task(bridge.reminders_forever())
        await asyncio.sleep(0.2)
        task.cancel()
    asyncio.run(one_round())
    assert claimed == []
