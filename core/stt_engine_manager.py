"""
STT Engine Manager

Explicit, deterministic Whisper engine selection and initialization.

Supported Engines:
- "openai": openai-whisper (original OpenAI implementation)
- "faster": faster-whisper (optimized version)

No automatic fallback. No dynamic switching. One engine per session.
Engine choice is explicit and logged.
"""

import logging
import numpy as np
from typing import Optional
from dataclasses import dataclass


@dataclass
class STTSegment:
    """Normalized STT segment structure (consistent across all engines)."""
    text: str
    start: float | None = None
    end: float | None = None


def verify_engine_dependencies(engine: str) -> None:
    """
    Verify that required dependencies for selected engine are installed.
    
    Called early in startup (before audio init) to fail fast with clear error.
    
    Args:
        engine: Engine name ("openai" or "faster")
    
    Raises:
        RuntimeError: If required package is not installed
    """
    logger = logging.getLogger("STT_ENGINE")
    
    if engine == "openai":
        try:
            import whisper  # noqa: F401
            logger.info("[STT_ENGINE] Preflight: openai-whisper dependency OK")
        except ImportError:
            raise RuntimeError(
                "STT engine 'openai' selected but openai-whisper is not installed. "
                "Run: pip install openai-whisper"
            )
    
    elif engine == "faster":
        try:
            from faster_whisper import WhisperModel  # noqa: F401
            logger.info("[STT_ENGINE] Preflight: faster-whisper dependency OK")
        except ImportError:
            raise RuntimeError(
                "STT engine 'faster' selected but faster-whisper is not installed. "
                "Run: pip install faster-whisper"
            )


