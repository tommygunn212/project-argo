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
    Supports barge-in interruption and suppression.
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
        "verse": "verse",
        "marin": "marin",
        "cedar": "cedar",
    }

    # Minimum chunk size before we start playback (bytes of PCM)
    # ~100ms of 24kHz 16-bit mono = 4800 bytes
    STREAM_BUFFER_BYTES = 4800

    def __init__(
        self,
        voice: str = "nova",
        model: str = "tts-1",
        speed: float = 1.0,
    ):
        self.voice = voice if voice in self.VOICES else "nova"
        self.model = model  # tts-1, tts-1-hd, or gpt-4o-mini-tts
        self.speed = speed
        self._client = None
        self._stop_requested = False
        self._playback_lock = threading.Lock()
        self._is_playing = False
        self._audio_device = None
        self._device_sample_rate = 24000  # OpenAI outputs 24kHz by default
        self._interrupt_suppress_until = 0.0  # timestamp until which barge-in is suppressed
        self._instructions = None  # gpt-4o-mini-tts speech style instructions
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
        Synthesize and play text using OpenAI TTS with true streaming.

        Audio playback begins after STREAM_BUFFER_BYTES of PCM arrive,
        then continues filling the buffer while playing. This gives
        near-instant time-to-first-audio and allows barge-in to stop
        playback at any point.
        """
        if not text or not text.strip():
            return

        self._stop_requested = False
        self._is_playing = True
        start_time = time.perf_counter()

        try:
            import sounddevice as sd
            import numpy as np

            # Build API call kwargs
            api_kwargs = dict(
                model=self.model,
                voice=self.voice,
                input=text,
                response_format="pcm",  # Raw PCM: 24kHz, 16-bit, mono
                speed=self.speed,
            )
            # gpt-4o-mini-tts supports 'instructions' for speech style control
            if self._instructions and "gpt-4o" in self.model:
                api_kwargs["instructions"] = self._instructions

            response = self._client.audio.speech.create(**api_kwargs)

            first_byte_time = time.perf_counter()
            logger.info(
                f"[OPENAI_TTS] First byte in {(first_byte_time - start_time)*1000:.0f}ms"
            )

            # --- True streaming playback ---
            # Collect an initial buffer, start playing, then keep feeding chunks.
            pcm_chunks = []
            total_bytes = 0
            playback_started = False
            stream = None
            write_idx = 0
            source_rate = 24000

            for chunk in response.iter_bytes(chunk_size=4096):
                if self._stop_requested:
                    logger.info("[OPENAI_TTS] Stop requested during stream")
                    return
                pcm_chunks.append(chunk)
                total_bytes += len(chunk)

                # Once we have enough data, start playback in a non-blocking stream
                if not playback_started and total_bytes >= self.STREAM_BUFFER_BYTES:
                    playback_started = True
                    initial_pcm = b"".join(pcm_chunks)
                    audio_arr = np.frombuffer(initial_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    if self._device_sample_rate != source_rate:
                        from scipy.signal import resample
                        target_len = int(len(audio_arr) * self._device_sample_rate / source_rate)
                        audio_arr = resample(audio_arr, target_len).astype(np.float32)
                    with self._playback_lock:
                        sd.play(audio_arr, samplerate=self._device_sample_rate, device=self._audio_device, blocking=False)
                    write_idx = len(audio_arr)
                    logger.info(
                        f"[OPENAI_TTS] Streaming playback started at {(time.perf_counter() - start_time)*1000:.0f}ms"
                    )

            if self._stop_requested:
                return

            # Combine all remaining chunks
            all_pcm = b"".join(pcm_chunks)
            if not all_pcm:
                return

            full_audio = np.frombuffer(all_pcm, dtype=np.int16).astype(np.float32) / 32768.0

            if self._device_sample_rate != source_rate:
                from scipy.signal import resample
                target_len = int(len(full_audio) * self._device_sample_rate / source_rate)
                full_audio = resample(full_audio, target_len).astype(np.float32)

            synth_done_time = time.perf_counter()
            logger.info(
                f"[OPENAI_TTS] Synth complete in {(synth_done_time - start_time)*1000:.0f}ms, "
                f"duration {len(full_audio)/self._device_sample_rate:.1f}s"
            )

            if self._stop_requested:
                return

            # If we already started streaming, stop and replay the full audio
            # (simplest approach that handles the tail correctly)
            if playback_started:
                sd.stop()
                if self._stop_requested:
                    return

            # Play the complete audio
            with self._playback_lock:
                sd.play(full_audio, samplerate=self._device_sample_rate, device=self._audio_device)
                # Poll instead of blocking sd.wait() so we can respond to stop quickly
                while sd.get_stream() and sd.get_stream().active:
                    if self._stop_requested:
                        sd.stop()
                        logger.info("[OPENAI_TTS] Barge-in stopped playback")
                        return
                    time.sleep(0.01)  # 10ms polling — fast barge-in response

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
        logger.info("[OPENAI_TTS] Stop signal sent")

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def suppress_interrupt(self, seconds: float) -> None:
        """Suppress barge-in interruption for the given duration."""
        self._interrupt_suppress_until = time.time() + seconds
        logger.info(f"[OPENAI_TTS] Barge-in suppressed for {seconds:.1f}s")

    def is_interrupt_suppressed(self) -> bool:
        """Check if barge-in is currently suppressed."""
        return time.time() < self._interrupt_suppress_until

    def set_instructions(self, instructions: str) -> None:
        """Set speech style instructions (only effective with gpt-4o-mini-tts)."""
        self._instructions = instructions
        logger.info(f"[OPENAI_TTS] Instructions set ({len(instructions)} chars)")

    def set_voice(self, voice: str) -> None:
        """Change the voice."""
        if voice in self.VOICES:
            self.voice = voice
            logger.info(f"[OPENAI_TTS] Voice changed to: {voice}")
        else:
            logger.warning(f"[OPENAI_TTS] Unknown voice '{voice}', keeping {self.voice}")

    def set_model(self, model: str) -> None:
        """Switch between tts-1, tts-1-hd, or gpt-4o-mini-tts."""
        if model in ("tts-1", "tts-1-hd", "gpt-4o-mini-tts"):
            self.model = model
            logger.info(f"[OPENAI_TTS] Model changed to: {model}")
