"""One voice path owns the microphone, and it does not let go by accident.

The log showed UI_CMD_START_VAD firing the moment LiveKit reported
"disconnected". Both paths then held the mic: the classic listener recorded
ARGO's own speakers, barge-in tripped 8 times on ARGO's own voice, and
Whisper hallucinated Arabic and Korean out of the tail.

The rule being pinned here: while Smooth Voice is selected, the classic
listener stays stopped through a disconnect, a dead worker, a reconnect and
multiple tabs. Only an explicit switch releases it.
"""

import json

import pytest

import main


@pytest.fixture(autouse=True)
def isolated_mode(tmp_path, monkeypatch):
    """Keep the real runtime/voice_mode.json out of the tests."""
    monkeypatch.setattr(main, "VOICE_MODE_FILE", tmp_path / "voice_mode.json")
    monkeypatch.setattr(main, "VOICE_MODE", main.VOICE_MODE_CLASSIC)
    monkeypatch.setattr(main, "LISTENING_ENABLED", False)
    monkeypatch.setattr(main, "audio_ref", None)
    monkeypatch.setattr(main, "broadcast_msg", lambda *a, **k: None)
    yield


def _control(cmd):
    main._handle_control(cmd)


# --- claiming -------------------------------------------------------------

def test_a_smooth_voice_phase_claims_the_microphone():
    main._note_smooth_voice_phase("live")
    assert main.VOICE_MODE == main.VOICE_MODE_SMOOTH


def test_claiming_stops_a_classic_listener_that_was_already_running(monkeypatch):
    stopped = []

    class Audio:
        def stop(self):
            stopped.append(True)

    monkeypatch.setattr(main, "audio_ref", Audio())
    monkeypatch.setattr(main, "LISTENING_ENABLED", True)

    main._note_smooth_voice_phase("mic_acquired")

    assert main.LISTENING_ENABLED is False
    assert stopped, "the classic input stream must actually be stopped"


@pytest.mark.parametrize("phase", ["live", "mic_acquired", "livekit_client_ready",
                                   "connecting", "remote_audio_subscribed"])
def test_every_phase_that_holds_a_mic_claims_it(phase):
    main._note_smooth_voice_phase(phase)
    assert main.VOICE_MODE == main.VOICE_MODE_SMOOTH


# --- the failures that must NOT release it --------------------------------

@pytest.mark.parametrize("phase", [
    "disconnected",   # network drop, or the worker dying
    "error",
    "start_failed",
    "closed",
    "stopped",
])
def test_no_browser_phase_ever_releases_the_microphone(phase):
    """This is the regression. The browser auto-resumed classic on exactly
    these, which is how two microphones ended up open at once."""
    main._note_smooth_voice_phase("live")
    main._note_smooth_voice_phase(phase)
    assert main.VOICE_MODE == main.VOICE_MODE_SMOOTH


def test_resume_is_refused_while_smooth_owns_the_microphone():
    main._note_smooth_voice_phase("live")
    _control("RESUME")
    assert main.LISTENING_ENABLED is False, "classic STT must not start"


def test_resume_is_refused_even_with_livekit_completely_down():
    """Ownership is a mode, not a liveness check: a dead worker and an empty
    room change nothing."""
    main._note_smooth_voice_phase("live")
    main._note_smooth_voice_phase("disconnected")
    _control("RESUME")
    assert main.LISTENING_ENABLED is False


def test_a_reconnect_does_not_open_a_second_microphone():
    main._note_smooth_voice_phase("live")
    main._note_smooth_voice_phase("disconnected")
    main._note_smooth_voice_phase("connecting")
    main._note_smooth_voice_phase("live")
    _control("RESUME")
    assert main.LISTENING_ENABLED is False
    assert main.VOICE_MODE == main.VOICE_MODE_SMOOTH


def test_a_second_tab_cannot_take_the_microphone():
    """Two tabs both reporting phases is still one owner."""
    main._note_smooth_voice_phase("live")          # tab A
    main._note_smooth_voice_phase("disconnected")  # tab A loses the lock
    main._note_smooth_voice_phase("live")          # tab B takes over
    _control("RESUME")
    assert main.LISTENING_ENABLED is False


# --- releasing it ---------------------------------------------------------

def test_only_the_explicit_switch_gives_the_microphone_back():
    main._note_smooth_voice_phase("live")
    _control("USE_CLASSIC_VOICE")
    assert main.VOICE_MODE == main.VOICE_MODE_CLASSIC
    assert main.LISTENING_ENABLED is True


def test_classic_resume_still_works_when_classic_owns_the_mic():
    _control("RESUME")
    assert main.LISTENING_ENABLED is True


# --- persistence ----------------------------------------------------------

def test_the_mode_survives_a_server_restart():
    """A restart must not quietly hand the microphone back."""
    main._note_smooth_voice_phase("live")
    main.VOICE_MODE = main.VOICE_MODE_CLASSIC  # simulate a fresh process
    main._restore_voice_mode()
    assert main.VOICE_MODE == main.VOICE_MODE_SMOOTH


def test_a_damaged_mode_file_falls_back_to_classic(tmp_path, monkeypatch):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(main, "VOICE_MODE_FILE", bad)
    assert main._load_voice_mode() == main.VOICE_MODE_CLASSIC


def test_a_missing_mode_file_means_classic(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "VOICE_MODE_FILE", tmp_path / "absent.json")
    assert main._load_voice_mode() == main.VOICE_MODE_CLASSIC


def test_the_persisted_file_says_what_it_means(tmp_path):
    main._note_smooth_voice_phase("live")
    written = json.loads(main.VOICE_MODE_FILE.read_text(encoding="utf-8"))
    assert written == {"mode": "smooth"}
