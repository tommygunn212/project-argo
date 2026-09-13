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
    # ~75ms of 24kHz 16-bit mono = 3600 bytes
    STREAM_BUFFER_BYTES = 3600

    def __init__(
        self,
        voice: str = "nova",
        model: str = "tts-1",
        speed: float = 1.02,
        output_device=None,
        timeout_seconds: float = 15.0,
        on_audio_level=None,
    ):
        self.voice = voice if voice in self.VOICES else "nova"
        self.model = model  # tts-1, tts-1-hd, or gpt-4o-mini-tts
        self.speed = speed
        self._client = None
        self._stop_requested = False
        self._cancel_lock = threading.Lock()
        self._cancel_generation = 0
        self._playback_lock = threading.Lock()
        self._is_playing = False
        self._audio_device = output_device
        self._active_stream = None
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._device_sample_rate = 24000  # OpenAI outputs 24kHz by default
        self._interrupt_suppress_until = 0.0  # timestamp until which barge-in is suppressed
        self._instructions = None  # gpt-4o-mini-tts speech style instructions
        self._on_audio_level = on_audio_level
        self._init_client()
        self._init_audio_device()

    def _init_client(self):
        try:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set.")
            self._client = OpenAI(api_key=api_key, timeout=self._timeout_seconds, max_retries=0)
            logger.info(f"[OPENAI_TTS] Initialized (voice={self.voice}, model={self.model})")
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

    def _init_audio_device(self):
        """Use the same selected output device as AudioManager."""
        try:
            import sounddevice as sd
            device_info = sd.query_devices(self._audio_device, "output")
            self._device_sample_rate = int(device_info["default_samplerate"])
            logger.info(
                f"[OPENAI_TTS] Audio: {device_info['name']} @ {self._device_sample_rate}Hz"
            )
        except Exception as e:
            logger.warning(f"[OPENAI_TTS] Audio device detection failed: {e}")
            self._device_sample_rate = 24000

    def begin_response(self) -> int:
        """Start a fresh TTS response generation and return its cancel token."""
        with self._cancel_lock:
            self._cancel_generation += 1
            self._stop_requested = False
            return self._cancel_generation

    def current_generation(self) -> int:
        with self._cancel_lock:
            return self._cancel_generation

    def is_cancelled(self, generation: Optional[int] = None) -> bool:
        with self._cancel_lock:
            stale = generation is not None and generation != self._cancel_generation
            return self._stop_requested or stale

    def _mark_playing(self, playing: bool, generation: int) -> None:
        with self._cancel_lock:
            if generation == self._cancel_generation:
                self._is_playing = playing

    def _speech_kwargs(self, text):
        kwargs = dict(model=self.model, voice=self.voice, input=text,
                      response_format="pcm", speed=self.speed)
        if "gpt-4o" in self.model:
            instructions = (self._instructions or "").strip()
            if any("\u3400" <= char <= "\u9fff" for char in text):
                chinese_instruction = (
                    "When the input contains Chinese characters, pronounce every Chinese phrase "
                    "clearly in Mandarin Chinese. Do not skip, spell out, transliterate, or replace "
                    "the Chinese characters."
                )
                instructions = " ".join(part for part in (instructions, chinese_instruction) if part)
            if instructions:
                kwargs["instructions"] = instructions
        return kwargs

    def _response_chunks(self, text, generation):
        # The context manager keeps HTTP streaming enabled and closes the
        # connection on EOF, failure, cancellation, or generator.close().
        start = time.perf_counter()
        first = True
        with self._client.audio.speech.with_streaming_response.create(
            **self._speech_kwargs(text)
        ) as response:
            for chunk in response.iter_bytes(chunk_size=1024):
                if self.is_cancelled(generation):
                    return
                if not chunk:
                    continue
                if first:
                    logger.info("[OPENAI_TTS] First PCM bytes in %.0fms",
                                (time.perf_counter() - start) * 1000)
                    first = False
                yield chunk

    def speak(self, text: str, generation: Optional[int] = None) -> None:
        """Play PCM before synthesis completes, with bounded HTTP idle waits."""
        if not text or not text.strip():
            return
        if generation is None:
            generation = self.begin_response()
        if self.is_cancelled(generation):
            return
        chunks = self._response_chunks(text, generation)
        try:
            self._play_chunks(chunks, generation)
        finally:
            chunks.close()

    def synthesize(self, text: str, generation: Optional[int] = None) -> Optional[bytes]:
        """Buffer one prefetched sentence using the reusable streaming client."""
        if not text or not text.strip():
            return None
        if generation is None:
            generation = self.current_generation()
        if self.is_cancelled(generation):
            return None
        chunks = self._response_chunks(text, generation)
        try:
            pcm = b"".join(chunks)
            return None if self.is_cancelled(generation) else pcm
        finally:
            chunks.close()

    def play_pcm(self, pcm_data: bytes, generation: Optional[int] = None) -> None:
        """Play prefetched PCM through the same device and cancellation path."""
        if not pcm_data:
            return
        if generation is None:
            generation = self.current_generation()
        chunks = (pcm_data[i:i + 4096] for i in range(0, len(pcm_data), 4096))
        self._play_chunks(chunks, generation)

    def _play_chunks(self, chunks, generation):
        if self.is_cancelled(generation):
            return
        import numpy as np
        import sounddevice as sd
        from core.streaming_resampler import StreamingResampler

        # Only a playback owner touches start/write/stop/close. Cancellation
        # aborts that particular stream; it never invokes global sd.stop().
        with self._playback_lock:
            if self.is_cancelled(generation):
                return
            self._mark_playing(True, generation)
            stream = None
            pcm = bytearray()
            converter = StreamingResampler(24000, self._device_sample_rate)

            def write_samples(samples):
                nonlocal stream
                if not len(samples) or self.is_cancelled(generation):
                    return
                if stream is None:
                    stream = sd.OutputStream(
                        samplerate=self._device_sample_rate, channels=1,
                        dtype="float32", device=self._audio_device, blocksize=0,
                    )
                    # Serialize publication/start against stop() so an old
                    # generation cannot start playing after it was cancelled.
                    with self._cancel_lock:
                        if self._stop_requested or generation != self._cancel_generation:
                            return
                        stream.start()
                        self._active_stream = stream
                # Small writes also bound cancellation response on devices
                # where abort cannot immediately unblock a native write.
                block = max(1, int(self._device_sample_rate * 0.025))
                for offset in range(0, len(samples), block):
                    if self.is_cancelled(generation):
                        return
                    underflow = stream.write(samples[offset:offset + block].reshape(-1, 1))
                    if not self.is_cancelled(generation):
                        level = float(np.sqrt(np.mean(samples[offset:offset + block] ** 2)))
                        self._emit_audio_level(level)
                    if underflow:
                        logger.warning("[OPENAI_TTS] Output underflow")

            try:
                for chunk in chunks:
                    if self.is_cancelled(generation):
                        return
                    pcm.extend(chunk)
                    if len(pcm) < self.STREAM_BUFFER_BYTES and stream is None:
                        continue
                    size = len(pcm) // 2 * 2
                    if size:
                        samples = np.frombuffer(bytes(pcm[:size]), dtype="<i2").astype(np.float32) / 32768.0
                        del pcm[:size]
                        write_samples(converter.process(samples))
                if self.is_cancelled(generation):
                    return
                if len(pcm) % 2:
                    raise ValueError("TTS returned a truncated 16-bit PCM sample")
                samples = np.frombuffer(bytes(pcm), dtype="<i2").astype(np.float32) / 32768.0
                write_samples(converter.process(samples, final=True))
                if stream and not self.is_cancelled(generation):
                    # PortAudio drains its actual pending buffers. Do not add
                    # an estimated sentence-duration sleep on top of writes.
                    stream.stop()
            except Exception:
                if not self.is_cancelled(generation):
                    logger.exception("[OPENAI_TTS] Playback failed")
                    raise
            finally:
                with self._cancel_lock:
                    if getattr(self, "_active_stream", None) is stream:
                        self._active_stream = None
                    if stream:
                        try:
                            stream.abort()
                            stream.close()
                        except Exception:
                            logger.debug("[OPENAI_TTS] Stream cleanup failed", exc_info=True)
                self._mark_playing(False, generation)
                self._emit_audio_level(0.0)

    def _emit_audio_level(self, level: float) -> None:
        # UI metering observes existing playback; it cannot own or stop audio.
        callback = getattr(self, "_on_audio_level", None)
        if callback is not None:
            try:
                callback(level)
            except Exception:
                logger.debug("[OPENAI_TTS] Avatar meter unavailable", exc_info=True)

    def stop(self) -> None:
        """Invalidate speech and abort only the TTS-owned output stream."""
        with self._cancel_lock:
            self._stop_requested = True
            self._cancel_generation += 1
            self._is_playing = False
            stream = getattr(self, "_active_stream", None)
            if stream is not None:
                try:
                    stream.abort()
                except Exception:
                    logger.debug("[OPENAI_TTS] Stream already stopped", exc_info=True)
        self._emit_audio_level(0.0)
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
