import pytest

import core.classic_runtime_startup as startup


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)


class _Audio:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


class _Pipeline:
    def __init__(self):
        self.llm_enabled = None
        self.warmed = False

    def set_llm_enabled(self, enabled):
        self.llm_enabled = enabled

    def warmup(self):
        self.warmed = True


def _install_database(monkeypatch, exists=True):
    monkeypatch.setattr(startup, "music_db_exists", lambda path: exists)
    monkeypatch.setattr(
        startup,
        "get_db_status",
        lambda path: {"ready": exists, "path": str(path)},
    )


def test_ollama_runtime_starts_audio_broadcasts_db_and_warms_pipeline(monkeypatch):
    audio = _Audio()
    pipeline = _Pipeline()
    logger = _Logger()
    broadcasts = []
    monkeypatch.setattr(startup, "check_ollama", lambda: True)
    _install_database(monkeypatch)

    available = startup.start_classic_runtime(
        audio,
        pipeline,
        {"llm": {"backend": "ollama"}},
        lambda kind, payload: broadcasts.append((kind, payload)),
        logger,
        environment={},
    )

    assert available is True
    assert audio.started is True
    assert pipeline.llm_enabled is True
    assert pipeline.warmed is True
    assert broadcasts[0][0] == "db_status"
    assert "Ollama online" in logger.messages


def test_optional_offline_ollama_enters_no_brain_mode(monkeypatch):
    audio = _Audio()
    pipeline = _Pipeline()
    logger = _Logger()
    monkeypatch.setattr(startup, "check_ollama", lambda: False)
    _install_database(monkeypatch, exists=False)

    available = startup.start_classic_runtime(
        audio,
        pipeline,
        {"llm": {"backend": "ollama"}, "llm.required": False},
        lambda *_args: None,
        logger,
        environment={},
    )

    assert available is False
    assert pipeline.llm_enabled is False
    assert pipeline.warmed is True
    assert "LLM offline: running in no-brain mode" in logger.messages


def test_required_offline_ollama_fails_before_pipeline_warmup(monkeypatch):
    audio = _Audio()
    pipeline = _Pipeline()
    monkeypatch.setattr(startup, "check_ollama", lambda: False)

    with pytest.raises(RuntimeError, match="Ollama is not running"):
        startup.start_classic_runtime(
            audio,
            pipeline,
            {"llm": {"backend": "ollama"}, "llm.required": True},
            lambda *_args: None,
            _Logger(),
            environment={},
        )

    assert audio.started is True
    assert pipeline.warmed is False


def test_openai_backend_uses_key_without_probing_ollama(monkeypatch):
    audio = _Audio()
    pipeline = _Pipeline()
    logger = _Logger()
    monkeypatch.setattr(
        startup,
        "check_ollama",
        lambda: (_ for _ in ()).throw(AssertionError("Ollama should not be probed")),
    )
    _install_database(monkeypatch)

    available = startup.start_classic_runtime(
        audio,
        pipeline,
        {"llm": {"backend": "openai"}, "llm.required": True},
        lambda *_args: None,
        logger,
        environment={"OPENAI_API_KEY": "present"},
    )

    assert available is True
    assert pipeline.llm_enabled is True
    assert "OpenAI LLM configured" in logger.messages
