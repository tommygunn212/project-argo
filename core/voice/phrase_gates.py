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

WAKE_REPLY_INSTRUCTIONS = (
    "Tommy just woke you with your wake phrase. Answer only his last line, the one "
    "that started with the wake phrase. If that line was only the wake phrase, a few "
    "words to say you're listening is enough. Ignore anything said before it while "
    "you were asleep - that was not meant for you."
)


def _normalize(transcript: str) -> str:
    return " ".join((transcript or "").strip().lower().translate(_PUNCTUATION).split())


def whole_phrase(transcript: str, phrases: Iterable[str]) -> str | None:
    """The phrase if it is the ENTIRE utterance ("Stop." yes, "stop the job" no)."""
    text = _normalize(transcript)
    for phrase in phrases:
        if text == phrase:
            return phrase
    return None


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

    @property
    def acted_this_utterance(self) -> bool:
        return bool(self._acted_on)


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
    # A bare "Stop." means "be quiet" - not "answer me about stopping". The
    # model still gets that turn and replies to it (live, it once ran
    # check_background_tasks and said "Stopped, nothing running"), so the
    # reply to a bare stop phrase is cut before it gets anywhere.
    hush = {"until": 0.0}
    HUSH_SECONDS = 4.0

    def on_final(event) -> None:
        transcript = getattr(event, "transcript", "") or ""
        phrase = whole_phrase(transcript, phrases)
        if not phrase:
            return
        import time as _time

        hush["until"] = _time.monotonic() + HUSH_SECONDS
        logger.info("[Interrupt] bare %r -> staying quiet, no reply (heard %r)",
                    phrase, transcript[:80])
        voice_events.emit("urgent_hush", phrase=phrase, transcript=transcript[:120])
        _interrupt(session, "Interrupt")

    def on_agent_state(event) -> None:
        if str(getattr(event, "new_state", "")) not in ("thinking", "speaking"):
            return
        import time as _time

        if _time.monotonic() < hush["until"]:
            hush["until"] = 0.0
            logger.info("[Interrupt] reply to a bare stop phrase -> cutting it")
            voice_events.emit("urgent_hush_reply_cut")
            _interrupt(session, "Interrupt")

    def on_transcript(event) -> None:
        if getattr(event, "is_final", False):
            on_final(event)
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
        session.on("agent_state_changed", on_agent_state)
        logger.info("[Interrupt] urgent phrases armed: %s", ", ".join(phrases))
    except Exception:
        logger.warning("[Interrupt] could not arm urgent phrases", exc_info=True)


def set_auto_reply(session: AgentSession, enabled: bool) -> bool:
    """Turn the realtime model's automatic reply-at-end-of-turn on or off.

    Off is what makes "asleep" real: the model still transcribes everything (so
    the wake phrase is heard) but never starts a response on its own, so it
    cannot speak *or run tools* on overheard speech. Returns False when this
    model has no server turn detection to change; the reactive gate below is
    then the only protection.
    """
    model = getattr(session, "llm", None)
    opts = getattr(model, "_opts", None)
    turn = getattr(opts, "turn_detection", None)
    if model is None or turn is None or not hasattr(model, "update_options"):
        return False
    try:
        if hasattr(turn, "model_copy"):
            updated = turn.model_copy(update={"create_response": enabled})
        else:
            updated = dict(turn)
            updated["create_response"] = enabled
        model.update_options(turn_detection=updated)
        logger.info("[WakeSleep] auto-reply %s", "on" if enabled else "off")
        return True
    except Exception:
        logger.warning("[WakeSleep] could not switch auto-reply %s",
                       "on" if enabled else "off", exc_info=True)
        return False


