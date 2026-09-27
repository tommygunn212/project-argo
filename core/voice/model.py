"""The OpenAI realtime model and the audio settings that ride with it.

Every optional setting here follows one rule: prefer the SDK's typed object,
fall back to the plain dict the API accepts, and log which one was used -
"configured" and "actually reached the session" are different claims. And an
optional setting that the installed plugin rejects must never take voice down.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from livekit.plugins import openai

from core.livekit_config import LiveKitRealtimeConfig

logger = logging.getLogger("ARGO.LiveKit")

# Pinned on purpose. Without a language, two of thirty turns in the first real
# mic run came back as Chinese characters (the AC was on) and ARGO answered one.
TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
TRANSCRIPTION_LANGUAGE = "en"

_EAGERNESS = ("low", "medium", "high", "auto")
_NOISE_REDUCTION = ("near_field", "far_field")
_OPTIONAL_MODEL_KWARGS = (
    "turn_detection", "input_audio_noise_reduction", "input_audio_transcription",
)


def build_noise_filter(cfg: LiveKitRealtimeConfig):
    """LiveKit BVC noise cancellation for the inbound mic track, or None.

    Off by default and must stay off here: BVC is a LiveKit *Cloud* filter and
    this server is self-hosted (AGENTS.md invariant 1). A missing or broken
    plugin degrades to raw audio and says so in the log.
    """
    if not cfg.noise_cancellation:
        logger.info("[Audio] noise cancellation disabled by config")
        return None
    try:
        from livekit.plugins import noise_cancellation

        noise_filter = noise_cancellation.BVC()
    except Exception:
        logger.exception("[Audio] noise cancellation unavailable; continuing with raw mic audio")
        return None
    logger.info("[Audio] noise cancellation enabled (BVC)")
    return noise_filter


def build_turn_detection(cfg: LiveKitRealtimeConfig) -> Any | None:
    """How the model decides Tommy has finished a thought.

    Semantic VAD reads the words as well as the silence; "low" eagerness waits
    longest. Without this the API runs a plain silence timer and answers
    half-finished sentences.

    Returns None meaning "do not pass the kwarg at all". Passing
    ``turn_detection=None`` would switch server turn detection OFF, which is
    not the same thing and much worse.
    """
    mode = (cfg.turn_detection or "").strip().lower()
    if mode in ("", "default", "auto_default"):
        return None

    eagerness = (cfg.turn_eagerness or "auto").strip().lower()
    if eagerness not in _EAGERNESS:
        logger.warning("[Turn] unknown eagerness %r; using 'auto'", eagerness)
        eagerness = "auto"

    if mode == "semantic_vad":
        payload = {"type": "semantic_vad", "eagerness": eagerness}
    elif mode == "server_vad":
        payload = {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            # Long on purpose: a normal thinking pause is ~600 ms and the old
            # default cut in under it.
            "silence_duration_ms": 900,
        }
    else:
        logger.warning("[Turn] unknown turn_detection %r; leaving the API default", mode)
        return None
    payload.update(create_response=True, interrupt_response=True)

    try:
        from openai.types.realtime import realtime_audio_input_turn_detection as types

        typed = (types.SemanticVad if mode == "semantic_vad" else types.ServerVad)(**payload)
        logger.info("[Turn] %s eagerness=%s (typed)", mode, eagerness)
        return typed
    except Exception:
        logger.debug("[Turn] typed turn detection unavailable; sending a dict", exc_info=True)
        logger.info("[Turn] %s eagerness=%s (dict)", mode, eagerness)
        return payload


def _input_transcription() -> Any:
    try:
        from openai.types import realtime as types

        value = types.AudioTranscription(model=TRANSCRIPTION_MODEL,
                                         language=TRANSCRIPTION_LANGUAGE)
        form = "typed"
    except Exception:
        value = {"model": TRANSCRIPTION_MODEL, "language": TRANSCRIPTION_LANGUAGE}
        form = "dict"
    logger.info("[Audio] input transcription: %s language=%s (%s)",
                TRANSCRIPTION_MODEL, TRANSCRIPTION_LANGUAGE, form)
    return value


def _input_noise_reduction(cfg: LiveKitRealtimeConfig) -> str | None:
    """OpenAI's server-side reduction - a different mechanism from BVC, and on."""
    reduction = (cfg.input_noise_reduction or "").strip().lower()
    if reduction in _NOISE_REDUCTION:
        logger.info("[Audio] server-side input noise reduction: %s", reduction)
        return reduction
    if reduction not in ("", "off", "none"):
        logger.warning("[Audio] unknown input_noise_reduction %r; leaving it off", reduction)
    return None


def _require_openai_key() -> str:
    from core.runtime_guard import ensure_openai_key

    ensure_openai_key()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for OpenAI Realtime voice, and it was "
            "not found in this process, in .env, or in the Windows User "
            "environment. ARGO will have accepted this job and then failed "
            "inside it, which from the room looks like no agent ever arrived."
        )
    return api_key


def build_realtime_model(cfg: LiveKitRealtimeConfig) -> openai.realtime.RealtimeModel:
    """The realtime model for one session, tuned from config."""
    kwargs: dict[str, Any] = dict(
        model=cfg.model,
        voice=cfg.voice,
        modalities=["text", "audio"],
        api_key=_require_openai_key(),
        temperature=cfg.temperature,
        speed=cfg.speed,
        input_audio_transcription=_input_transcription(),
    )
    turn_detection = build_turn_detection(cfg)
    if turn_detection is not None:
        kwargs["turn_detection"] = turn_detection
    reduction = _input_noise_reduction(cfg)
    if reduction is not None:
        kwargs["input_audio_noise_reduction"] = reduction

    logger.info(
        "[LiveKit] realtime model=%s voice=%s temp=%.2f speed=%.2f turn_detection=%s",
        cfg.model, cfg.voice, cfg.temperature, cfg.speed,
        _describe(turn_detection),
    )

    try:
        return openai.realtime.RealtimeModel(**kwargs)
    except TypeError:
        # An older plugin that does not know one of these kwargs must not take
        # voice down - drop the optional ones and say so, loudly.
        logger.exception(
            "[LiveKit] realtime model rejected the tuning kwargs; retrying without "
            "turn_detection/noise-reduction/transcription. Turn-taking will be the API default."
        )
        for optional in _OPTIONAL_MODEL_KWARGS:
            kwargs.pop(optional, None)
        return openai.realtime.RealtimeModel(**kwargs)


def _describe(turn_detection: Any | None) -> str:
    if turn_detection is None:
        return "api-default"
    if isinstance(turn_detection, dict):
        return str(turn_detection)
    return type(turn_detection).__name__
