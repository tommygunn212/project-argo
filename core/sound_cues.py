"""
Optional ARGO state-change sound cues.

Short WAV cues are played only from deterministic pipeline/state events and must
respect the central audio owner so they do not overlap STT, TTS, or music.
"""

from __future__ import annotations

import argparse
import array
import logging
import os
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.audio_owner import get_audio_owner
from core.instrumentation import log_event

logger = logging.getLogger(__name__)

SOUND_CUE_OWNER = "SOUND_CUE"
MAX_CUE_MS = 500

CUE_FILES = {
    "listening_start": "listening_start.wav",
    "listening_end": "listening_end.wav",
    "thinking_start": "thinking_start.wav",
    "speaking_start": "speaking_start.wav",
    "speaking_end": "speaking_end.wav",
    "error": "error.wav",
}

TEST_CUE_ORDER = (
    "listening_start",
    "listening_end",
    "thinking_start",
    "speaking_start",
    "speaking_end",
    "error",
)


class PlaybackHandle(Protocol):
    def wait_done(self) -> None: ...
    def stop(self) -> None: ...


class PlaybackBackend(Protocol):
    def play_buffer(
        self,
        audio_data: bytes,
        num_channels: int,
        bytes_per_sample: int,
        sample_rate: int,
    ) -> PlaybackHandle: ...


class SimpleAudioBackend:
    """Thin adapter for simpleaudio; imported lazily so cues remain optional."""

    def play_buffer(
        self,
        audio_data: bytes,
        num_channels: int,
        bytes_per_sample: int,
        sample_rate: int,
    ) -> PlaybackHandle:
        import simpleaudio

        return simpleaudio.play_buffer(
            audio_data,
            num_channels=num_channels,
            bytes_per_sample=bytes_per_sample,
            sample_rate=sample_rate,
        )


