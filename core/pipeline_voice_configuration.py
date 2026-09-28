"""Runtime voice and TTS model selection for the classic pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


VALID_OPENAI_TTS_MODELS = frozenset(
    {"tts-1", "tts-1-hd", "gpt-4o-mini-tts"}
)


@dataclass(frozen=True)
class PipelineVoiceConfigurationDependencies:
    openai_voices: Callable[[], Mapping[str, str]]
    edge_voices: Callable[[], Mapping[str, str]]
    get_openai_tts: Callable[[], Any]
    get_edge_tts: Callable[[], Any]
    get_tts_model: Callable[[], str]
    set_voice_key: Callable[[str], None]
    set_tts_engine: Callable[[str], None]
    set_tts_model: Callable[[str], None]
    clear_openai_tts: Callable[[], None]
    broadcast: Callable[[str, Any], None]
    logger: Any


class PipelineVoiceConfigurationService:
    """Apply voice changes without depending on the full pipeline object."""

    def __init__(self, dependencies: PipelineVoiceConfigurationDependencies):
        self._dependencies = dependencies

    def set_voice(self, voice_key: str) -> bool:
        dependencies = self._dependencies
        if voice_key in dependencies.openai_voices():
            dependencies.set_voice_key(voice_key)
            dependencies.set_tts_engine("openai")
            client = dependencies.get_openai_tts()
            if client is not None:
                client.set_voice(voice_key)
            dependencies.logger.info(
                "Voice switched to OpenAI: %s", voice_key
            )
            dependencies.broadcast(
                "log", f"System: Voice switched to OpenAI {voice_key.upper()}"
            )
            return True

        edge_voices = dependencies.edge_voices()
        if voice_key in edge_voices:
            dependencies.set_voice_key(voice_key)
            dependencies.set_tts_engine("edge")
            client = dependencies.get_edge_tts()
            if client is not None:
                try:
                    client.voice = edge_voices[voice_key]
                except Exception:
                    pass
            dependencies.logger.info(
                "Voice switched to %s: %s", voice_key, edge_voices[voice_key]
            )
            dependencies.broadcast(
                "log", f"System: Voice profile switched to {voice_key.upper()}"
            )
            return True
        return False

    def set_tts_model(self, model: str) -> bool:
        dependencies = self._dependencies
        if model not in VALID_OPENAI_TTS_MODELS:
            dependencies.logger.warning("[TTS] Unknown model: %s", model)
            return False
        if model == dependencies.get_tts_model():
            return True
        dependencies.set_tts_model(model)
        dependencies.clear_openai_tts()
        dependencies.logger.info(
            "[TTS] Model switched to %s (will reinit on next speak)", model
        )
        dependencies.broadcast("log", f"System: TTS model switched to {model}")
        return True
