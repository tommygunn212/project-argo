import json

import pytest
import requests

import wrapper.ollama_generation as generation


class _Response:
    def __init__(self, *, payload=None, lines=None):
        self.payload = payload or {}
        self.lines = lines or []

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=False):
        assert decode_unicode is True
        return iter(self.lines)


def _install_online_argo(monkeypatch, lines):
    calls = []
    monkeypatch.setattr(generation.requests, "head", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(
        generation.requests,
        "get",
        lambda *args, **kwargs: _Response(payload={"models": [{"name": "argo:latest"}]}),
    )

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response(lines=lines)

    monkeypatch.setattr(generation.requests, "post", post)
    return calls


def test_streaming_returns_full_validated_response(monkeypatch, capsys):
    lines = [
        json.dumps({"response": "hello "}),
        "not-json",
        json.dumps({"response": "Tommy"}),
    ]
    calls = _install_online_argo(monkeypatch, lines)
    monkeypatch.setattr(
        generation,
        "validate_voice_compliance",
        lambda text: f"validated:{text}",
    )

    result = generation.generate_ollama_response("prompt".encode("utf-8"))

    assert result == "validated:hello Tommy"
    assert calls[0][1]["json"] == {
        "model": "argo",
        "prompt": "prompt",
        "stream": True,
    }
    assert capsys.readouterr().out == "hello Tommy\n"


def test_missing_argo_model_exits_before_generation(monkeypatch, capsys):
    monkeypatch.setattr(generation.requests, "head", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(
        generation.requests,
        "get",
        lambda *args, **kwargs: _Response(payload={"models": [{"name": "other:latest"}]}),
    )
    monkeypatch.setattr(
        generation.requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected post")),
    )

    with pytest.raises(SystemExit) as exc:
        generation.generate_ollama_response(b"prompt")

    assert exc.value.code == 1
    assert "Model 'argo' not found" in capsys.readouterr().err


def test_connection_failure_preserves_actionable_error(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(generation.requests, "head", fail)

    with pytest.raises(SystemExit) as exc:
        generation.generate_ollama_response(b"prompt")

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "Ollama server is not running" in error
    assert "ollama serve" in error


def test_terminal_cutoff_does_not_truncate_logged_response(monkeypatch, capsys):
    token = "x" * 1600
    _install_online_argo(
        monkeypatch,
        [json.dumps({"response": token}), json.dumps({"response": token})],
    )
    monkeypatch.setattr(generation, "validate_voice_compliance", lambda text: text)

    result = generation.generate_ollama_response(b"prompt")

    assert result == token * 2
    assert "Output paused to keep things readable" in capsys.readouterr().out