class STTEngineManager:
    """Centralized STT engine initialization and selection."""

    SUPPORTED_ENGINES = ["openai", "faster"]
    DEFAULT_ENGINE = "openai"

    def __init__(self, engine: str = DEFAULT_ENGINE, model_size: str = "base", device: str = "cpu"):
        """
        Initialize STT engine manager.

        Args:
            engine: "openai" or "faster"
            model_size: Model size ("tiny", "base", "small", "medium", "large")
            device: "cpu" or "cuda"

        Raises:
            ValueError: If engine is not supported
        """
        if engine not in self.SUPPORTED_ENGINES:
            raise ValueError(
                f"Invalid STT_ENGINE: {engine}. "
                f"Supported: {', '.join(self.SUPPORTED_ENGINES)}"
            )

        self.engine = engine
        self.model_size = model_size
        self.device = device
        self.model = None
        self.logger = logging.getLogger("STT_ENGINE")

        self._load_engine()

    def _load_engine(self):
        """Load the selected Whisper engine."""
        if self.engine == "openai":
            self._load_openai_whisper()
        elif self.engine == "faster":
            self._load_faster_whisper()

    def _load_openai_whisper(self):
        """Load openai-whisper engine."""
        try:
            import whisper
        except ImportError:
            raise ImportError(
                "openai-whisper not installed. "
                "Run: pip install openai-whisper"
            )

        self.logger.info(
            f"[STT_ENGINE] Loading openai-whisper (model={self.model_size})..."
        )

        try:
            self.model = whisper.load_model(self.model_size, device=self.device)
            self.logger.info(
                f"[STT_ENGINE] openai-whisper loaded successfully "
                f"(engine=openai, model={self.model_size}, device={self.device})"
            )
        except Exception as e:
            self.logger.error(f"[STT_ENGINE] Failed to load openai-whisper: {e}")
            raise

    def _load_faster_whisper(self):
        """Load faster-whisper engine."""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper not installed. "
                "Run: pip install faster-whisper"
            )

        self.logger.info(
            f"[STT_ENGINE] Loading faster-whisper (model={self.model_size}.en)..."
        )

        try:
            self.model = WhisperModel(
                f"{self.model_size}.en",
                device=self.device,
                compute_type="float16" if self.device == "cuda" else "int8"
            )
            self.logger.info(
                f"[STT_ENGINE] faster-whisper loaded successfully "
                f"(engine=faster, model={self.model_size}.en, device={self.device})"
            )
        except Exception as e:
            self.logger.error(f"[STT_ENGINE] Failed to load faster-whisper: {e}")
            raise

    def _normalize_segments(self, raw_segments) -> list:
        """
        Normalize segments to a consistent STTSegment structure.
        
        Handles different segment formats:
        - openai-whisper: list of dicts with 'text', 'start', 'end'
        - faster-whisper: list of Segment objects with .text, .start, .end
        
        Returns:
            List of STTSegment objects with guaranteed .text attribute
        """
        normalized = []
        
        for seg in raw_segments:
            if isinstance(seg, STTSegment):
                # Already normalized
                normalized.append(seg)
            elif isinstance(seg, dict):
                # openai-whisper dict format
                normalized.append(STTSegment(
                    text=seg.get("text", ""),
                    start=seg.get("start"),
                    end=seg.get("end")
                ))
            else:
                # faster-whisper Segment object or other (has .text attribute)
                text = getattr(seg, "text", str(seg))
                start = getattr(seg, "start", None)
                end = getattr(seg, "end", None)
                normalized.append(STTSegment(
                    text=text,
                    start=start,
                    end=end
                ))
        
        return normalized

    def transcribe(self, audio_data: np.ndarray, language: str = "en", **kwargs) -> dict:
        """
        Transcribe audio using the selected engine.

        Args:
            audio_data: Audio samples (float32, [-1, 1])
            language: Language code (e.g., "en")
            **kwargs: Additional engine-specific parameters

        Returns:
            {
                "text": str,
                "confidence": float (engine-native),
                "segments": list,
                "engine": "openai" | "faster",
                "duration_ms": float
            }

        Raises:
            ValueError: If transcription fails
        """
        if self.model is None:
            raise ValueError("STT engine not initialized")

        import time
        start = time.perf_counter()

        try:
            if self.engine == "openai":
                return self._transcribe_openai(audio_data, language, **kwargs)
            elif self.engine == "faster":
                return self._transcribe_faster(audio_data, language, **kwargs)
        except Exception as e:
            self.logger.error(f"[STT_ENGINE] Transcription failed: {e}")
            raise

    def _transcribe_openai(self, audio_data: np.ndarray, language: str, **kwargs) -> dict:
        """Transcribe using openai-whisper."""
        import time

        start = time.perf_counter()

        # Apply audio boost before transcription
        audio_data = audio_data * 1.8
        audio_data = np.clip(audio_data, -1.0, 1.0)

        result = self.model.transcribe(
            audio_data,
            language=language,
            verbose=False,
            fp16=False,  # Force FP32
            **kwargs
        )

        text = result.get("text", "").strip()
        duration_ms = (time.perf_counter() - start) * 1000

        # Calculate confidence from logprobs if available
        confidence = 0.0
        raw_segments = result.get("segments", [])
        if raw_segments:
            logprobs = [seg.get("avg_logprob", 0) for seg in raw_segments]
            if logprobs:
                confidence = float(np.mean(logprobs))  # Will be negative (log scale)

        # Normalize segments to consistent structure
        normalized_segments = self._normalize_segments(raw_segments)

        return {
            "text": text,
            "confidence": confidence,  # Engine-native (log scale for openai-whisper)
            "segments": normalized_segments,
            "engine": "openai",
            "duration_ms": duration_ms,
        }

    def _transcribe_faster(self, audio_data: np.ndarray, language: str, **kwargs) -> dict:
        """Transcribe using faster-whisper."""
        import time

        start = time.perf_counter()

        segments, info = self.model.transcribe(
            audio_data,
            language=language,
            **kwargs
        )

        segments_list = list(segments)
        text = " ".join([seg.text for seg in segments_list]).strip()
        duration_ms = (time.perf_counter() - start) * 1000

        # Calculate confidence from logprobs
        confidence = 0.0
        if segments_list:
            logprobs = [seg.avg_logprob for seg in segments_list]
            if logprobs:
                confidence = float(np.mean(logprobs))  # Will be negative (log scale)

        # Normalize segments to consistent structure
        normalized_segments = self._normalize_segments(segments_list)

        return {
            "text": text,
            "confidence": confidence,  # Engine-native (log scale)
            "segments": normalized_segments,
            "engine": "faster",
            "duration_ms": duration_ms,
        }

    def warmup(self, duration_s: float = 1.0):
        """
        Warmup the STT engine.

        Args:
            duration_s: Duration of dummy audio to transcribe
        """
        self.logger.info(f"[STT_ENGINE] Warming up {self.engine} engine...")

        try:
            dummy_audio = np.zeros(int(16000 * duration_s), dtype=np.float32)
            self.transcribe(dummy_audio, beam_size=1 if self.engine == "faster" else None)
            self.logger.info(f"[STT_ENGINE] {self.engine} engine warmed up successfully")
        except Exception as e:
            self.logger.warning(f"[STT_ENGINE] Warmup failed: {e}")
