"""Startup composition for the classic audio pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping, Protocol

from core.config import MUSIC_DB_PATH
from core.database import get_db_status, music_db_exists
from core.startup_checks import check_ollama


class AudioRuntime(Protocol):
    def start(self) -> None: ...


class PipelineRuntime(Protocol):
    def set_llm_enabled(self, enabled: bool) -> None: ...

    def warmup(self) -> None: ...


def start_classic_runtime(
    audio: AudioRuntime,
    pipeline: PipelineRuntime,
    config: Any,
    broadcast: Callable[[str, Any], None],
    logger: logging.Logger,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Start classic dependencies and return whether its LLM is available."""
    environment = os.environ if environment is None else environment
    audio.start()

    llm_config = config.get("llm", {})
    if isinstance(llm_config, dict):
        llm_backend = str(llm_config.get("backend", "ollama")).lower()
    else:
        llm_backend = str(config.get("llm.backend", "ollama")).lower()
    require_llm = bool(config.get("llm.required", False))

    if llm_backend == "openai":
        llm_available = bool(environment.get("OPENAI_API_KEY"))
        if require_llm and not llm_available:
            raise RuntimeError("LLM required but OPENAI_API_KEY is not set")
        if llm_available:
            logger.info("OpenAI LLM configured")
        else:
            logger.info(
                "LLM offline: OPENAI_API_KEY missing; running in no-brain mode"
            )
    else:
        llm_available = check_ollama()
        if require_llm and not llm_available:
            raise RuntimeError("LLM required but Ollama is not running")
        if llm_available:
            logger.info("Ollama online")
        else:
            logger.info("LLM offline: running in no-brain mode")

    db_ready = music_db_exists(MUSIC_DB_PATH)
    db_status = get_db_status(MUSIC_DB_PATH)
    if db_ready:
        logger.info("Music DB detected")
    else:
        logger.info("Music DB not present (awaiting Jellyfin ingest)")
    broadcast("db_status", db_status)

    pipeline.set_llm_enabled(llm_available)
    pipeline.warmup()
    return llm_available
