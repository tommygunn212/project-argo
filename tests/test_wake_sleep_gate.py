"""
Tests for the phrase gates in core/voice/phrase_gates.py.

No LiveKit connection involved - AgentSession is faked with a minimal
double that supports .on(name, cb), .interrupt(), .generate_reply(), and a
settable .agent_state, which is all the gates touch. The real
module is imported for real (not reimplemented here), so these exercise the
actual gate logic that will run live.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.voice import phrase_gates as gates
from core.livekit_config import LiveKitRealtimeConfig


class FakeEvent:
    def __init__(self, transcript=None, is_final=None, new_state=None):
        if transcript is not None:
            self.transcript = transcript
        if is_final is not None:
            self.is_final = is_final
        if new_state is not None:
            self.new_state = new_state


class FakeSession:
    """Just enough of AgentSession for the gate to wire itself onto."""

    def __init__(self):
        self._handlers = {}
        self.agent_state = "listening"
        self.interrupt = MagicMock()
        self.generate_reply = MagicMock()

    def on(self, name, callback):
        self._handlers.setdefault(name, []).append(callback)

    def fire(self, name, event):
        for cb in self._handlers.get(name, []):
            cb(event)


def make_cfg(**overrides):
    base = dict(
        enabled=True, url="ws://x", api_key="k", api_secret="s", room="r",
        agent_name="a", model="m", voice="v", instructions="i", greeting="",
        temperature=0.6, speed=1.0, token_ttl_minutes=60,
        min_interruption_duration=0.35, false_interruption_timeout=1.2,
        speaker_id_enabled=False, speaker_id_provider="speechmatics",
        wake_sleep_gate_enabled=True,
        sleep_phrases=("go to sleep",),
        wake_phrases=("hey argo",),
        wake_ack_enabled=False,
    )
    base.update(overrides)
    return LiveKitRealtimeConfig(**base)


class TestWakeSleepGateDisabledByDefault(unittest.TestCase):
    def test_default_config_has_gate_off(self):
        cfg = make_cfg(wake_sleep_gate_enabled=False)
        session = FakeSession()
        gates.wire_wake_sleep_gate(session, cfg)
        self.assertEqual(session._handlers, {}, "disabled gate must register no handlers")


class TestWakeSleepGateBehavior(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.session = FakeSession()
        with patch("core.voice_events.emit"):
            gates.wire_wake_sleep_gate(self.session, self.cfg)

    def _interim(self, text):
        self.session.fire("user_input_transcribed", FakeEvent(transcript=text, is_final=False))

    def _final(self):
        self.session.fire("user_input_transcribed", FakeEvent(transcript="", is_final=True))

    def test_sleep_phrase_while_speaking_interrupts_immediately(self):
        self.session.agent_state = "speaking"
        with patch("core.voice_events.emit") as mock_emit:
            self._interim("go to sleep")
        self.session.interrupt.assert_called_once()
        mock_emit.assert_any_call("sleep_word_triggered", phrase="go to sleep", transcript="go to sleep")

    def test_sleep_phrase_while_not_speaking_does_not_interrupt(self):
        self.session.agent_state = "listening"
        with patch("core.voice_events.emit"):
            self._interim("go to sleep")
        self.session.interrupt.assert_not_called()

    def test_unrelated_speech_does_not_trigger_sleep(self):
        self.session.agent_state = "speaking"
        with patch("core.voice_events.emit") as mock_emit:
            self._interim("what's the weather like")
        self.session.interrupt.assert_not_called()
        mock_emit.assert_not_called()

    def test_wake_phrase_ignored_while_awake(self):
        with patch("core.voice_events.emit") as mock_emit:
            self._interim("hey argo")
        mock_emit.assert_not_called()

    def test_full_sleep_then_wake_cycle(self):
        with patch("core.voice_events.emit") as mock_emit:
            self._interim("go to sleep")
            self._final()
            self._interim("hey argo")
        mock_emit.assert_any_call("sleep_word_triggered", phrase="go to sleep", transcript="go to sleep")
        mock_emit.assert_any_call("wake_word_triggered", phrase="hey argo", transcript="hey argo")
        self.session.generate_reply.assert_not_called()

    def test_reply_started_while_asleep_is_interrupted(self):
        with patch("core.voice_events.emit"):
            self._interim("go to sleep")
        self.session.interrupt.reset_mock()
        with patch("core.voice_events.emit") as mock_emit:
            self.session.fire("agent_state_changed", FakeEvent(new_state="speaking"))
        self.session.interrupt.assert_called_once()
        mock_emit.assert_any_call("wake_sleep_suppressed_reply")

    def test_agent_state_change_while_awake_is_ignored(self):
        with patch("core.voice_events.emit") as mock_emit:
            self.session.fire("agent_state_changed", FakeEvent(new_state="speaking"))
        self.session.interrupt.assert_not_called()
        mock_emit.assert_not_called()

    def test_double_fire_on_same_interim_transcript_only_acts_once(self):
        self.session.agent_state = "speaking"
        with patch("core.voice_events.emit"):
            self._interim("go to sleep")
            self.session.interrupt.reset_mock()
            self._interim("go to sleep now please")
        self.session.interrupt.assert_not_called()


class TestWakeAckConfigurable(unittest.TestCase):
    def test_wake_ack_enabled_calls_generate_reply(self):
        cfg = make_cfg(wake_ack_enabled=True)
        session = FakeSession()
        with patch("core.voice_events.emit"):
            gates.wire_wake_sleep_gate(session, cfg)
            session.fire("user_input_transcribed", FakeEvent(transcript="go to sleep", is_final=False))
            session.fire("user_input_transcribed", FakeEvent(transcript="", is_final=True))
            session.fire("user_input_transcribed", FakeEvent(transcript="hey argo", is_final=False))
        session.generate_reply.assert_called_once()


class TestOpeningPhrase(unittest.TestCase):
    def test_phrase_must_open_the_utterance(self):
        self.assertEqual(gates.opening_phrase("Stop!", ("stop",)), "stop")
        self.assertEqual(gates.opening_phrase("stop talking", ("stop",)), "stop")
        self.assertIsNone(gates.opening_phrase("don't stop the music", ("stop",)))
        self.assertIsNone(gates.opening_phrase("stopwatch", ("stop",)))
        self.assertIsNone(gates.opening_phrase("", ("stop",)))


class TestUrgentInterrupts(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        gates.wire_urgent_interrupts(self.session, make_cfg(urgent_interrupt_phrases=("stop",)))

    def _interim(self, text):
        self.session.fire("user_input_transcribed", FakeEvent(transcript=text, is_final=False))

    def test_interrupts_only_while_speaking(self):
        with patch("core.voice_events.emit"):
            self._interim("stop")
        self.session.interrupt.assert_not_called()
        self.session.agent_state = "speaking"
        with patch("core.voice_events.emit"):
            self._interim("stop")
        self.session.interrupt.assert_called_once()

    def test_acts_once_per_utterance_and_rearms_on_final(self):
        self.session.agent_state = "speaking"
        with patch("core.voice_events.emit"):
            self._interim("stop")
            self._interim("stop talking")
            self.assertEqual(self.session.interrupt.call_count, 1)
            self.session.fire("user_input_transcribed", FakeEvent(transcript="stop talking", is_final=True))
            self._interim("stop")
        self.assertEqual(self.session.interrupt.call_count, 2)

    def test_no_phrases_registers_nothing(self):
        session = FakeSession()
        gates.wire_urgent_interrupts(session, make_cfg(urgent_interrupt_phrases=()))
        self.assertEqual(session._handlers, {})


if __name__ == "__main__":
    unittest.main()
