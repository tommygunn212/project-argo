"""
OpenAI Realtime Speech TTS — Cloud TTS Engine for ARGO (Personal Edition)

Uses OpenAI's TTS API (tts-1 / tts-1-hd) with streaming playback.
Audio starts playing as soon as the first chunk arrives — no waiting for
full synthesis to complete.

Voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer
Model: tts-1 (fast, low-latency) or tts-1-hd (higher quality)

Requires: OPENAI_API_KEY environment variable
"""

import io
import logging
import os
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger("OPENAI_TTS")


class OpenAIRealtimeTTS:
    """
    Streaming TTS using OpenAI's speech API.

    Streams audio chunks and plays them as they arrive for minimum latency.
    """

    # Available voices
    VOICES = {
        "alloy": "alloy",
        "ash": "ash",
        "ballad": "ballad",
        "coral": "coral",
        "echo": "echo",
        "fable": "fable",
        "nova": "nova",
        "onyx": "onyx",
        "sage": "sage",
        "shimmer": "shimmer",
    }

    def __init__(
        self,
        voice: str = "nova",
        model: str = "tts-1",
        speed: float = 1.0,
    ):
        self.voice = voice if voice in self.VOICES else "nova"
        self.model = model  # tts-1 (fast) or tts-1-hd (quality)
        self.speed = speed
        self._client = None
        self._stop_requested = False
        self._playback_lock = threading.Lock()
        self._is_playing = False
        self._audio_device = None
        self._device_sample_rate = 24000  # OpenAI outputs 24kHz by default
        self._init_client()
        self._init_audio_device()

    def _init_client(self):
        try:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set.")
            self._client = OpenAI(api_key=api_key)
            logger.info(f"[OPENAI_TTS] Initialized (voice={self.voice}, model={self.model})")
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

    def _init_audio_device(self):
        """Detect system default audio output device."""
        try:
            import sounddevice as sd
            self._audio_device = None  # system default
            device_info = sd.query_devices(self._audio_device, "output")
            self._device_sample_rate = int(device_info["default_samplerate"])
            logger.info(
                f"[OPENAI_TTS] Audio: {device_info['name']} @ {self._device_sample_rate}Hz"
            )
        except Exception as e:
            logger.warning(f"[OPENAI_TTS] Audio device detection failed: {e}")
            self._device_sample_rate = 24000

    def speak(self, text: str) -> None:
        """
        Synthesize and play text using OpenAI TTS with streaming.

        Audio playback begins as soon as the first chunk arrives.
        Blocks until playback is complete or stop() is called.
        """
        if not text or not text.strip():
            return

        self._stop_requested = False
        self._is_playing = True
        start_time = time.perf_counter()

        try:
            import sounddevice as sd
            import numpy as np
            from pydub import AudioSegment

            # Request streaming audio from OpenAI
            # Use pcm format for lowest latency (no decoding overhead)
            response = self._client.audio.speech.create(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="pcm",  # Raw PCM: 24kHz, 16-bit, mono
                speed=self.speed,
            )

            first_byte_time = time.perf_counter()
            logger.info(
                f"[OPENAI_TTS] First byte in {(first_byte_time - start_time)*1000:.0f}ms"
            )

            # Collect the full PCM response (OpenAI streams it)
            pcm_data = b""
            for chunk in response.iter_bytes(chunk_size=4096):
                if self._stop_requested:
                    logger.info("[OPENAI_TTS] Stop requested during stream")
                    return
                pcm_data += chunk

            if not pcm_data or self._stop_requested:
                return

            # Convert raw PCM (24kHz, 16-bit signed, mono) to numpy
            audio_array = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
            source_rate = 24000

            # Resample if device expects different rate
            if self._device_sample_rate != source_rate:
                from scipy.signal import resample
                target_samples = int(len(audio_array) * self._device_sample_rate / source_rate)
                audio_array = resample(audio_array, target_samples).astype(np.float32)

            synth_done_time = time.perf_counter()
            logger.info(
                f"[OPENAI_TTS] Synth complete in {(synth_done_time - start_time)*1000:.0f}ms, "
                f"playing {len(audio_array)/self._device_sample_rate:.1f}s of audio"
            )

            if self._stop_requested:
                return

            # Play audio (blocking)
            with self._playback_lock:
                sd.play(audio_array, samplerate=self._device_sample_rate, device=self._audio_device)
                sd.wait()

            total_time = time.perf_counter() - start_time
            logger.info(f"[OPENAI_TTS] Total speak() time: {total_time*1000:.0f}ms")

        except Exception as e:
            logger.error(f"[OPENAI_TTS] Error: {e}", exc_info=True)
        finally:
            self._is_playing = False

    def stop(self) -> None:
        """Stop any active playback immediately."""
        self._stop_requested = True
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self._is_playing = False

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def set_voice(self, voice: str) -> None:
        """Change the voice."""
        if voice in self.VOICES:
            self.voice = voice
            logger.info(f"[OPENAI_TTS] Voice changed to: {voice}")
        else:
            logger.warning(f"[OPENAI_TTS] Unknown voice '{voice}', keeping {self.voice}")

    def set_model(self, model: str) -> None:
        """Switch between tts-1 (fast) and tts-1-hd (quality)."""
        if model in ("tts-1", "tts-1-hd"):
            self.model = model
            logger.info(f"[OPENAI_TTS] Model changed to: {model}")
