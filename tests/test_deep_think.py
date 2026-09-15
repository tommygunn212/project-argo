"""The deep-thinking handoff, and the one rule that makes it usable.

GPT-5.5 is slow on purpose - it is for planning, debugging and comparing, not
for "what time is it". The risk that comes with slow is an answer arriving
after Tommy has moved on and talking over the thought he moved on TO. So the
rule these tests exist for is: the instant he speaks again, the in-flight
request dies and says nothing.
"""

import asyncio

import pytest

from core import deep_think


@pytest.fixture(autouse=True)
def quiet_state():
    deep_think.cancel_all(reason="test setup")
    yield
    deep_think.cancel_all(reason="test teardown")


def _stub(monkeypatch, text="the considered answer", delay=0.0):
    async def fake(messages, model):
        if delay:
            await asyncio.sleep(delay)
        fake.seen = messages
        return text
    fake.seen = None
    monkeypatch.setattr(deep_think, "_call_openai", fake)
    return fake


# --- it answers -----------------------------------------------------------

def test_a_question_comes_back_answered(monkeypatch):
    _stub(monkeypatch)
    result = asyncio.run(deep_think.think("how should I structure the worker?"))
    assert result.ok and result.text == "the considered answer"
    assert result.elapsed_ms >= 0 and not result.cancelled


def test_the_conversation_travels_with_the_question(monkeypatch):
    """Without context, "would that still work" is unanswerable."""
    fake = _stub(monkeypatch)
    history = [
        {"role": "user", "text": "I'm thinking of moving the worker off-box"},
        {"role": "assistant", "text": "That would cost you the local LiveKit hop"},
    ]
    asyncio.run(deep_think.think("would that still work?", history=history))

    roles = [m["role"] for m in fake.seen]
    assert roles[0] == "system"
    assert "moving the worker off-box" in fake.seen[1]["content"]
    assert fake.seen[-1]["content"] == "would that still work?"


def test_context_is_trimmed_not_unbounded(monkeypatch):
    fake = _stub(monkeypatch)
    history = [{"role": "user", "text": f"turn {i} " + "x" * 400} for i in range(60)]
    asyncio.run(deep_think.think("so?", history=history))
    assert len(fake.seen) <= deep_think.CONTEXT_TURNS + 2
    assert sum(len(m["content"]) for m in fake.seen[1:-1]) <= deep_think.CONTEXT_CHARS + 400


def test_it_is_told_to_write_for_the_ear():
    """The answer gets read aloud, so markdown and bullet lists are wrong."""
    prompt = deep_think.SYSTEM_PROMPT.lower()
    assert "read aloud" in prompt
    assert "no markdown" in prompt and "no bullet" in prompt


# --- it stops the moment he speaks ----------------------------------------

def test_speaking_again_kills_the_request(monkeypatch):
    _stub(monkeypatch, delay=30)

    async def scenario():
        task = asyncio.ensure_future(deep_think.think("something hard", timeout=30))
        await asyncio.sleep(0.3)
        assert deep_think.is_thinking(), "should be outstanding before cancelling"
        killed = deep_think.cancel_all(reason="user_started_speaking")
        return killed, await task

    killed, result = asyncio.run(scenario())
    assert killed == 1
    assert result.cancelled and result.ok is False


def test_a_cancelled_request_says_nothing(monkeypatch):
    """Anything spoken here would talk over the thought that cancelled it."""
    _stub(monkeypatch, delay=30)

    async def scenario():
        task = asyncio.ensure_future(deep_think.think("hard", timeout=30))
        await asyncio.sleep(0.2)
        deep_think.cancel_all()
        return await task

    assert deep_think.spoken_failure(asyncio.run(scenario())) == ""


def test_cancelling_nothing_is_harmless():
    assert deep_think.cancel_all(reason="nothing in flight") == 0


def test_the_flag_clears_after_a_normal_answer(monkeypatch):
    _stub(monkeypatch)
    asyncio.run(deep_think.think("quick one"))
    assert deep_think.is_thinking() is False


# --- failure never reaches the session as an exception --------------------

def test_a_timeout_becomes_a_line_she_can_say(monkeypatch):
    _stub(monkeypatch, delay=5)
    result = asyncio.run(deep_think.think("hard", timeout=0.2))
    assert result.ok is False and not result.cancelled
    spoken = deep_think.spoken_failure(result)
    assert spoken and "Traceback" not in spoken


def test_a_broken_model_becomes_a_line_she_can_say(monkeypatch):
    async def boom(messages, model):
        raise RuntimeError("model not found")
    monkeypatch.setattr(deep_think, "_call_openai", boom)

    result = asyncio.run(deep_think.think("anything"))
    assert result.ok is False
    assert "model not found" in result.error
    assert deep_think.spoken_failure(result)


def test_an_empty_question_is_refused_without_calling_the_model(monkeypatch):
    fake = _stub(monkeypatch)
    assert asyncio.run(deep_think.think("   ")).ok is False
    assert fake.seen is None
