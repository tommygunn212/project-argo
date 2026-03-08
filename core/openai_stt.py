"""
OpenAI Whisper API — Cloud STT Engine for ARGO (Personal Edition)

Uses OpenAI's Whisper API endpoint for fast, high-quality transcription.
Trades local-only principle for dramatically lower latency and better accuracy.

Requires: OPENAI_API_KEY environment variable
"""

import io
import logging
import time
import wave

import numpy as np

logger = logging.getLogger("OPENAI_STT")


class OpenAIWhisperSTT:
    """Cloud-based STT using OpenAI's Whisper API."""

    def __init__(self, model: str = "whisper-1", language: str = "en"):
        self.model = model
        self.language = language
        self._client = None
        self._init_client()

    def _init_client(self):
        import os
        try:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY not set. "
                    "Set it in your environment or .env file."
                )
            self._client = OpenAI(api_key=api_key)
            logger.info("[OPENAI_STT] Client initialized")
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )

    def _audio_to_wav_bytes(self, audio_data: np.ndarray, sample_rate: int = 16000) -> bytes:
        """Convert numpy audio array to WAV bytes for the API."""
        # Ensure float32 → int16
        if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
            audio_int16 = (audio_data * 32767).astype(np.int16)
        else:
            audio_int16 = audio_data.astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int16.tobytes())
        buf.seek(0)
        return buf.read()

    def transcribe(self, audio_data: np.ndarray, language: str = "en", **kwargs) -> dict:
        """
        Transcribe audio using OpenAI Whisper API.

        Args:
            audio_data: numpy float32 array of audio samples (16kHz mono)
            language: language code

        Returns:
            dict with text, confidence, segments, engine, duration_ms
        """
        start = time.perf_counter()

        wav_bytes = self._audio_to_wav_bytes(audio_data)

        # Create a file-like object with a name attribute (required by the API)
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "audio.wav"

        try:
            # Use verbose_json for segment-level detail
            response = self._client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

            duration_ms = (time.perf_counter() - start) * 1000

            text = response.text.strip() if response.text else ""

            # Extract segments if available
            segments = []
            confidence = 0.95  # OpenAI Whisper API doesn't return logprobs; high baseline
            if hasattr(response, "segments") and response.segments:
                for seg in response.segments:
                    segments.append({
                        "text": seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", ""),
                        "start": seg.get("start") if isinstance(seg, dict) else getattr(seg, "start", None),
                        "end": seg.get("end") if isinstance(seg, dict) else getattr(seg, "end", None),
                    })
                # Use avg_logprob if available
                logprobs = []
                for seg in response.segments:
                    lp = seg.get("avg_logprob") if isinstance(seg, dict) else getattr(seg, "avg_logprob", None)
                    if lp is not None:
                        logprobs.append(lp)
                if logprobs:
                    confidence = float(np.mean(logprobs))

            logger.info(
                f"[OPENAI_STT] Transcribed in {duration_ms:.0f}ms: "
                f"'{text[:60]}...' conf={confidence:.3f}"
            )

            return {
                "text": text,
                "confidence": confidence,
                "segments": segments,
                "engine": "openai_cloud",
                "duration_ms": duration_ms,
            }

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"[OPENAI_STT] Transcription failed ({duration_ms:.0f}ms): {e}")
            raise
