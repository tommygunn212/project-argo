"""
LiveKit/OpenAI Realtime configuration helpers for ARGO.

The classic local pipeline is still useful for commands, diagnostics, and
fallback speech. This module owns only the realtime room path used for fast
voice conversation and clean barge-in behavior.
"""

from __future__ import annotations

import os
import re
import socket
import uuid
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from core.config import get_config


logger = logging.getLogger("ARGO.LiveKitConfig")

DEFAULT_LOCAL_LIVEKIT_SECRET = "devsecretdevsecretdevsecretdevsecretdevsecret"

# The realtime worker runs in its own process, so a UI personality change cannot
# reach it through core.config's in-memory runtime overrides. This file is the
# cross-process handoff: main.py writes it, and each new realtime session reads
# it at start. No restart needed — the value is resolved per session.
VOICE_PERSONALITY_FILE = Path(__file__).resolve().parents[1] / "runtime" / "voice_personality.json"
# Same cross-process handoff as the personality, for the same reason: the
# worker is a separate process and in-memory runtime overrides never reach it.
REALTIME_VOICE_FILE = Path(__file__).resolve().parents[1] / "runtime" / "realtime_voice.json"

# What gpt-realtime will actually accept. Anything else is refused at the
# session level, which is a bad way to find out - so it is checked here.
REALTIME_VOICES = [
    ("marin", "Marin - warm, natural (default)"),
    ("cedar", "Cedar - warm, lower"),
    ("alloy", "Alloy - balanced, neutral"),
    ("ash", "Ash - clear, even"),
    ("ballad", "Ballad - soft, expressive"),
    ("coral", "Coral - bright, friendly"),
    ("echo", "Echo - crisp, measured"),
    ("sage", "Sage - calm, steady"),
    ("shimmer", "Shimmer - light, quick"),
    ("verse", "Verse - rich, narrative"),
]
REALTIME_VOICE_NAMES = [v for v, _ in REALTIME_VOICES]


def read_realtime_voice(config: Any | None = None) -> str:
    """Which voice the next realtime session speaks in.

    Precedence matches the personality: env override, then the UI selection
    persisted by main.py, then config.json, then marin.
    """
    env_value = (os.getenv("ARGO_REALTIME_VOICE") or "").strip()
    if env_value:
        return env_value
    try:
        import json

        raw = json.loads(REALTIME_VOICE_FILE.read_text(encoding="utf-8"))
        chosen = str(raw.get("voice", "")).strip().lower()
        if chosen in REALTIME_VOICE_NAMES:
            return chosen
    except FileNotFoundError:
        pass
    except Exception:
        pass
    cfg = config or get_config()
    return str(_env_or_config(cfg, "ARGO_REALTIME_VOICE", "livekit.voice", "marin") or "marin")


def write_realtime_voice(voice: str) -> None:
    """Persist the UI's voice selection for the next realtime session."""
    import json
    from datetime import datetime, timezone

    name = str(voice or "").strip().lower()
    if name not in REALTIME_VOICE_NAMES:
        raise ValueError(f"{voice!r} is not a gpt-realtime voice. "
                         f"Choose from: {', '.join(REALTIME_VOICE_NAMES)}")
    REALTIME_VOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"voice": name, "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp = REALTIME_VOICE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(REALTIME_VOICE_FILE)
HEDRA_REALTIME_RETIRED = True
HEDRA_REALTIME_NOTICE = (
    "Hedra retired its realtime avatar service. Voice uses direct LiveKit audio; "
    "the Cortana portrait remains available locally."
)
LOCAL_AVATAR_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
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


def read_voice_personality(config: Any | None = None) -> str:
    """Resolve the personality for the next realtime session.

    Precedence: env override > UI selection persisted by main.py > config.json
    default > "neutral". Never raises; a damaged file falls through to config.
    """
    env_value = (os.getenv("ARGO_REALTIME_PERSONALITY") or "").strip()
    if env_value:
        return env_value

    try:
        import json

        raw = json.loads(VOICE_PERSONALITY_FILE.read_text(encoding="utf-8"))
        selected = str(raw.get("personality", "")).strip()
        if selected:
            return selected
    except FileNotFoundError:
        pass
    except Exception:
        # A corrupt handoff file must never break voice; fall through to config.
        pass

    cfg = config or get_config()
    return str(_env_or_config(cfg, "ARGO_PERSONALITY", "personality.default", "argo") or "argo")


def write_voice_personality(personality: str) -> None:
    """Persist the UI's personality selection for the next realtime session."""
    import json
    from datetime import datetime, timezone

    name = str(personality or "").strip()
    if not name:
        return
    VOICE_PERSONALITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"personality": name, "updated_at": datetime.now(timezone.utc).isoformat()}
    tmp = VOICE_PERSONALITY_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(VOICE_PERSONALITY_FILE)


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


