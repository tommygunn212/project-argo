from core.livekit_config import (
    DEFAULT_LOCAL_LIVEKIT_SECRET,
    build_livekit_token_response,
    get_livekit_realtime_config,
    hedra_avatar_status,
    livekit_status,
    local_avatar_media_status,
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
    assert payload["avatar"]["provider"] == "hedra_live_avatar"
    assert "api_key" not in payload["avatar"]


def test_realtime_defaults_are_tuned_for_fast_turn_taking(monkeypatch):
    monkeypatch.delenv("ARGO_REALTIME_MIN_INTERRUPTION_DURATION", raising=False)
    monkeypatch.delenv("ARGO_REALTIME_FALSE_INTERRUPTION_TIMEOUT", raising=False)

    cfg = get_livekit_realtime_config(FakeConfig({"livekit": {}}))

    # These used to be 0.08s / 0.22s - hair-trigger. That is what made ARGO
    # cut in on a cough, on the AC, and on her own speaker bleeding back into
    # the Brio. Generic speech now has to be sustained; a decisive "stop" gets
    # a separate fast path instead (see urgent_interrupt_phrases), so nothing
    # urgent pays for this.
    assert cfg.min_interruption_duration >= 0.3
    assert cfg.false_interruption_timeout >= 1.0
    assert cfg.min_interruption_words >= 2
    assert "stop" in cfg.urgent_interrupt_phrases

    # Reply LENGTH stays uncapped: the instructions used to say "answer in one
    # short sentence by default", which is what made ARGO sound clipped next
    # to ChatGPT voice mode.
    assert "one short sentence" not in cfg.instructions
    lowered = cfg.instructions.lower()
    assert "a casual thought gets a real but short reply" in lowered
    assert "not a cut-off" in lowered


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


def test_retired_hedra_is_not_ready_even_with_key_plugin_and_image(monkeypatch, tmp_path):
    image = tmp_path / "avatar.png"
    image.write_bytes(b"fake")
    monkeypatch.setenv("ARGO_HEDRA_AVATAR_ENABLED", "true")
    monkeypatch.setenv("HEDRA_API_KEY", "test-secret")
    monkeypatch.setenv("HEDRA_AVATAR_IMAGE", str(image))
    monkeypatch.delenv("HEDRA_AVATAR_ID", raising=False)

    payload = hedra_avatar_status()

    assert payload["enabled"] is True
    assert payload["api_key_ready"] is True
    assert payload["image_ready"] is True
    assert payload["ready"] is False
    assert payload["service_retired"] is True
    assert "retired" in payload["error"]
    assert "test-secret" not in str(payload)


def test_local_avatar_media_status_reports_ready_file(monkeypatch, tmp_path):
    media = tmp_path / "avatar.gif"
    media.write_bytes(b"GIF89a")
    monkeypatch.delenv("ARGO_LOCAL_AVATAR_MEDIA", raising=False)
    monkeypatch.delenv("ARGO_LOCAL_AVATAR_MEDIA_ENABLED", raising=False)

    payload = local_avatar_media_status(
        FakeConfig({"avatar": {"local_media_enabled": True, "local_media_path": str(media)}})
    )

    assert payload["enabled"] is True
    assert payload["ready"] is True
    assert payload["url"] == "/v2-assets/local-avatar-media"
    assert payload["content_type"] == "image/gif"
    assert payload["media_type"] == "image"


def test_local_avatar_media_status_does_not_claim_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "missing.gif"
    monkeypatch.delenv("ARGO_LOCAL_AVATAR_MEDIA", raising=False)
    monkeypatch.delenv("ARGO_LOCAL_AVATAR_MEDIA_ENABLED", raising=False)

    payload = local_avatar_media_status(
        FakeConfig({"avatar": {"local_media_enabled": True, "local_media_path": str(missing)}})
    )

    assert payload["enabled"] is True
    assert payload["ready"] is False
    assert payload["url"] == ""
    assert payload["error"] == "missing"


def test_local_video_expressions_expose_calibration_and_motion_override(monkeypatch, tmp_path):
    media = tmp_path / "avatar.mp4"
    media.write_bytes(b"test-video")
    monkeypatch.delenv("ARGO_LOCAL_AVATAR_MEDIA", raising=False)
    monkeypatch.delenv("ARGO_LOCAL_AVATAR_MEDIA_ENABLED", raising=False)
    for enabled in (None, True, False):
        payload = local_avatar_media_status(FakeConfig({"avatar": {
            "local_media_path": str(media),
            "local_media_profile": "halo",
            "motion_enabled": enabled,
        }}))
        assert payload["ready"] is True
        assert payload["content_type"] == "video/mp4"
        assert payload["media_type"] == "video"
        assert payload["expression_profile"] == "halo"
        assert payload["motion_enabled"] is enabled
