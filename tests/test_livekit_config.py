from core.livekit_config import (
    DEFAULT_LOCAL_LIVEKIT_SECRET,
    build_livekit_token_response,
    get_livekit_realtime_config,
    livekit_status,
    mobile_access_status,
    speaker_identity_status,
)


class FakeConfig:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        value = self.data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


def test_dev_secret_is_used_for_local_dev_key(monkeypatch):
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)

    cfg = get_livekit_realtime_config(
        FakeConfig({"livekit": {"api_key": "devkey", "api_secret": ""}})
    )

    assert cfg.api_key == "devkey"
    assert cfg.api_secret == DEFAULT_LOCAL_LIVEKIT_SECRET


def test_livekit_token_response_sanitizes_room_and_identity(monkeypatch):
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)

    cfg = FakeConfig(
        {
            "livekit": {
                "enabled": True,
                "url": "ws://127.0.0.1:7880",
                "api_key": "devkey",
                "api_secret": "",
                "room": "argo-live",
                "model": "gpt-realtime",
                "voice": "marin",
                "token_ttl_minutes": 30,
            }
        }
    )

    payload = build_livekit_token_response(
        identity="Tommy Gunn!",
        room="argo live!",
        config=cfg,
    )

    assert payload["url"] == "ws://127.0.0.1:7880"
    assert payload["room"] == "argo-live-"
    assert payload["identity"] == "Tommy-Gunn-"
    assert payload["token"]
    assert "api_secret" not in payload


def test_livekit_status_is_safe_without_server():
    payload = livekit_status(
        FakeConfig(
            {
                "livekit": {
                    "enabled": True,
                    "url": "ws://127.0.0.1:1",
                    "room": "argo-live",
                    "model": "gpt-realtime",
                    "voice": "marin",
                }
            }
        )
    )

    assert payload["mode"] == "livekit_realtime"
    assert payload["server_reachable"] is False
    assert payload["speaker_identity"]["provider"] == "speechmatics"
    assert payload["avatar"]["legacy_hedra_enabled"] is False


def test_realtime_defaults_are_tuned_for_fast_turn_taking(monkeypatch):
    monkeypatch.delenv("ARGO_REALTIME_MIN_INTERRUPTION_DURATION", raising=False)
    monkeypatch.delenv("ARGO_REALTIME_FALSE_INTERRUPTION_TIMEOUT", raising=False)

    cfg = get_livekit_realtime_config(FakeConfig({"livekit": {}}))

    assert cfg.min_interruption_duration == 0.08
    assert cfg.false_interruption_timeout == 0.22
    assert "fast back-and-forth" in cfg.instructions


def test_mobile_access_status_uses_request_host(monkeypatch):
    monkeypatch.setenv("ARGO_HTTP_PORT", "8000")
    monkeypatch.setenv("ARGO_WS_PORT", "8001")

    payload = mobile_access_status("192.168.1.44:8000")

    assert payload["http_url"] == "http://192.168.1.44:8000/v2"
    assert payload["ws_url"] == "ws://192.168.1.44:8001/ws"


def test_speaker_identity_status_requires_key_and_plugin(monkeypatch):
    monkeypatch.setenv("ARGO_SPEAKER_ID_ENABLED", "true")
    monkeypatch.setenv("SPEECHMATICS_API_KEY", "test-key")

    payload = speaker_identity_status()

    assert payload["enabled"] is True
    assert payload["api_key_ready"] is True
    assert payload["plugin_ready"] is True
    assert payload["ready"] is True
