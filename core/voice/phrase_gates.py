"""Phrases that act on ARGO the instant they are heard.

Both gates here watch *interim* transcripts, so they fire while Tommy is still
speaking instead of after the realtime model has decided his turn is over.
They share one rule and one piece of bookkeeping:

* A phrase counts only when it OPENS the utterance. "Stop" and "stop talking"
  fire; "don't stop the music" does not. That is the whole safety margin - a
  gate that fired on any occurrence of "wait" would cut ARGO off constantly.
* A gate acts at most once per utterance. Interims grow ("stop", "stop tal",
  "stop talking"), so each one after the first is ignored until the final
  transcript re-arms the gate.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from livekit.agents import AgentSession

from core import voice_events
from core.livekit_config import LiveKitRealtimeConfig

logger = logging.getLogger("ARGO.LiveKit")

_PUNCTUATION = str.maketrans("", "", ".,!?;:\"'")

WAKE_ACK_INSTRUCTIONS = (
    "Acknowledge you are listening again, one or two words only, nothing more."
)


def opening_phrase(transcript: str, phrases: Iterable[str]) -> str | None:
    """The phrase this transcript opens with, or None.

    Case and punctuation are ignored; the phrase must be the whole utterance
    or be followed by a space.
    """
    text = (transcript or "").strip().lower().translate(_PUNCTUATION)
    if not text:
        return None
    for phrase in phrases:
        if text == phrase or text.startswith(phrase + " "):
            return phrase
    return None


class _OncePerUtterance:
    """Lets a gate act on the first matching interim of an utterance only."""

    def __init__(self) -> None:
        self._acted_on = ""

    def candidate(self, event) -> str | None:
        """The interim transcript worth checking, or None to ignore the event."""
        if getattr(event, "is_final", False):
            self._acted_on = ""  # utterance over; re-arm
            return None
        transcript = getattr(event, "transcript", "") or ""
        if not transcript.strip():
            return None
        if self._acted_on and transcript.startswith(self._acted_on):
            return None  # already acted on this utterance
        return transcript

    def acted(self, transcript: str) -> None:
        self._acted_on = transcript


def _is_speaking(session: AgentSession) -> bool:
    return str(getattr(session, "agent_state", "")) == "speaking"


def _interrupt(session: AgentSession, tag: str) -> None:
    try:
        session.interrupt()
    except Exception:
        logger.warning("[%s] session.interrupt() failed", tag, exc_info=True)


def wire_urgent_interrupts(session: AgentSession, cfg: LiveKitRealtimeConfig) -> None:
    """Let a clear "stop" cut in without waiting for the sustained threshold.

    ``min_interruption_words`` keeps a cough, a chair creak and the AC from
    barging in - but it also means a single decisive word would sit waiting
    for a second one. Generic speech keeps the stronger threshold; urgent
    phrases get their own door, and only while ARGO is actually speaking.
    """
    phrases = tuple(cfg.urgent_interrupt_phrases or ())
    if not phrases:
        logger.info("[Interrupt] no urgent phrases configured")
        return

    latch = _OncePerUtterance()

    def on_transcript(event) -> None:
        transcript = latch.candidate(event)
        if transcript is None:
            return
        phrase = opening_phrase(transcript, phrases)
        if not phrase or not _is_speaking(session):
            return
        latch.acted(transcript)
        logger.info("[Interrupt] urgent phrase %r -> interrupting now (heard %r)",
                    phrase, transcript[:80])
        voice_events.emit("urgent_interrupt", phrase=phrase, transcript=transcript[:120])
        _interrupt(session, "Interrupt")

    try:
        session.on("user_input_transcribed", on_transcript)
        logger.info("[Interrupt] urgent phrases armed: %s", ", ".join(phrases))
    except Exception:
        logger.warning("[Interrupt] could not arm urgent phrases", exc_info=True)


def wire_wake_sleep_gate(session: AgentSession, cfg: LiveKitRealtimeConfig) -> None:
    """Optional sleep-word / wake-word gate. A no-op unless the config enables it.

    What "asleep" means: ARGO keeps transcribing - the realtime model owns
    turn-taking, and there is no hook that stops it hearing without also
    stopping it ever waking up - but every reply is gated:

    * A sleep phrase cuts her off at once if she is speaking and marks her
      asleep. No confirmation.
    * While asleep, any reply the model starts anyway (it still runs its own
      server-side turn detection) is interrupted the instant it starts.
    * A wake phrase clears the flag, with a one-word acknowledgement only if
      ``wake_ack_enabled``.

    This is a reactive gate, not a preventative one: good enough to stop ARGO
    talking over a sleeping house, not a substitute for a local wake-word
    detector if the goal is ever "never send audio upstream at all".
    """
    if not cfg.wake_sleep_gate_enabled:
        logger.info("[WakeSleep] gate disabled (wake_sleep_gate_enabled=False)")
        return

    sleep_phrases = tuple(cfg.sleep_phrases or ())
    wake_phrases = tuple(cfg.wake_phrases or ())
    if not sleep_phrases and not wake_phrases:
        logger.info("[WakeSleep] gate enabled but no phrases configured; not arming")
        return

    latch = _OncePerUtterance()
    asleep = False

    def fall_asleep(phrase: str, transcript: str) -> None:
        nonlocal asleep
        asleep = True
        logger.info("[WakeSleep] sleep phrase %r -> going quiet (heard %r)",
                    phrase, transcript[:80])
        voice_events.emit("sleep_word_triggered", phrase=phrase, transcript=transcript[:120])
        if _is_speaking(session):
            _interrupt(session, "WakeSleep")

    def wake_up(phrase: str, transcript: str) -> None:
        nonlocal asleep
        asleep = False
        logger.info("[WakeSleep] wake phrase %r -> listening again (heard %r)",
                    phrase, transcript[:80])
        voice_events.emit("wake_word_triggered", phrase=phrase, transcript=transcript[:120])
        if cfg.wake_ack_enabled:
            try:
                session.generate_reply(instructions=WAKE_ACK_INSTRUCTIONS,
                                       allow_interruptions=True)
            except Exception:
                logger.warning("[WakeSleep] wake acknowledgement failed", exc_info=True)

    def on_transcript(event) -> None:
        transcript = latch.candidate(event)
        if transcript is None:
            return
        phrase = opening_phrase(transcript, wake_phrases if asleep else sleep_phrases)
        if not phrase:
            return
        latch.acted(transcript)
        (wake_up if asleep else fall_asleep)(phrase, transcript)

    def on_agent_state(event) -> None:
        if not asleep or str(getattr(event, "new_state", "")) != "speaking":
            return
        # The model ran its own turn detection on something said while asleep
        # and decided to answer. Cut it off; she stays asleep.
        logger.info("[WakeSleep] reply started while asleep -> interrupting")
        voice_events.emit("wake_sleep_suppressed_reply")
        _interrupt(session, "WakeSleep")

    try:
        session.on("user_input_transcribed", on_transcript)
        session.on("agent_state_changed", on_agent_state)
        logger.info(
            "[WakeSleep] gate armed: %d sleep phrase(s), %d wake phrase(s), wake_ack=%s",
            len(sleep_phrases), len(wake_phrases), cfg.wake_ack_enabled,
        )
    except Exception:
        logger.warning("[WakeSleep] could not arm gate", exc_info=True)
