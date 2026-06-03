import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_write_text_to_app_rejects_unsupported_app():
    from core.app_control import write_text_to_app

    ok, msg = write_text_to_app("microsoft edge", "hello")
    assert ok is False
    assert "Notepad or Word" in msg


def test_write_text_to_app_launches_and_pastes(monkeypatch):
    import core.app_control as ac

    monkeypatch.setattr(ac, "is_app_running", lambda app_key: False)
    monkeypatch.setattr(ac, "open_app", lambda app_key: (True, f"Opening {app_key}."))
    monkeypatch.setattr(ac, "focus_app_deterministic", lambda app_key: (True, f"{app_key} focused.", "focused"))
    monkeypatch.setattr(ac.time, "sleep", lambda *_args, **_kwargs: None)

    class Result:
        stdout = "true"

    seen = {}

    def _fake_run(cmd, capture_output, text, timeout):
        seen["cmd"] = cmd
        return Result()

    monkeypatch.setattr(ac.subprocess, "run", _fake_run)

    ok, msg = ac.write_text_to_app("notepad", "Hello from ARGO")
    assert ok is True
    assert "Notepad" in msg
    assert seen["cmd"][0] == "powershell"


def test_app_status_response_uses_display_name(monkeypatch):
    import core.app_control as ac

    monkeypatch.setattr(ac, "is_app_running", lambda app_key: True)

    message = ac.app_status_response("is edge running")

    assert message == "Microsoft Edge is running."
