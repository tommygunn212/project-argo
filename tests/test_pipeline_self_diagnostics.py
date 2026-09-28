from types import SimpleNamespace

import core.pipeline_self_diagnostics as stage


class _Logger:
    def __init__(self):
        self.errors = []

    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        self.errors.append(args)


class _Pipeline:
    def __init__(self):
        self.logger = _Logger()
        self.broadcasts = []
        self.deliveries = []

    def broadcast(self, event, payload):
        self.broadcasts.append((event, payload))

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True


def _install_diagnostics(monkeypatch, summary, last_check=None):
    class _Diagnostics:
        def __init__(self):
            self.last_check = last_check or {}

        def check_all(self):
            pass

        def get_summary(self):
            return summary

    monkeypatch.setattr(stage, "SystemDiagnostics", _Diagnostics)


def _respond(pipeline):
    return stage.respond_with_self_diagnostics(
        pipeline, "interaction-1", False, {"voice": "test"}
    )


def test_healthy_diagnostics_are_broadcast_and_spoken(monkeypatch):
    pipeline = _Pipeline()
    summary = {"overall": "ok", "ok_count": 8, "summary": "healthy"}
    _install_diagnostics(monkeypatch, summary)

    assert _respond(pipeline) is True
    assert pipeline.broadcasts == [("diagnostics_result", summary)]
    message, _, options = pipeline.deliveries[0]
    assert message == "All systems operational. 8 components checked, all healthy."
    assert options["enforce_confidence"] is False
    assert options["force_tts"] is True


def test_warning_names_are_limited_for_speech(monkeypatch):
    pipeline = _Pipeline()
    summary = {
        "overall": "warning",
        "warnings": [{"name": name} for name in ["audio", "stt", "tts", "llm"]],
    }
    _install_diagnostics(monkeypatch, summary)

    assert _respond(pipeline) is True
    assert pipeline.deliveries[0][0] == "Systems mostly okay. Warnings on: audio, stt, tts."


def test_error_uses_shared_recovery_manager(monkeypatch):
    pipeline = _Pipeline()
    proposals = []
    pipeline.recovery_manager = SimpleNamespace(
        propose=lambda action, message: proposals.append((action, message)) or True
    )
    component = SimpleNamespace(
        status=SimpleNamespace(value="error"),
        recovery_action="restart_audio",
        message="audio is offline",
    )
    summary = {
        "overall": "error",
        "errors": [{"name": "audio", "message": "is offline", "fix": "restart it"}],
    }
    _install_diagnostics(monkeypatch, summary, {"audio": component})

    assert _respond(pipeline) is True
    assert proposals == [("restart_audio", "audio is offline")]
    assert pipeline.deliveries[0][0] == (
        "Problem detected: audio is offline. Suggested fix: restart it. "
        "Want me to try restarting audio?"
    )


def test_diagnostics_failure_degrades_to_spoken_error(monkeypatch):
    pipeline = _Pipeline()

    class _BrokenDiagnostics:
        def __init__(self):
            raise RuntimeError("probe failed")

    monkeypatch.setattr(stage, "SystemDiagnostics", _BrokenDiagnostics)

    assert _respond(pipeline) is True
    assert pipeline.deliveries[0][0] == "I tried to check myself but something went wrong."
    assert pipeline.logger.errors
