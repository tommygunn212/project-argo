"""Which voice ARGO speaks with: OpenAI's built-in realtime voice, or ElevenLabs.

The realtime model normally speaks for itself - audio straight out of OpenAI,
from a handful of built-in voices that cannot really do accents. To give her a
designed voice (the Cockney robot), the realtime model is switched to text
output and an ElevenLabs TTS reads the words aloud. The model still listens,
thinks and calls tools exactly as before; only the mouth changes.

    "voice_output": {
      "provider": "elevenlabs",              # or "openai" (the default)
      "elevenlabs": {"voice_id": "...", "model": "eleven_flash_v2_5",
                     "stability": 0.45, "similarity_boost": 0.8,
                     "style": 0.35, "speed": 1.0},
      "fallback_openai_voice": "ash"
    }

Key: ELEVEN_API_KEY in .env (ELEVENLABS_API_KEY is accepted too).
Env overrides: ARGO_VOICE_PROVIDER, ARGO_ELEVENLABS_VOICE_ID.

The rule, as everywhere in Smooth Voice: a better voice must never cost her
the voice. Missing key, missing voice id or a missing plugin means the normal
OpenAI voice, logged and reported. At runtime ElevenLabs sits in a
FallbackAdapter with OpenAI's TTS behind it, so if ElevenLabs goes down
mid-session she keeps talking in the fallback voice.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from core import voice_events

logger = logging.getLogger("ARGO.VoiceOutput")

# LiveKit refuses to register a plugin anywhere but the main thread, and a
# session runs off it - importing ElevenLabs lazily inside build_tts() failed
# live with "Plugins must be registered on the main thread". So import it
# here, when the worker first loads this module.
try:
    from livekit.plugins import elevenlabs as _elevenlabs
except Exception as _exc:  # plugin not installed: the realtime voice is used
    _elevenlabs = None
    _ELEVENLABS_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
else:
    _ELEVENLABS_IMPORT_ERROR = ""

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "config.json"


@dataclass(frozen=True)
class ElevenLabsVoice:
    voice_id: str = ""
    name: str = ""
    model: str = "eleven_flash_v2_5"
    stability: float = 0.45
    similarity_boost: float = 0.8
    style: float = 0.35
    speed: float = 1.0


@dataclass(frozen=True)
class VoiceOutputSettings:
    provider: str = "openai"
    elevenlabs: ElevenLabsVoice = field(default_factory=ElevenLabsVoice)
    fallback_openai_voice: str = "ash"


def load_settings(config: dict | None = None) -> VoiceOutputSettings:
    if config is None:
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    raw = config.get("voice_output") or {}
    el = raw.get("elevenlabs") or {}
    base = ElevenLabsVoice()

    def num(key: str, default: float) -> float:
        try:
            return float(el.get(key, default))
        except (TypeError, ValueError):
            return default

    voice = ElevenLabsVoice(
        voice_id=(os.getenv("ARGO_ELEVENLABS_VOICE_ID") or str(el.get("voice_id") or "")).strip(),
        name=str(el.get("name") or ""),
        model=str(el.get("model") or base.model),
        stability=num("stability", base.stability),
        similarity_boost=num("similarity_boost", base.similarity_boost),
        style=num("style", base.style),
        speed=num("speed", base.speed),
    )
    provider = (os.getenv("ARGO_VOICE_PROVIDER") or str(raw.get("provider") or "openai")).strip().lower()
    return VoiceOutputSettings(provider=provider, elevenlabs=voice,
                               fallback_openai_voice=str(raw.get("fallback_openai_voice") or "ash"))


def elevenlabs_key() -> str:
    return (os.getenv("ELEVEN_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or "").strip()


def _fall_back(reason: str) -> None:
    logger.warning("[VoiceOutput] using the OpenAI realtime voice: %s", reason)
    voice_events.emit("voice_output_fallback", reason=reason)


def build_tts(settings: VoiceOutputSettings | None = None):
    """A TTS for the session, or None to let the realtime model speak itself."""
    try:
        settings = settings or load_settings()
        if settings.provider != "elevenlabs":
            return None
        key = elevenlabs_key()
        if not key:
            _fall_back("ELEVEN_API_KEY is not set in .env")
            return None
        voice = settings.elevenlabs
        if not voice.voice_id:
            _fall_back("voice_output.elevenlabs.voice_id is empty")
            return None
        if _elevenlabs is None:
            _fall_back(f"ElevenLabs plugin unavailable ({_ELEVENLABS_IMPORT_ERROR}); "
                       "pip install livekit-plugins-elevenlabs==1.5.17")
            return None
        from livekit.agents import tts as agents_tts
        from livekit.plugins import openai

        elevenlabs = _elevenlabs
        primary = elevenlabs.TTS(
            voice_id=voice.voice_id,
            model=voice.model,
            api_key=key,
            voice_settings=elevenlabs.VoiceSettings(
                stability=voice.stability, similarity_boost=voice.similarity_boost,
                style=voice.style, speed=voice.speed),
        )
        backup = openai.TTS(model="gpt-4o-mini-tts", voice=settings.fallback_openai_voice)
        logger.info("[VoiceOutput] ElevenLabs voice %s (%s), OpenAI %s as fallback",
                    voice.voice_id, voice.model, settings.fallback_openai_voice)
        voice_events.emit("voice_output", provider="elevenlabs", voice_id=voice.voice_id,
                          model=voice.model)
        return agents_tts.FallbackAdapter([primary, backup])
    except Exception as exc:
        _fall_back(f"{type(exc).__name__}: {exc}"[:200])
        return None


def status(settings: VoiceOutputSettings | None = None) -> dict:
    """What voice the NEXT Smooth Voice session will speak with, for the dashboard.
    No network calls - this only checks that everything needed is in place."""
    try:
        settings = settings or load_settings()
        voice = settings.elevenlabs
        if settings.provider != "elevenlabs":
            return {"provider": "openai", "ready": True, "label": "OpenAI realtime voice"}
        problems = []
        if not elevenlabs_key():
            problems.append("ELEVEN_API_KEY missing from .env")
        if not voice.voice_id:
            problems.append("no voice_id")
        # The dashboard backend imports this module off its main thread, where
        # LiveKit refuses plugin registration - so ask pip, not the import.
        try:
            from importlib.metadata import version

            version("livekit-plugins-elevenlabs")
        except Exception:
            problems.append("ElevenLabs plugin not installed")
        return {"provider": "elevenlabs", "ready": not problems, "voice_id": voice.voice_id,
                "model": voice.model, "label": voice.name or "ElevenLabs voice",
                "fallback": settings.fallback_openai_voice, "problems": problems}
    except Exception as exc:
        return {"provider": "unknown", "ready": False, "problems": [type(exc).__name__]}
