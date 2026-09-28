"""
LiveKit/OpenAI Realtime configuration helpers for ARGO.

The classic local pipeline is still useful for commands, diagnostics, and
fallback speech. This module owns only the realtime room path used for fast
voice conversation and clean barge-in behavior.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.config import get_config


logger = logging.getLogger("ARGO.LiveKitConfig")

DEFAULT_LOCAL_LIVEKIT_SECRET = "devsecretdevsecretdevsecretdevsecretdevsecret"

from core.livekit_preferences import (
    REALTIME_VOICE_FILE,
    REALTIME_VOICE_NAMES,
    REALTIME_VOICES,
    VOICE_MODE_FILE,
    VOICE_PERSONALITY_FILE,
    read_realtime_voice,
    read_voice_mode,
    read_voice_personality,
    write_realtime_voice,
    write_voice_personality,
)
from core.livekit_avatar import (
    HEDRA_REALTIME_NOTICE,
    HEDRA_REALTIME_RETIRED,
    LOCAL_AVATAR_MEDIA_TYPES,
    hedra_avatar_status,
    local_avatar_media_status,
    resolve_local_avatar_media,
)
from core.livekit_access import (
    _clean_name,
    build_livekit_token_response,
    ensure_livekit_agent_dispatch,
)
from core.livekit_status import livekit_status, mobile_access_status, speaker_identity_status
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from core.persona_briefs import (  # noqa: E402
    CONVERSATION_CONTRACT,
    DEEP_THINK_POLICY,
    TOOL_POLICY,
    compose_instructions,
    instruction_fingerprint,
)

# The product contract is the base instruction. Everything ARGO is told is
# assembled once, in core.persona_briefs.compose_instructions; these names are
# kept so existing callers and tests keep working.
DEFAULT_REALTIME_INSTRUCTIONS = CONVERSATION_CONTRACT
TOOL_BRIEF = TOOL_POLICY
DEEP_THINK_BRIEF = DEEP_THINK_POLICY


def compose_realtime_instructions(
    base_instructions: str,
    personality: str,
    *,
    deep_think: bool = True,
) -> str:
    """Assemble everything the realtime model is told - once, here.

    Order: the conversation contract (what every ARGO does), the selected
    persona's voice AND collaboration style, the deep-think policy, the short
    tool policy. Nothing else is layered on top: not the classic personas'
    text post-processors, not a tool manual, not a second system prompt.

    `base_instructions` is the contract unless a caller overrides it (tests
    do); an unknown persona contributes no manner at all.
    """
    return compose_instructions(personality, deep_think=deep_think, contract=base_instructions)


@dataclass(frozen=True)
class LiveKitRealtimeConfig:
    enabled: bool
    url: str
    api_key: str
    api_secret: str
    room: str
    agent_name: str
    model: str
    voice: str
    instructions: str
    greeting: str
    temperature: float
    speed: float
    token_ttl_minutes: int
    # Deliberate, not hair-trigger. A cough, a chair creak and ARGO's own
    # speaker bleeding back into the Brio all used to clear the old 0.08s.
    min_interruption_duration: float
    false_interruption_timeout: float
    speaker_id_enabled: bool
    speaker_id_provider: str
    personality: str = "argo"
    instruction_fingerprint: str = ""
    # LiveKit Cloud only. Off unless this actually runs against Cloud.
    noise_cancellation: bool = False
    idle_processes: int = 1
    # How the model decides Tommy has finished a thought. "semantic_vad" reads
    # the words, not just the silence, which is the difference between waiting
    # through a mid-sentence pause and talking over him.
    turn_detection: str = "semantic_vad"
    # How ready it is to jump in. "low" waits longest - that is the setting
    # that stops it answering half a question.
    turn_eagerness: str = "low"
    # Server-side cleanup on the inbound mic. "far_field" suits a speakerphone
    # across a desk with an AC running; "near_field" suits a headset.
    input_noise_reduction: str = "far_field"
    # How many words he has to actually say before it counts as an
    # interruption. 0 means a cough stops her mid-sentence.
    min_interruption_words: int = 2
    deep_think_enabled: bool = True
    deep_think_model: str = "gpt-5.5"
    deep_think_timeout: float = 90.0
    # Where to land if the configured realtime model will not run. Never the
    # same string as `model`, or a failure would retry itself forever.
    fallback_model: str = "gpt-realtime-1.5"
    # Said clearly and on purpose, these stop ARGO the instant they are
    # recognised - they do not wait for the sustained-speech threshold that
    # keeps coughs and the AC from barging in.
    urgent_interrupt_phrases: tuple[str, ...] = (
        "stop", "wait", "hold on", "hang on", "pause",
        "stop talking", "shut up", "never mind", "nevermind", "no no",
    )

    # Off by default - nothing about ARGO's live behavior changes until this
    # is deliberately turned on. When on, a sleep phrase silences her (cuts
    # off mid-sentence if she is speaking, no confirmation) until a wake
    # phrase is heard. She keeps transcribing while "asleep" - only her
    # replies are gated, not the microphone - because the realtime model
    # keeps its own turn-taking regardless of this flag.
    wake_sleep_gate_enabled: bool = False
    sleep_phrases: tuple[str, ...] = (
        "go to sleep", "goodnight argo", "argo go to sleep", "argo sleep",
    )
    wake_phrases: tuple[str, ...] = (
        "hey argo", "argo wake up", "wake up argo", "argo are you there",
    )
    # A one or two word acknowledgement on waking. Off by default to match
    # the sleep side, which never confirms - Tommy can turn this on alone
    # without changing anything else.
    wake_ack_enabled: bool = False


DEFAULT_URGENT_INTERRUPT_PHRASES = (
    "stop", "wait", "hold on", "hang on", "pause",
    "stop talking", "shut up", "never mind", "nevermind", "no no",
)

DEFAULT_SLEEP_PHRASES = (
    "go to sleep", "goodnight argo", "argo go to sleep", "argo sleep",
)

DEFAULT_WAKE_PHRASES = (
    "hey argo", "argo wake up", "wake up argo", "argo are you there",
)


def _urgent_phrases(cfg: Any) -> tuple[str, ...]:
    """Phrases that interrupt ARGO immediately, however short.

    The sustained-speech threshold is what keeps a cough or the AC from
    cutting her off, but it also means a single confident "stop" would have
    to wait for a second word that is never coming. These get a fast path
    instead: recognised clearly at the start of an utterance, they interrupt
    at once.
    """
    raw = _env_or_config(cfg, "ARGO_REALTIME_URGENT_PHRASES", "livekit.urgent_interrupt_phrases", None)
    if raw is None:
        return DEFAULT_URGENT_INTERRUPT_PHRASES
    if isinstance(raw, str):
        raw = [part for part in raw.split(",")]
    phrases = tuple(str(p).strip().lower() for p in raw if str(p).strip())
    return phrases or DEFAULT_URGENT_INTERRUPT_PHRASES


def _phrase_list(cfg: Any, env_key: str, config_key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Shared loader for the sleep/wake phrase lists - same shape as urgent
    phrases (comma-separated env var, or a config.json list), same fallback
    behavior (an empty or missing value means "use the default list", not
    "no phrases at all", so a typo in config.json cannot silently disable
    the gate's vocabulary).
    """
    raw = _env_or_config(cfg, env_key, config_key, None)
    if raw is None:
        return default
    if isinstance(raw, str):
        raw = [part for part in raw.split(",")]
    phrases = tuple(str(p).strip().lower() for p in raw if str(p).strip())
    return phrases or default


