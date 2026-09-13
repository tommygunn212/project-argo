"""Noise cancellation on the realtime mic track.

livekit-plugins-noise-cancellation was installed and never referenced, so
every realtime session ran on raw mic audio while the plugin sat on disk.
It is wired now - and wired so that a broken plugin degrades to raw audio
instead of taking voice down with it.
"""

import os

import pytest

os.environ.setdefault("LIVEKIT_URL", "ws://localhost:7880")

from core.livekit_config import get_livekit_realtime_config  # noqa: E402
import livekit_realtime_agent as agent_mod  # noqa: E402


def test_noise_cancellation_is_on_by_default():
    assert get_livekit_realtime_config().noise_cancellation is True


def test_filter_is_built_when_enabled():
    cfg = get_livekit_realtime_config()
    assert agent_mod._build_noise_filter(cfg) is not None


def test_config_can_turn_it_off():
    cfg = get_livekit_realtime_config()
    off = type(cfg)(**{**cfg.__dict__, "noise_cancellation": False})
    assert agent_mod._build_noise_filter(off) is None


def test_a_broken_plugin_degrades_to_raw_audio(monkeypatch):
    """A broken native dependency must not stop the session starting."""
    from livekit.plugins import noise_cancellation

    def boom():
        raise RuntimeError("pretend the native library is missing")

    monkeypatch.setattr(noise_cancellation, "BVC", boom)
    assert agent_mod._build_noise_filter(get_livekit_realtime_config()) is None


def test_room_input_options_accept_the_filter():
    """The kwarg has to exist on the installed SDK, not just in our code."""
    import inspect

    from livekit.agents import room_io

    assert "noise_cancellation" in inspect.signature(room_io.RoomInputOptions).parameters
