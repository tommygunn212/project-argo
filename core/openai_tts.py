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

    def speak(self, text: str, generation: Optional[int] = None) -> None:
        """
        Synthesize and play text using OpenAI TTS.

        Streams PCM from the API directly into an audio output stream,
        starting playback as soon as the first chunk arrives for minimum
        inter-sentence latency.  Supports barge-in via _stop_requested.
        """
        if not text or not text.strip():
            return

        if generation is None:
            generation = self.begin_response()
        if self.is_cancelled(generation):
            logger.info("[OPENAI_TTS] speak skipped after stop")
            return
        self._mark_playing(True, generation)
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

            if self.is_cancelled(generation):
                logger.info("[OPENAI_TTS] speak cancelled before request")
                return

            response = self._client.audio.speech.create(**api_kwargs)

            if self.is_cancelled(generation):
                logger.info("[OPENAI_TTS] speak cancelled before playback")
                return

            first_byte_time = time.perf_counter()
            logger.info(
                f"[OPENAI_TTS] First byte in {(first_byte_time - start_time)*1000:.0f}ms"
            )

            source_rate = 24000
            need_resample = self._device_sample_rate != source_rate

            # Stream directly to output — no collect-then-play gap
            pcm_buffer = bytearray()
            playback_started = False
            playback_start_time = 0.0
            stream = None
            total_samples_written = 0

            try:
                for chunk in response.iter_bytes(chunk_size=4096):
                    if self.is_cancelled(generation):
                        logger.info("[OPENAI_TTS] Stop requested during stream")
                        return
                    pcm_buffer.extend(chunk)

                    # Start playback once we have enough buffered
                    if not playback_started and len(pcm_buffer) >= self.STREAM_BUFFER_BYTES:
                        stream = sd.OutputStream(
                            samplerate=self._device_sample_rate,
                            channels=1,
                            dtype='float32',
                            device=self._audio_device,
                            blocksize=2048,
                        )
                        stream.start()
                        playback_started = True
                        playback_start_time = time.perf_counter()

                    # Write accumulated audio to the stream in chunks
                    if playback_started and len(pcm_buffer) >= self.STREAM_BUFFER_BYTES:
                        audio_f32 = np.frombuffer(bytes(pcm_buffer), dtype=np.int16).astype(np.float32) / 32768.0
                        if need_resample:
                            from scipy.signal import resample
                            target_len = int(len(audio_f32) * self._device_sample_rate / source_rate)
                            audio_f32 = resample(audio_f32, target_len).astype(np.float32)
                        if self.is_cancelled(generation):
                            logger.info("[OPENAI_TTS] Stop requested before stream write")
                            return
                        stream.write(audio_f32.reshape(-1, 1))
                        total_samples_written += len(audio_f32)
                        pcm_buffer.clear()

                # Flush any remaining audio
                if pcm_buffer and playback_started and stream:
                    if not self.is_cancelled(generation):
                        audio_f32 = np.frombuffer(bytes(pcm_buffer), dtype=np.int16).astype(np.float32) / 32768.0
                        if need_resample:
                            from scipy.signal import resample
                            target_len = int(len(audio_f32) * self._device_sample_rate / source_rate)
                            audio_f32 = resample(audio_f32, target_len).astype(np.float32)
                        if self.is_cancelled(generation):
                            logger.info("[OPENAI_TTS] Stop requested before final stream write")
                            return
                        stream.write(audio_f32.reshape(-1, 1))
                        total_samples_written += len(audio_f32)
                    pcm_buffer.clear()
                elif pcm_buffer and not playback_started:
                    # Short text: all audio arrived before buffer threshold
                    audio_f32 = np.frombuffer(bytes(pcm_buffer), dtype=np.int16).astype(np.float32) / 32768.0
                    if need_resample:
                        from scipy.signal import resample
                        target_len = int(len(audio_f32) * self._device_sample_rate / source_rate)
                        audio_f32 = resample(audio_f32, target_len).astype(np.float32)
                    if self.is_cancelled(generation):
                        logger.info("[OPENAI_TTS] Stop requested before short playback")
                        return
                    sd.play(audio_f32, samplerate=self._device_sample_rate, device=self._audio_device)
                    while sd.get_stream() and sd.get_stream().active:
                        if self.is_cancelled(generation):
                            sd.stop()
                            return
                        time.sleep(0.01)
                    total_samples_written = len(audio_f32)

                # Wait for the OutputStream to drain (only the remaining time)
                if stream and playback_start_time > 0:
                    total_duration = total_samples_written / self._device_sample_rate
                    elapsed = time.perf_counter() - playback_start_time
                    remaining = max(0, total_duration - elapsed + 0.05)
                    drain_start = time.perf_counter()
                    while (time.perf_counter() - drain_start) < remaining:
                        if self.is_cancelled(generation):
                            logger.info("[OPENAI_TTS] Barge-in stopped playback")
                            break
                        if not stream.active:
                            break
                        time.sleep(0.01)
            finally:
                if stream:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass

            total_time = time.perf_counter() - start_time
            logger.info(f"[OPENAI_TTS] Total speak() time: {total_time*1000:.0f}ms")

        except Exception as e:
            logger.error(f"[OPENAI_TTS] Error: {e}", exc_info=True)
        finally:
            self._mark_playing(False, generation)

    def synthesize(self, text: str, generation: Optional[int] = None) -> Optional[bytes]:
        """Call TTS API and return raw PCM bytes (24 kHz, 16-bit, mono).

        Used for pre-fetching: synthesize the next sentence while the current
        one is still playing so there is zero gap between sentences.
        """
        if not text or not text.strip():
            return None
        if generation is None:
            generation = self.current_generation()
        if self.is_cancelled(generation):
            logger.info("[OPENAI_TTS] synthesize skipped after stop")
            return None
        from openai import OpenAI
        api_kwargs = dict(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="pcm",
            speed=self.speed,
        )
        if self._instructions and "gpt-4o" in self.model:
            api_kwargs["instructions"] = self._instructions
        start = time.perf_counter()
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        response = client.audio.speech.create(**api_kwargs)
        if self.is_cancelled(generation):
            logger.info("[OPENAI_TTS] synthesize cancelled before read")
            return None
        chunks = []
        for chunk in response.iter_bytes(chunk_size=4096):
            if self.is_cancelled(generation):
                logger.info("[OPENAI_TTS] synthesize cancelled during read")
                return None
            chunks.append(chunk)
        pcm_data = b"".join(chunks)
        if self.is_cancelled(generation):
            logger.info("[OPENAI_TTS] synthesize cancelled before return")
            return None
        logger.info(
            f"[OPENAI_TTS] synthesize({len(text)} chars): "
            f"{(time.perf_counter() - start)*1000:.0f}ms, {len(pcm_data)} bytes"
        )
        return pcm_data

    def play_pcm(self, pcm_data: bytes, generation: Optional[int] = None) -> None:
        """Play pre-fetched PCM data with barge-in support.

        Expects raw 24 kHz 16-bit mono PCM (the format returned by synthesize()).
        """
        if not pcm_data:
            return
        if generation is None:
            generation = self.current_generation()
        if self.is_cancelled(generation):
            logger.info("[OPENAI_TTS] play_pcm skipped after stop")
            return
        self._mark_playing(True, generation)
        start_time = time.perf_counter()
        stream = None
        try:
            import sounddevice as sd
            import numpy as np

            source_rate = 24000
            audio_f32 = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
            if self._device_sample_rate != source_rate:
                from scipy.signal import resample
                target_len = int(len(audio_f32) * self._device_sample_rate / source_rate)
                audio_f32 = resample(audio_f32, target_len).astype(np.float32)
            if self.is_cancelled(generation):
                logger.info("[OPENAI_TTS] play_pcm cancelled before playback")
                return

            stream = sd.OutputStream(
                samplerate=self._device_sample_rate,
                channels=1,
                dtype='float32',
                device=self._audio_device,
                blocksize=2048,
            )
            stream.start()
            playback_start = time.perf_counter()

            # Write in chunks so barge-in can interrupt mid-sentence
            CHUNK = 4800
            for i in range(0, len(audio_f32), CHUNK):
                if self.is_cancelled(generation):
                    logger.info("[OPENAI_TTS] Barge-in during play_pcm")
                    return
                stream.write(audio_f32[i:i + CHUNK].reshape(-1, 1))

            # Drain remaining buffered audio
            total_duration = len(audio_f32) / self._device_sample_rate
            elapsed = time.perf_counter() - playback_start
            remaining = max(0, total_duration - elapsed + 0.05)
            drain_start = time.perf_counter()
            while (time.perf_counter() - drain_start) < remaining:
                if self.is_cancelled(generation):
                    logger.info("[OPENAI_TTS] Barge-in stopped playback")
                    break
                if not stream.active:
                    break
                time.sleep(0.01)
            logger.info(f"[OPENAI_TTS] play_pcm: {(time.perf_counter() - start_time)*1000:.0f}ms")
        except Exception as e:
            logger.error(f"[OPENAI_TTS] play_pcm error: {e}", exc_info=True)
        finally:
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            self._mark_playing(False, generation)

    def stop(self) -> None:
        """Stop any active playback immediately."""
        with self._cancel_lock:
            self._stop_requested = True
            self._cancel_generation += 1
            self._is_playing = False
            generation = self._cancel_generation
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        logger.info(f"[OPENAI_TTS] Stop signal sent (generation={generation})")

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
