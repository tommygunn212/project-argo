"""Classic pipeline model initialization behind a narrow dependency boundary."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WarmupDependencies:
    logger: Any
    config: dict[str, Any] | None
    audio_output_device: int | None
    runtime_overrides: dict[str, Any]
    llm_enabled: bool
    llm_router: Any
    stt_manager_factory: Callable[..., Any]
    verify_stt_dependencies: Callable[[str], None]
    stt_prompt_profile: str
    tts_instructions: str
    broadcast_audio_level: Callable[[float], None]


@dataclass(frozen=True)
class WarmupResult:
    stt_manager: Any
    stt_engine: str
    stt_model_name: str
    tts_engine: str
    tts_model: str
    openai_tts: Any | None
    current_voice_key: str | None
    llm_model_name: str | None
    personal_mode: bool


def initialize_pipeline_runtime(
    dependencies: WarmupDependencies,
) -> WarmupResult:
    """Initialize configured providers and return state for the orchestrator."""
    if dependencies.stt_prompt_profile:
        dependencies.logger.info(
            f"[STT] Prompt profile: {dependencies.stt_prompt_profile}"
        )

    cache_dir = Path(__file__).resolve().parent.parent / ".hf_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache_dir / "hub"))

    stt_engine = "openai"
    stt_model_size = "base"
    stt_device = "cpu"
    config = dependencies.config
    if config is not None:
        stt_config = config.get("speech_to_text", {})
        if isinstance(stt_config, dict):
            stt_engine = stt_config.get("engine", "openai")
            stt_model_size = stt_config.get("model", "base")
            stt_device = stt_config.get("device", "cpu")

    supported_engines = dependencies.stt_manager_factory.SUPPORTED_ENGINES
    if stt_engine not in supported_engines:
        dependencies.logger.error(
            f"Invalid STT_ENGINE: {stt_engine}. "
            f"Supported: {', '.join(supported_engines)}"
        )
        raise ValueError(f"Invalid STT engine: {stt_engine}")

    dependencies.logger.info(
        f"[STT] Engine configuration: engine={stt_engine}, "
        f"model={stt_model_size}, device={stt_device}"
    )
    dependencies.verify_stt_dependencies(stt_engine)
    stt_manager = dependencies.stt_manager_factory(
        engine=stt_engine,
        model_size=stt_model_size,
        device=stt_device,
    )
    dependencies.logger.info(
        f"[STT] STT engine ready (engine={stt_engine}, "
        f"model={stt_model_size}, device={stt_device})"
    )

    tts_engine = "edge"
    tts_voice = None
    tts_model = "tts-1"
    if config is not None:
        tts_config = config.get("text_to_speech", {})
        if isinstance(tts_config, dict):
            tts_engine = tts_config.get("engine", "edge")
            tts_voice = tts_config.get("voice", None)
            tts_model = tts_config.get("model", "tts-1")

    openai_tts = None
    current_voice_key = None
    try:
        if tts_engine == "openai":
            from core.openai_tts import OpenAIRealtimeTTS

            voice = tts_voice or "nova"
            openai_tts = OpenAIRealtimeTTS(
                voice=voice,
                model=tts_model,
                output_device=dependencies.audio_output_device,
                on_audio_level=dependencies.broadcast_audio_level,
            )
            openai_tts._instructions = dependencies.tts_instructions
            current_voice_key = voice
            dependencies.logger.info(
                f"[TTS] OpenAI Realtime Speech ready "
                f"(voice={voice}, model={tts_model})"
            )
        else:
            dependencies.logger.info("[TTS] Edge TTS engine selected")
    except Exception as exc:
        dependencies.logger.warning(
            f"[TTS] OpenAI TTS init failed, falling back to Edge: {exc}"
        )
        tts_engine = "edge"
        openai_tts = None
        current_voice_key = None

    personal_mode = bool(dependencies.runtime_overrides.get("personal_mode", False))
    if personal_mode:
        dependencies.logger.info(
            "[PERSONAL] Personal mode active — gates loosened, "
            "confidence floors removed"
        )

    llm_model_name = None
    if dependencies.llm_enabled:
        try:
            llm_model_name = dependencies.llm_router.primary_model_name
            dependencies.llm_router.warmup()
            dependencies.logger.info(
                "[LLM] Provider router ready (primary=%s)", llm_model_name
            )
        except Exception as exc:
            dependencies.logger.warning(f"LLM Warmup Warning: {exc}")

    return WarmupResult(
        stt_manager=stt_manager,
        stt_engine=stt_engine,
        stt_model_name=stt_model_size,
        tts_engine=tts_engine,
        tts_model=tts_model,
        openai_tts=openai_tts,
        current_voice_key=current_voice_key,
        llm_model_name=llm_model_name,
        personal_mode=personal_mode,
    )
