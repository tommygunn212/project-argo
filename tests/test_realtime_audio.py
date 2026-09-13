"""Noise cancellation on the realtime mic track.

livekit-plugins-noise-cancellation was installed and never referenced, so
every realtime session ran on raw mic audio while the plugin sat on disk.
It is wired now - and wired so that a broken plugin degrades to raw audio
instead of taking voice down with it.
"""

import pytest

# No os.environ.setdefault("LIVEKIT_URL", ...) here. Importing the agent no
# longer builds a server, so nothing needs it - and setting it leaks into the
# whole pytest process and breaks test_livekit_config's URL defaults.
from core.livekit_config import get_livekit_realtime_config
import livekit_realtime_agent as agent_mod


def test_noise_cancellation_is_off_by_default():
    """BVC is a LiveKit Cloud filter and this server is self-hosted. It was
    on by default for one afternoon and was a credible suspect when Smooth
    Voice connected and then heard nothing."""
    assert get_livekit_realtime_config().noise_cancellation is False


def test_no_filter_is_built_when_disabled():
    assert agent_mod._build_noise_filter(get_livekit_realtime_config()) is None


def test_the_filter_still_builds_when_explicitly_enabled():
    """Off by default, not removed - this runs against Cloud one day."""
    cfg = get_livekit_realtime_config()
    on = type(cfg)(**{**cfg.__dict__, "noise_cancellation": True})
    assert agent_mod._build_noise_filter(on) is not None




def test_a_broken_plugin_degrades_to_raw_audio(monkeypatch):
    """A broken native dependency must not stop the session starting."""
    from livekit.plugins import noise_cancellation

    def boom():
        raise RuntimeError("pretend the native library is missing")

    monkeypatch.setattr(noise_cancellation, "BVC", boom)
    cfg = get_livekit_realtime_config()
    on = type(cfg)(**{**cfg.__dict__, "noise_cancellation": True})
    assert agent_mod._build_noise_filter(on) is None


def test_room_input_options_accept_the_filter():
    """The kwarg has to exist on the installed SDK, not just in our code."""
    import inspect

    from livekit.agents import room_io

    assert "noise_cancellation" in inspect.signature(room_io.RoomInputOptions).parameters