def _sleep_phrases(cfg: Any) -> tuple[str, ...]:
    return _phrase_list(
        cfg, "ARGO_REALTIME_SLEEP_PHRASES", "livekit.wake_sleep_gate.sleep_phrases",
        DEFAULT_SLEEP_PHRASES,
    )


def _wake_phrases(cfg: Any) -> tuple[str, ...]:
    return _phrase_list(
        cfg, "ARGO_REALTIME_WAKE_PHRASES", "livekit.wake_sleep_gate.wake_phrases",
        DEFAULT_WAKE_PHRASES,
    )


def get_livekit_realtime_config(config: Any | None = None) -> LiveKitRealtimeConfig:
    cfg = config or get_config()

    api_key = _env_or_config(cfg, "LIVEKIT_API_KEY", "livekit.api_key", "devkey")
    api_secret = _env_or_config(cfg, "LIVEKIT_API_SECRET", "livekit.api_secret", "")
    if not api_secret and api_key == "devkey":
        api_secret = DEFAULT_LOCAL_LIVEKIT_SECRET

    # Resolved per call, so each new realtime session picks up the current UI
    # selection without restarting the worker or ARGO.
    personality = read_voice_personality(cfg)
    base_instructions = _env_or_config(
        cfg, "ARGO_REALTIME_INSTRUCTIONS", "livekit.instructions", DEFAULT_REALTIME_INSTRUCTIONS
    )

    _instructions = compose_realtime_instructions(
        base_instructions,
        personality,
        deep_think=_bool(
            _env_or_config(cfg, "ARGO_DEEP_THINK_ENABLED", "livekit.deep_think.enabled", True)
        ),
    )

    return LiveKitRealtimeConfig(
        enabled=_bool(_env_or_config(cfg, "ARGO_LIVEKIT_ENABLED", "livekit.enabled", True)),
        url=_env_or_config(cfg, "LIVEKIT_URL", "livekit.url", "ws://127.0.0.1:7880"),
        api_key=api_key,
        api_secret=api_secret,
        room=_clean_name(_env_or_config(cfg, "ARGO_LIVEKIT_ROOM", "livekit.room", "argo-live")),
        agent_name=_clean_name(_env_or_config(cfg, "LIVEKIT_AGENT_NAME", "livekit.agent_name", "")),
        model=_env_or_config(cfg, "ARGO_REALTIME_MODEL", "livekit.model", "gpt-realtime"),
        voice=read_realtime_voice(cfg),
        instructions=_instructions,
        instruction_fingerprint=instruction_fingerprint(_instructions),
        personality=personality,
        greeting=_env_or_config(cfg, "ARGO_REALTIME_GREETING", "livekit.greeting", ""),
        temperature=_float(_env_or_config(cfg, "ARGO_REALTIME_TEMPERATURE", "livekit.temperature", 0.6), 0.6),
        speed=_float(_env_or_config(cfg, "ARGO_REALTIME_SPEED", "livekit.speed", 1.0), 1.0),
        token_ttl_minutes=_int(
            _env_or_config(cfg, "ARGO_LIVEKIT_TOKEN_TTL_MINUTES", "livekit.token_ttl_minutes", 60),
            60,
        ),
        min_interruption_duration=_float(
            _env_or_config(
                cfg,
                "ARGO_REALTIME_MIN_INTERRUPTION_DURATION",
                "livekit.min_interruption_duration",
                0.35,
            ),
            0.35,
        ),
        false_interruption_timeout=_float(
            _env_or_config(
                cfg,
                "ARGO_REALTIME_FALSE_INTERRUPTION_TIMEOUT",
                "livekit.false_interruption_timeout",
                1.2,
            ),
            1.2,
        ),
        speaker_id_enabled=_bool(
            _env_or_config(cfg, "ARGO_SPEAKER_ID_ENABLED", "speaker_identity.enabled", False)
        ),
        speaker_id_provider=_env_or_config(
            cfg, "ARGO_SPEAKER_ID_PROVIDER", "speaker_identity.provider", "speechmatics"
        ),
        # Default ON. It was defaulting to False with no key in config.json, so
        # the plugin was installed, the code path existed, and the mic was
        # still feeding raw room noise and speaker echo straight to the model.
        noise_cancellation=_bool(
            _env_or_config(
                cfg, "ARGO_REALTIME_NOISE_CANCELLATION", "livekit.noise_cancellation", False
            )
        ),
        turn_detection=str(
            _env_or_config(cfg, "ARGO_REALTIME_TURN_DETECTION", "livekit.turn_detection", "semantic_vad")
        ).strip().lower(),
        turn_eagerness=str(
            _env_or_config(cfg, "ARGO_REALTIME_TURN_EAGERNESS", "livekit.turn_eagerness", "low")
        ).strip().lower(),
        input_noise_reduction=str(
            _env_or_config(
                cfg, "ARGO_REALTIME_INPUT_NOISE_REDUCTION", "livekit.input_noise_reduction", "far_field"
            )
        ).strip().lower(),
        min_interruption_words=max(
            0,
            _int(
                _env_or_config(
                    cfg, "ARGO_REALTIME_MIN_INTERRUPTION_WORDS", "livekit.min_interruption_words", 2
                ),
                2,
            ),
        ),
        deep_think_enabled=_bool(
            _env_or_config(cfg, "ARGO_DEEP_THINK_ENABLED", "livekit.deep_think.enabled", True)
        ),
        deep_think_model=str(
            _env_or_config(cfg, "ARGO_DEEP_THINK_MODEL", "livekit.deep_think.model", "gpt-5.5")
        ).strip(),
        deep_think_timeout=_float(
            _env_or_config(cfg, "ARGO_DEEP_THINK_TIMEOUT", "livekit.deep_think.timeout_seconds", 90.0),
            90.0,
        ),
        fallback_model=str(
            _env_or_config(cfg, "ARGO_REALTIME_FALLBACK_MODEL", "livekit.fallback_model",
                           "gpt-realtime-1.5")
        ).strip(),
        urgent_interrupt_phrases=_urgent_phrases(cfg),
        wake_sleep_gate_enabled=_bool(
            _env_or_config(cfg, "ARGO_WAKE_SLEEP_GATE_ENABLED", "livekit.wake_sleep_gate.enabled", False)
        ),
        sleep_phrases=_sleep_phrases(cfg),
        wake_phrases=_wake_phrases(cfg),
        wake_ack_enabled=_bool(
            _env_or_config(cfg, "ARGO_WAKE_ACK_ENABLED", "livekit.wake_sleep_gate.wake_ack_enabled", False)
        ),
        idle_processes=max(
            0,
            _int(
                _env_or_config(cfg, "ARGO_REALTIME_IDLE_PROCESSES", "livekit.idle_processes", 1),
                1,
            ),
        ),
    )


def _env_or_config(config: Any, env_key: str, config_key: str, default: Any) -> Any:
    env_value = os.getenv(env_key)
    if env_value not in (None, ""):
        return env_value
    value = config.get(config_key, default)
    return default if value in (None, "") else value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