@dataclass(frozen=True)
class SoundCueConfig:
    enabled: bool = True
    volume: float = 0.35
    sounds_dir: Path = Path(__file__).resolve().parents[1] / "assets" / "sounds"
    max_duration_ms: int = MAX_CUE_MS
    allow_during_capture: bool = False
    respect_audio_owner: bool = True


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _config_get(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        value: Any = config
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            return getter(key) if key in config else default
    return default


def load_sound_cue_config(config: Any = None) -> SoundCueConfig:
    enabled_default = _config_get(config, "sound_cues_enabled", True)
    enabled = _config_get(config, "audio.sound_cues_enabled", enabled_default)
    env_enabled = os.getenv("ARGO_SOUND_CUES_ENABLED")
    if env_enabled is not None:
        enabled = env_enabled

    volume_default = _config_get(config, "sound_cues_volume", 0.35)
    volume = _config_get(config, "audio.sound_cues_volume", volume_default)
    env_volume = os.getenv("ARGO_SOUND_CUES_VOLUME")
    if env_volume is not None:
        volume = env_volume

    try:
        volume_float = max(0.0, min(1.0, float(volume)))
    except (TypeError, ValueError):
        volume_float = 0.35

    sounds_dir = _config_get(config, "audio.sound_cues_dir", None)
    sounds_path = Path(sounds_dir) if sounds_dir else SoundCueConfig.sounds_dir
    if not sounds_path.is_absolute():
        sounds_path = Path.cwd() / sounds_path

    return SoundCueConfig(
        enabled=_as_bool(enabled, True),
        volume=volume_float,
        sounds_dir=sounds_path,
        allow_during_capture=_as_bool(
            _config_get(config, "audio.sound_cues_allow_during_capture", False),
            False,
        ),
    )


class SoundCuePlayer:
    def __init__(
        self,
        config: SoundCueConfig | None = None,
        backend: PlaybackBackend | None = None,
    ):
        self.config = config or SoundCueConfig()
        self._backend = backend
        self._lock = threading.RLock()
        self._active_playback: PlaybackHandle | None = None
        self._active_cue: str | None = None
        self._capture_active = False
        self._cache: dict[tuple[str, float], tuple[bytes, int, int, int, float]] = {}

    def set_capture_active(self, active: bool) -> None:
        self._capture_active = bool(active)
        log_event(f"SOUND_CUE_CAPTURE_ACTIVE active={self._capture_active}", stage="sound_cue")
        if active:
            self.stop_active_cue("capture_started")

    def play(
        self,
        cue: str,
        *,
        interaction_id: str = "",
        block: bool = False,
        safe_during_capture: bool = False,
    ) -> bool:
        if cue not in CUE_FILES:
            log_event(f"SOUND_CUE_SKIP cue={cue} reason=unknown", stage="sound_cue", interaction_id=interaction_id)
            return False
        if not self.config.enabled:
            log_event(f"SOUND_CUE_SKIP cue={cue} reason=disabled", stage="sound_cue", interaction_id=interaction_id)
            return False
        if self.config.volume <= 0:
            log_event(f"SOUND_CUE_SKIP cue={cue} reason=muted", stage="sound_cue", interaction_id=interaction_id)
            return False
        if self._capture_active and not (safe_during_capture or self.config.allow_during_capture):
            log_event(
                f"SOUND_CUE_SKIP cue={cue} reason=capture_active",
                stage="sound_cue",
                interaction_id=interaction_id,
            )
            return False

        loaded = self._load_cue(cue, interaction_id=interaction_id)
        if loaded is None:
            return False
        audio_data, channels, sample_width, sample_rate, duration_ms = loaded

        with self._lock:
            active_cue = self._active_cue
        if active_cue:
            self.stop_active_cue(f"replace_with_{cue}", interaction_id=interaction_id)

        owner = get_audio_owner()
        acquired = False
        if self.config.respect_audio_owner:
            current_owner = owner.get_owner()
            if current_owner and current_owner != SOUND_CUE_OWNER:
                log_event(
                    f"SOUND_CUE_SKIP cue={cue} reason=audio_owned_by_{current_owner}",
                    stage="sound_cue",
                    interaction_id=interaction_id,
                )
                return False
            try:
                owner.acquire(SOUND_CUE_OWNER)
                acquired = True
                log_event(
                    f"SOUND_CUE_AUDIO_ACQUIRED cue={cue}",
                    stage="sound_cue",
                    interaction_id=interaction_id,
                )
            except Exception as exc:
                log_event(
                    f"SOUND_CUE_SKIP cue={cue} reason=audio_contested error={type(exc).__name__}",
                    stage="sound_cue",
                    interaction_id=interaction_id,
                )
                return False

        try:
            playback = self._get_backend().play_buffer(audio_data, channels, sample_width, sample_rate)
        except Exception as exc:
            if acquired:
                owner.release(SOUND_CUE_OWNER)
            log_event(
                f"SOUND_CUE_SKIP cue={cue} reason=playback_error error={type(exc).__name__}",
                stage="sound_cue",
                interaction_id=interaction_id,
            )
            logger.debug("Sound cue playback failed", exc_info=True)
            return False

        with self._lock:
            self._active_playback = playback
            self._active_cue = cue

        log_event(
            f"SOUND_CUE_PLAY cue={cue} duration_ms={duration_ms:.0f} volume={self.config.volume:.2f}",
            stage="sound_cue",
            interaction_id=interaction_id,
        )

        if block:
            self._wait_and_release(playback, cue, interaction_id, acquired)
        else:
            thread = threading.Thread(
                target=self._wait_and_release,
                args=(playback, cue, interaction_id, acquired),
                name=f"sound-cue-{cue}",
                daemon=True,
            )
            thread.start()
        return True

    def stop_active_cue(self, reason: str = "interrupt", interaction_id: str = "") -> None:
        with self._lock:
            playback = self._active_playback
            cue = self._active_cue
            self._active_playback = None
            self._active_cue = None
        if playback is not None:
            try:
                playback.stop()
            except Exception:
                pass
            get_audio_owner().release(SOUND_CUE_OWNER)
            log_event(
                f"SOUND_CUE_STOP cue={cue or 'unknown'} reason={reason}",
                stage="sound_cue",
                interaction_id=interaction_id,
            )

    def _wait_and_release(
        self,
        playback: PlaybackHandle,
        cue: str,
        interaction_id: str,
        acquired: bool,
    ) -> None:
        try:
            playback.wait_done()
        except Exception:
            logger.debug("Sound cue wait failed", exc_info=True)
        finally:
            with self._lock:
                if self._active_playback is playback:
                    self._active_playback = None
                    self._active_cue = None
            if acquired:
                get_audio_owner().release(SOUND_CUE_OWNER)
                log_event(
                    f"SOUND_CUE_AUDIO_RELEASED cue={cue}",
                    stage="sound_cue",
                    interaction_id=interaction_id,
                )
            log_event(f"SOUND_CUE_DONE cue={cue}", stage="sound_cue", interaction_id=interaction_id)

    def _get_backend(self) -> PlaybackBackend:
        if self._backend is None:
            self._backend = SimpleAudioBackend()
        return self._backend

    def _load_cue(
        self,
        cue: str,
        *,
        interaction_id: str = "",
    ) -> tuple[bytes, int, int, int, float] | None:
        cache_key = (cue, self.config.volume)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        path = self.config.sounds_dir / CUE_FILES[cue]
        if not path.exists():
            log_event(
                f"SOUND_CUE_SKIP cue={cue} reason=missing_file path={path}",
                stage="sound_cue",
                interaction_id=interaction_id,
            )
            return None

        try:
            with wave.open(str(path), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()
                frame_count = wav.getnframes()
                duration_ms = (frame_count / float(sample_rate)) * 1000 if sample_rate else 0.0
                if duration_ms > self.config.max_duration_ms:
                    log_event(
                        f"SOUND_CUE_SKIP cue={cue} reason=too_long duration_ms={duration_ms:.0f}",
                        stage="sound_cue",
                        interaction_id=interaction_id,
                    )
                    return None
                frames = wav.readframes(frame_count)
        except Exception as exc:
            log_event(
                f"SOUND_CUE_SKIP cue={cue} reason=wav_error error={type(exc).__name__}",
                stage="sound_cue",
                interaction_id=interaction_id,
            )
            return None

        if sample_width == 2 and self.config.volume != 1.0:
            frames = _scale_int16_pcm(frames, self.config.volume)

        loaded = (frames, channels, sample_width, sample_rate, duration_ms)
        self._cache[cache_key] = loaded
        return loaded


_sound_cue_player: SoundCuePlayer | None = None
_sound_cue_lock = threading.Lock()


def get_sound_cue_player(config: Any = None) -> SoundCuePlayer:
    global _sound_cue_player
    if _sound_cue_player is None:
        with _sound_cue_lock:
            if _sound_cue_player is None:
                _sound_cue_player = SoundCuePlayer(load_sound_cue_config(config))
    return _sound_cue_player


def _scale_int16_pcm(frames: bytes, volume: float) -> bytes:
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()
    for idx, sample in enumerate(samples):
        samples[idx] = max(-32768, min(32767, int(sample * volume)))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def reset_sound_cue_player() -> None:
    global _sound_cue_player
    with _sound_cue_lock:
        if _sound_cue_player is not None:
            _sound_cue_player.stop_active_cue("reset")
        _sound_cue_player = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Play ARGO sound cues once.")
    parser.add_argument("--test", action="store_true", help="play every cue once in deterministic order")
    args = parser.parse_args()
    if not args.test:
        parser.print_help()
        return 0

    try:
        from core.config import get_config

        base_config = load_sound_cue_config(get_config())
    except Exception:
        base_config = SoundCueConfig()
    player = SoundCuePlayer(
        SoundCueConfig(
            enabled=True,
            volume=base_config.volume,
            sounds_dir=base_config.sounds_dir,
            max_duration_ms=base_config.max_duration_ms,
            allow_during_capture=True,
            respect_audio_owner=False,
        )
    )
    for cue in TEST_CUE_ORDER:
        print(f"Playing {cue}")
        player.play(cue, block=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