DEFAULT_URGENT_INTERRUPT_PHRASES = (
    "stop", "wait", "hold on", "hang on", "pause",
    "stop talking", "shut up", "never mind", "nevermind", "no no",
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
        idle_processes=max(
            0,
            _int(
                _env_or_config(cfg, "ARGO_REALTIME_IDLE_PROCESSES", "livekit.idle_processes", 1),
                1,
            ),
        ),
    )


def build_livekit_token_response(
    *,
    identity: str | None = None,
    room: str | None = None,
    name: str | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    from livekit import api

    cfg = get_livekit_realtime_config(config)
    if not cfg.enabled:
        raise RuntimeError("LiveKit realtime voice is disabled in config.")
    if not cfg.api_key or not cfg.api_secret:
        raise RuntimeError("LiveKit API key/secret are required for token minting.")

    room_name = _clean_name(room or cfg.room) or cfg.room
    participant_identity = _clean_identity(identity or f"tommy-{uuid.uuid4().hex[:8]}")
    participant_name = name or participant_identity
    ttl_minutes = max(1, cfg.token_ttl_minutes)

    token_builder = (
        api.AccessToken(cfg.api_key, cfg.api_secret)
        .with_identity(participant_identity)
        .with_name(participant_name)
        .with_ttl(timedelta(minutes=ttl_minutes))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )
    if cfg.agent_name:
        token_builder = token_builder.with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=cfg.agent_name)]
            )
        )

    token = token_builder.to_jwt()
    dispatch_id = ""
    dispatch_error = ""
    try:
        dispatch_id = ensure_livekit_agent_dispatch(room_name=room_name, config=cfg)
    except Exception as exc:
        # Some local LiveKit builds expose worker dispatch through room config
        # but return 503 from the agent dispatch API. Do not block the browser
        # join - but never swallow this silently again. A failure here IS the
        # "ARGO says LIVE and then cannot hear me" bug: the browser joins the
        # room and publishes a mic track, and no agent is ever dispatched to
        # listen to it. It has to be loud in the log and visible on the
        # dashboard instead of looking like success.
        dispatch_error = f"{type(exc).__name__}: {exc}"
        logger.error(
            "[LiveKit] AGENT DISPATCH FAILED room=%s agent=%s - the browser will "
            "join and publish audio but NOTHING will be listening: %s",
            room_name,
            cfg.agent_name,
            dispatch_error,
        )
    else:
        logger.info(
            "[LiveKit] agent dispatched room=%s agent=%s dispatch_id=%s",
            room_name,
            cfg.agent_name,
            dispatch_id or "(none)",
        )
    if cfg.agent_name and not dispatch_id and not dispatch_error:
        dispatch_error = "no dispatch id returned"
        logger.error(
            "[LiveKit] no dispatch id for room=%s agent=%s - no agent will hear this session",
            room_name,
            cfg.agent_name,
        )

    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": room_name,
        "identity": participant_identity,
        "token": token,
        "agent_name": cfg.agent_name,
        "agent_dispatch_id": dispatch_id,
        "agent_dispatch_error": dispatch_error,
        "agent_listening": bool(dispatch_id) or not cfg.agent_name,
        "model": cfg.model,
        "voice": cfg.voice,
        "ttl_minutes": ttl_minutes,
    }


def ensure_livekit_agent_dispatch(
    *,
    room_name: str | None = None,
    config: LiveKitRealtimeConfig | None = None,
) -> str:
    """Ensure the local ARGO realtime worker is dispatched into the room."""

    cfg = config or get_livekit_realtime_config()
    if not cfg.agent_name:
        return ""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("LiveKit dispatch check skipped inside a running event loop")

    async def _ensure() -> str:
        from livekit import api

        lk = api.LiveKitAPI(url=cfg.url, api_key=cfg.api_key, api_secret=cfg.api_secret)
        try:
            room = _clean_name(room_name or cfg.room) or cfg.room
            # A dispatch record outlives the worker process that claimed it.
            # Reusing one left behind by a killed worker is exactly why ARGO
            # goes LIVE and then hears nothing: LiveKit considers the agent
            # already dispatched for this room and never hands the job to the
            # worker that is actually running now. Clear ours out and dispatch
            # fresh on every connect - creating a dispatch is cheap, silence
            # is not.
            try:
                existing = await lk.agent_dispatch.list_dispatch(room)
            except Exception:
                logger.warning(
                    "[LiveKit] could not list dispatches for room=%s", room, exc_info=True
                )
                existing = []
            for dispatch in existing:
                if dispatch.agent_name != cfg.agent_name:
                    continue
                try:
                    await lk.agent_dispatch.delete_dispatch(dispatch.id, room)
                    logger.info(
                        "[LiveKit] cleared stale dispatch id=%s agent=%s room=%s",
                        dispatch.id,
                        cfg.agent_name,
                        room,
                    )
                except Exception:
                    logger.warning(
                        "[LiveKit] could not clear stale dispatch id=%s room=%s",
                        dispatch.id,
                        room,
                        exc_info=True,
                    )
            created = await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    room=room,
                    agent_name=cfg.agent_name,
                    metadata="argo-realtime",
                )
            )
            logger.info(
                "[LiveKit] created dispatch id=%s agent=%s room=%s",
                created.id,
                cfg.agent_name,
                room,
            )
            return created.id
        finally:
            await lk.aclose()

    return asyncio.run(_ensure())


