"""
Speech-to-Text Module

Responsibility: Accept audio, return text.
Nothing more.

Does NOT:
- Decide what the text means (no intent parsing)
- Trigger actions (no Coordinator integration)
- Handle wake words (input boundary only)
- Retry or stream (transcribe once, return once)
- Maintain memory or personality (stateless transcription)
"""

from abc import ABC, abstractmethod
import time

try:
    from core.instrumentation import log_event
except Exception:
    def log_event(event: str, stage: str = "", interaction_id: str = ""):
        pass


class SpeechToText(ABC):
    """
    Base class for speech-to-text engines.
    
    Single responsibility: Convert audio to text.
    """

    @abstractmethod
    def transcribe(self, audio_data: bytes, sample_rate: int) -> str:
        """
        Transcribe audio bytes to text.

        Args:
            audio_data: Raw audio bytes (WAV or similar format)
            sample_rate: Sample rate of audio (typically 16000 Hz)

        Returns:
            Transcribed text (single transcription, no streaming)

        Raises:
            ValueError: If audio is empty or invalid
        """
        pass

    def get_last_metrics(self) -> dict | None:
        return None


class WhisperSTT(SpeechToText):
    """
    OpenAI Whisper-based local speech-to-text.
    
    Uses the 'base' model for balance between accuracy and speed.
    Hardcoded settings for predictability.
    """

    def __init__(self):
        """Initialize Whisper model (downloads on first run)."""
        try:
            import whisper
        except ImportError:
            raise ImportError(
                "whisper not installed. Run: pip install openai-whisper"
            )

        self.whisper = whisper
        # Load base model (reasonable size, reasonable accuracy)
        # Hardcoded for predictability
        self.model = whisper.load_model("base")
        self.last_metrics = None

    def transcribe(self, audio_data: bytes, sample_rate: int) -> str:
        """
        Transcribe audio bytes using Whisper.

        Args:
            audio_data: Raw audio bytes (WAV format)
            sample_rate: Sample rate (e.g., 16000)

        Returns:
            Transcribed text

        Raises:
            ValueError: If audio is empty
        """
        if not audio_data:
            raise ValueError("audio_data is empty")

        # Write to temp file (Whisper expects file path or numpy array)
        import tempfile
        import numpy as np
        import io
        from scipy.io import wavfile

        # Parse WAV bytes to numpy array
        try:
            sample_rate_from_file, audio_array = wavfile.read(
                io.BytesIO(audio_data)
            )
            # Convert stereo to mono if needed
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)
            # Normalize to float32 [-1, 1]
            if audio_array.dtype != np.float32:
                audio_array = audio_array.astype(np.float32) / 32768.0
        except Exception as e:
            raise ValueError(f"Failed to parse audio: {e}")

        # Boost quiet speech slightly before Whisper
        audio_array = audio_array * 1.8
        audio_array = np.clip(audio_array, -1.0, 1.0)

        # Transcribe
        start = time.perf_counter()
        result = self.model.transcribe(
            audio_array,
            language="en",
            fp16=False,  # Force FP32 (CPU optimized, silences FP16 not supported warning)
            verbose=False,
            initial_prompt="User: ARGO, check the 3950X status.",
        )

        text = result.get("text", "").strip()
        duration_ms = (time.perf_counter() - start) * 1000
        rms = float(np.sqrt(np.mean(audio_array ** 2))) if len(audio_array) else 0.0
        silence_ratio = float(np.mean(np.abs(audio_array) < 0.01)) if len(audio_array) else 1.0
        conf = 0.0
        duration_s = len(audio_array) / float(sample_rate or 16000)
        if duration_s > 0:
            conf = min(1.0, (len(text) / max(1.0, duration_s * 10)) * (1.0 - silence_ratio))
        self.last_metrics = {
            "text_len": len(text),
            "rms": rms,
            "silence_ratio": silence_ratio,
            "confidence": conf,
            "duration_ms": duration_ms,
        }
        log_event(
            f"STT_DONE len={len(text)} rms={rms:.4f} silence={silence_ratio:.2f} conf={conf:.2f} {duration_ms:.0f}ms",
            stage="stt",
        )
        return text

    def get_last_metrics(self) -> dict | None:
        return self.last_metrics
