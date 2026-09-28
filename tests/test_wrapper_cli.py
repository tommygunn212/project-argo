from types import SimpleNamespace

import pytest

from wrapper.cli import parse_cli_args, run_cli


def test_parse_cli_args_preserves_ordered_flag_contract():
    options = parse_cli_args([
        "--session", "night", "--mode", "brainstorm", "--persona", "rick",
        "--strict", "off", "--replay", "last:3", "--no-voice", "hello", "there",
    ])

    assert options.session_name == "night"
    assert options.mode == "brainstorm"
    assert options.persona == "rick"
    assert options.strict_mode is False
    assert options.replay_n == 3
    assert options.replay_session is False
    assert options.voice_enabled is False
    assert options.message == "hello there"


@pytest.mark.parametrize("value", ["last:nope", "everything"])
def test_invalid_replay_is_rejected(value):
    with pytest.raises(ValueError, match="last:N or session"):
        parse_cli_args(["--replay", value, "hello"])


def test_single_shot_uses_loaded_runtime_without_reimport(monkeypatch):
    calls = []
    runtime = SimpleNamespace(
        SESSION_ID="old",
        resolve_session_id=lambda name: f"resolved:{name}",
        run_argo=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    monkeypatch.delenv("PIPER_ENABLED", raising=False)

    result = run_cli(runtime, ["--session", "work", "--voice", "hello"])

    assert result == 0
    assert runtime.SESSION_ID == "resolved:work"
    assert calls == [(('hello',), {
        "active_mode": None,
        "replay_n": None,
        "replay_session": False,
        "strict_mode": True,
        "persona": "neutral",
    })]
    assert __import__("os").environ["VOICE_ENABLED"] == "true"
    assert __import__("os").environ["PIPER_ENABLED"] == "true"


def test_declined_transcription_returns_failure_without_running_model():
    runtime = SimpleNamespace(
        SESSION_ID="old",
        transcribe_and_confirm=lambda _path: (False, "ignored", object()),
        run_argo=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model should not run")
        ),
    )

    assert run_cli(runtime, ["--transcribe", "clip.wav"]) == 1
