from core.livekit_config import (
    DEFAULT_LOCAL_LIVEKIT_SECRET,
    build_livekit_token_response,
    get_livekit_realtime_config,
    livekit_status,
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
