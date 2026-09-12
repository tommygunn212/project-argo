import wave
import threading
from pathlib import Path

from core.audio_owner import get_audio_owner
from core.sound_cues import (
    CUE_FILES,
    SoundCueConfig,
    SoundCuePlayer,
    load_sound_cue_config,
)


class FakePlayback:
    def __init__(self, block_wait=False):
        self.stopped = False
        self.waited = False
        self._block_wait = block_wait
        self._released = threading.Event()

    def wait_done(self):
        self.waited = True
        if self._block_wait:
            self._released.wait(timeout=1.0)

    def stop(self):
        self.stopped = True
        self._released.set()


class FakeBackend:
    def __init__(self, block_wait=False):
        self.calls = []
        self.handles = []
        self._block_wait = block_wait

    def play_buffer(self, audio_data, num_channels, bytes_per_sample, sample_rate):
        self.calls.append((audio_data, num_channels, bytes_per_sample, sample_rate))
        handle = FakePlayback(block_wait=self._block_wait)
        self.handles.append(handle)
        return handle


def release_sound_cue_owner():
    get_audio_owner().release("SOUND_CUE")


def test_config_reads_audio_flags():
    config = {
        "audio": {
            "sound_cues_enabled": False,
            "sound_cues_volume": 0.2,
            "sound_cues_allow_during_capture": False,
        }
    }

    loaded = load_sound_cue_config(config)

    assert loaded.enabled is False
    assert loaded.volume == 0.2
    assert loaded.allow_during_capture is False


def test_disabled_cues_do_not_play():
    backend = FakeBackend(block_wait=True)
    player = SoundCuePlayer(SoundCueConfig(enabled=False), backend=backend)

    assert player.play("listening_start") is False
    assert backend.calls == []


def test_missing_sound_file_does_not_crash(tmp_path):
    backend = FakeBackend(block_wait=True)
    player = SoundCuePlayer(SoundCueConfig(sounds_dir=tmp_path), backend=backend)

    assert player.play("listening_start") is False
    assert backend.calls == []


def test_capture_active_blocks_cue():
    backend = FakeBackend(block_wait=True)
    player = SoundCuePlayer(SoundCueConfig(), backend=backend)

    player.set_capture_active(True)

    assert player.play("listening_start") is False
    assert backend.calls == []


def test_audio_owner_blocks_overlap():
    backend = FakeBackend()
    player = SoundCuePlayer(SoundCueConfig(), backend=backend)
    owner = get_audio_owner()
    owner.acquire("TTS")
    try:
        assert player.play("listening_start") is False
    finally:
        owner.release("TTS")

    assert backend.calls == []


def test_blocking_play_releases_owner():
    backend = FakeBackend()
    player = SoundCuePlayer(SoundCueConfig(), backend=backend)

    assert player.play("speaking_start", block=True) is True

    assert backend.calls
    assert backend.handles[-1].waited is True
    assert get_audio_owner().get_owner() is None


def test_stop_active_cue_releases_owner(tmp_path):
    cue_path = tmp_path / CUE_FILES["thinking_start"]
    source_path = Path("assets/sounds") / CUE_FILES["thinking_start"]
    cue_path.write_bytes(source_path.read_bytes())
    backend = FakeBackend(block_wait=True)
    player = SoundCuePlayer(SoundCueConfig(sounds_dir=tmp_path), backend=backend)

    assert player.play("thinking_start", block=False) is True
    player.stop_active_cue("barge_in")

    assert backend.handles[-1].stopped is True
    assert get_audio_owner().get_owner() is None


def test_all_sound_assets_are_under_500_ms():
    for filename in CUE_FILES.values():
        path = Path("assets/sounds") / filename
        assert path.exists(), filename
        with wave.open(str(path), "rb") as wav:
            duration_ms = wav.getnframes() / wav.getframerate() * 1000
        assert duration_ms < 500, filename