class WakeState:
    """Whether ARGO is asleep, plus a one-shot pass for a deliberate line."""

    def __init__(self, asleep: bool = False) -> None:
        self.asleep = asleep
        self.allow_once = False


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
    state = WakeState(asleep=bool(getattr(cfg, "wake_start_asleep", False)))
    # Shared with core.voice.proactive, which needs to know whether she's
    # asleep and to let one deliberate line (a due reminder) through.
    try:
        session.argo_wake = state
    except Exception:
        pass

    def fall_asleep(phrase: str, transcript: str) -> None:
        state.asleep = True
        set_auto_reply(session, False)
        logger.info("[WakeSleep] sleep phrase %r -> going quiet (heard %r)",
                    phrase, transcript[:80])
        voice_events.emit("sleep_word_triggered", phrase=phrase, transcript=transcript[:120])
        if _is_speaking(session):
            _interrupt(session, "WakeSleep")

    def wake_up(phrase: str, transcript: str, *, from_final: bool = False) -> None:
        state.asleep = False
        auto_was_off = set_auto_reply(session, True)
        logger.info("[WakeSleep] wake phrase %r -> listening again (heard %r)",
                    phrase, transcript[:80])
        voice_events.emit("wake_word_triggered", phrase=phrase, transcript=transcript[:120])
        if from_final and auto_was_off:
            # Auto-reply was off when this turn ended, so nothing is answering
            # it yet. Answer it now - just this line, not the overheard ones.
            try:
                session.generate_reply(instructions=WAKE_REPLY_INSTRUCTIONS,
                                       allow_interruptions=True)
            except Exception:
                logger.warning("[WakeSleep] wake reply failed", exc_info=True)
            return
        if from_final:
            # The model already answered this turn on its own; don't stack a
            # second reply on top.
            return
        if cfg.wake_ack_enabled:
            try:
                session.generate_reply(instructions=WAKE_ACK_INSTRUCTIONS,
                                       allow_interruptions=True)
            except Exception:
                logger.warning("[WakeSleep] wake acknowledgement failed", exc_info=True)

    def on_transcript(event) -> None:
        if getattr(event, "is_final", False):
            # Some transcribers (gpt-4o-mini-transcribe over realtime) send
            # only blank interims, so the final is the first real text we
            # see. Check it too, unless an interim already acted.
            already = latch.acted_this_utterance
            latch.candidate(event)  # re-arm for the next utterance
            if already:
                return
            transcript = getattr(event, "transcript", "") or ""
            phrase = opening_phrase(transcript, wake_phrases if state.asleep else sleep_phrases)
            if not phrase:
                return
            if state.asleep:
                # The model is already answering this turn; that answer is the
                # acknowledgement, so don't stack a second reply on top.
                wake_up(phrase, transcript, from_final=True)
            else:
                fall_asleep(phrase, transcript)
            return
        transcript = latch.candidate(event)
        if transcript is None:
            return
        phrase = opening_phrase(transcript, wake_phrases if state.asleep else sleep_phrases)
        if not phrase:
            return
        latch.acted(transcript)
        (wake_up if state.asleep else fall_asleep)(phrase, transcript)

    def on_agent_state(event) -> None:
        new_state = str(getattr(event, "new_state", ""))
        if not state.asleep or new_state not in ("speaking", "thinking"):
            return
        if new_state == "thinking":
            # Thinking while asleep means a reply - maybe a tool call - is
            # under way on overheard speech. Stop it before it does anything,
            # unless it is the one deliberate line (a due reminder).
            if not state.allow_once:
                logger.info("[WakeSleep] reply thinking while asleep -> interrupting")
                voice_events.emit("wake_sleep_suppressed_reply", stage="thinking")
                _interrupt(session, "WakeSleep")
            return
        if state.allow_once:
            # A line ARGO was told to say on purpose (a due reminder).
            state.allow_once = False
            return
        # The model ran its own turn detection on something said while asleep
        # and decided to answer. Cut it off; she stays asleep.
        logger.info("[WakeSleep] reply started while asleep -> interrupting")
        voice_events.emit("wake_sleep_suppressed_reply")
        _interrupt(session, "WakeSleep")

    if state.asleep:
        set_auto_reply(session, False)

    try:
        session.on("user_input_transcribed", on_transcript)
        session.on("agent_state_changed", on_agent_state)
        logger.info(
            "[WakeSleep] gate armed: %d sleep phrase(s), %d wake phrase(s), wake_ack=%s, "
            "starts %s", len(sleep_phrases), len(wake_phrases), cfg.wake_ack_enabled,
            "asleep" if state.asleep else "awake",
        )
    except Exception:
        logger.warning("[WakeSleep] could not arm gate", exc_info=True)