def _active_now() -> dict[str, Any] | None:
    try:
        from core.voice_active import read_active

        return read_active()
    except Exception:
        return None


def _persona_list() -> list[dict[str, str]]:
    try:
        from core.persona_briefs import selectable

        return selectable()
    except Exception:
        return []


def livekit_status(config: Any | None = None) -> dict[str, Any]:
    cfg = get_livekit_realtime_config(config)
    speaker_status = speaker_identity_status(cfg)
    avatar_status = hedra_avatar_status(config)
    return {
        "enabled": cfg.enabled,
        "mode": "livekit_realtime",
        "url": cfg.url,
        "room": cfg.room,
        "agent_name": cfg.agent_name,
        "model": cfg.model,
        "voice": cfg.voice,
        "server_reachable": _socket_reachable(cfg.url),
        "personality": cfg.personality,
        "avatar": avatar_status,
        "speaker_identity": speaker_status,
        # Which voice path actually owns the microphone. The dashboard was
        # showing the classic STT and TTS settings while Smooth Voice was
        # doing the talking, so it has to be able to say which is live.
        "voice_mode": read_voice_mode(),
        # What the live session is ACTUALLY running, from the record the
        # worker writes at session start - not what is saved in config.
        "active_now": _active_now(),
        # What the NEXT connection will use. Shown separately, so a changed
        # dropdown never looks like it transformed a session already in flight.
        "saved_for_next": {
            "model": cfg.model,
            "voice": cfg.voice,
            "personality": cfg.personality,
            "instruction_fingerprint": cfg.instruction_fingerprint,
        },
        "personas": _persona_list(),
        "voices": [{"name": v, "label": label} for v, label in REALTIME_VOICES],
        "interruption": {
            "allowed": True,
            "min_duration": cfg.min_interruption_duration,
            "min_words": cfg.min_interruption_words,
            "false_timeout": cfg.false_interruption_timeout,
        },
        "turn_detection": {
            "mode": cfg.turn_detection,
            "eagerness": cfg.turn_eagerness,
        },
        "urgent_interrupt_phrases": list(cfg.urgent_interrupt_phrases),
        "fallback_model": cfg.fallback_model,
        "noise_cancellation": cfg.noise_cancellation,
        "input_noise_reduction": cfg.input_noise_reduction,
        "deep_think": {
            "enabled": cfg.deep_think_enabled,
            "model": cfg.deep_think_model,
            "timeout_seconds": cfg.deep_think_timeout,
        },
    }


VOICE_MODE_FILE = Path(__file__).resolve().parents[1] / "runtime" / "voice_mode.json"


def read_voice_mode() -> str:
    """Which path owns the microphone: "smooth" or "classic".

    main.py persists this so a restart cannot quietly hand the microphone
    back; the dashboard reads the same file so it cannot disagree with the
    server about what is live.
    """
    try:
        import json

        raw = json.loads(VOICE_MODE_FILE.read_text(encoding="utf-8"))
        mode = str(raw.get("mode", "")).strip().lower()
        if mode in ("smooth", "classic"):
            return mode
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return "classic"


def mobile_access_status(request_host: str | None = None) -> dict[str, Any]:
    host = _clean_request_host(request_host) or _best_lan_ip() or "127.0.0.1"
    http_port = _int(os.getenv("ARGO_HTTP_PORT", "8000"), 8000)
    ws_port = _int(os.getenv("ARGO_WS_PORT", "8001"), 8001)
    return {
        "host": host,
        "http_url": f"http://{host}:{http_port}/v2",
        "ws_url": f"ws://{host}:{ws_port}/ws",
        "livekit": livekit_status(),
        "note": "Use this URL from an iPad or phone on the same network; browser microphone permission must be allowed.",
    }


def speaker_identity_status(cfg: LiveKitRealtimeConfig | None = None) -> dict[str, Any]:
    cfg = cfg or get_livekit_realtime_config()
    provider = str(cfg.speaker_id_provider or "speechmatics").strip().lower()
    api_key_ready = bool(os.getenv("SPEECHMATICS_API_KEY", "").strip()) if provider == "speechmatics" else False
    plugin_ready = False
    plugin_error = ""
    if provider == "speechmatics":
        try:
            metadata.version("livekit-plugins-speechmatics")
        except Exception as exc:  # pragma: no cover - depends on optional package install
            plugin_error = str(exc)
        else:
            plugin_ready = True
    else:
        plugin_error = f"Unsupported speaker identity provider: {provider}"

    return {
        "enabled": bool(cfg.speaker_id_enabled),
        "provider": provider,
        "api_key_ready": api_key_ready,
        "plugin_ready": plugin_ready,
        "ready": bool(cfg.speaker_id_enabled and api_key_ready and plugin_ready),
        "mode": "experimental_sidecar",
        "error": plugin_error,
    }


def resolve_local_avatar_media(config: Any | None = None) -> tuple[Path | None, str, str, str]:
    """Resolve an explicitly configured local avatar media file."""

    cfg = config or get_config()
    enabled = _bool(_env_or_config(cfg, "ARGO_LOCAL_AVATAR_MEDIA_ENABLED", "avatar.local_media_enabled", True))
    raw_path = str(_env_or_config(cfg, "ARGO_LOCAL_AVATAR_MEDIA", "avatar.local_media_path", "") or "").strip()
    if not enabled or not raw_path:
        return None, "", raw_path, "not_configured"

    media_path = Path(raw_path).expanduser()
    if not media_path.is_absolute():
        media_path = Path(__file__).resolve().parents[1] / media_path
    content_type = LOCAL_AVATAR_MEDIA_TYPES.get(media_path.suffix.lower(), "")
    if not content_type:
        return media_path, "", raw_path, "unsupported_type"
    if not media_path.exists() or not media_path.is_file():
        return media_path, content_type, raw_path, "missing"
    return media_path, content_type, raw_path, ""


def local_avatar_media_status(config: Any | None = None) -> dict[str, Any]:
    cfg = config or get_config()
    media_path, content_type, raw_path, error = resolve_local_avatar_media(config)
    ready = bool(media_path and content_type and not error)
    motion_enabled = cfg.get("avatar.motion_enabled", None)
    return {
        "enabled": error != "not_configured",
        "ready": ready,
        "path": raw_path,
        "url": "/v2-assets/local-avatar-media" if ready else "",
        "content_type": content_type,
        "media_type": "video" if content_type.startswith("video/") else "image",
        "expression_profile": str(cfg.get("avatar.local_media_profile", "") or ""),
        "motion_enabled": None if motion_enabled is None else _bool(motion_enabled),
        "error": error,
    }


def hedra_avatar_status(config: Any | None = None) -> dict[str, Any]:
    """Return safe-to-display Hedra avatar readiness without exposing secrets."""

    image_path_raw = os.getenv("HEDRA_AVATAR_IMAGE", "").strip()
    image_path = Path(image_path_raw).expanduser() if image_path_raw else None
    if image_path and not image_path.is_absolute():
        image_path = Path(__file__).resolve().parents[1] / image_path

    plugin_ready = False
    plugin_version = ""
    plugin_error = ""
    try:
        plugin_version = metadata.version("livekit-plugins-hedra")
        plugin_ready = True
    except Exception as exc:  # pragma: no cover - depends on optional package install
        plugin_error = str(exc)

    avatar_id_ready = bool(os.getenv("HEDRA_AVATAR_ID", "").strip())
    image_ready = bool(image_path and image_path.exists())
    api_key_ready = bool(os.getenv("HEDRA_API_KEY", "").strip())
    enabled = _bool(os.getenv("ARGO_HEDRA_AVATAR_ENABLED", False))

    return {
        "enabled": enabled,
        "provider": "hedra_live_avatar",
        "api_key_ready": api_key_ready,
        "avatar_id_ready": avatar_id_ready,
        "image_ready": image_ready,
        "image": image_path_raw,
        "plugin_ready": plugin_ready,
        "plugin_version": plugin_version,
        "ready": False,
        "service_retired": HEDRA_REALTIME_RETIRED,
        "api_url": os.getenv("HEDRA_API_URL", "https://api.hedra.com/public/livekit/v1/session"),
        "mode": "livekit_video_track",
        "fallback": "local_cortana_portrait",
        "local_media": local_avatar_media_status(config),
        "error": HEDRA_REALTIME_NOTICE,
    }


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


def _clean_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]", "-", str(value or "").strip())[:96]


def _clean_identity(value: str) -> str:
    cleaned = _clean_name(value)
    return cleaned or f"tommy-{uuid.uuid4().hex[:8]}"


def _clean_request_host(value: str | None) -> str:
    if not value:
        return ""
    host = value.split(":", 1)[0].strip()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return host
    return re.sub(r"[^A-Za-z0-9_.:-]", "", host)[:96]


def _best_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def _socket_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
