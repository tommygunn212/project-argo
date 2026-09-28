"""Avatar readiness and local-media configuration for Smooth Voice."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path
from typing import Any

from core.config import get_config

ROOT = Path(__file__).resolve().parents[1]
HEDRA_REALTIME_RETIRED = True
HEDRA_REALTIME_NOTICE = (
    "Hedra retired its realtime avatar service. Voice uses direct LiveKit audio; "
    "the Cortana portrait remains available locally."
)
LOCAL_AVATAR_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def _env_or_config(config: Any, env_key: str, config_key: str, default: Any) -> Any:
    env_value = os.getenv(env_key)
    if env_value not in (None, ""):
        return env_value
    value = config.get(config_key, default)
    return default if value in (None, "") else value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def resolve_local_avatar_media(config: Any | None = None) -> tuple[Path | None, str, str, str]:
    cfg = config or get_config()
    enabled = _bool(
        _env_or_config(cfg, "ARGO_LOCAL_AVATAR_MEDIA_ENABLED", "avatar.local_media_enabled", True)
    )
    raw_path = str(
        _env_or_config(cfg, "ARGO_LOCAL_AVATAR_MEDIA", "avatar.local_media_path", "") or ""
    ).strip()
    if not enabled or not raw_path:
        return None, "", raw_path, "not_configured"

    media_path = Path(raw_path).expanduser()
    if not media_path.is_absolute():
        media_path = ROOT / media_path
    content_type = LOCAL_AVATAR_MEDIA_TYPES.get(media_path.suffix.lower(), "")
    if not content_type:
        return media_path, "", raw_path, "unsupported_type"
    if not media_path.exists() or not media_path.is_file():
        return media_path, content_type, raw_path, "missing"
    return media_path, content_type, raw_path, ""


def local_avatar_media_status(config: Any | None = None) -> dict[str, Any]:
    cfg = config or get_config()
    media_path, content_type, raw_path, error = resolve_local_avatar_media(config)
    ready = bool(media_path and content_type and not error)
    motion_enabled = cfg.get("avatar.motion_enabled", None)
    return {
        "enabled": error != "not_configured",
        "ready": ready,
        "path": raw_path,
        "url": "/v2-assets/local-avatar-media" if ready else "",
        "content_type": content_type,
        "media_type": "video" if content_type.startswith("video/") else "image",
        "expression_profile": str(cfg.get("avatar.local_media_profile", "") or ""),
        "motion_enabled": None if motion_enabled is None else _bool(motion_enabled),
        "error": error,
    }


def hedra_avatar_status(config: Any | None = None) -> dict[str, Any]:
    image_path_raw = os.getenv("HEDRA_AVATAR_IMAGE", "").strip()
    image_path = Path(image_path_raw).expanduser() if image_path_raw else None
    if image_path and not image_path.is_absolute():
        image_path = ROOT / image_path

    plugin_ready = False
    plugin_version = ""
    try:
        plugin_version = metadata.version("livekit-plugins-hedra")
        plugin_ready = True
    except Exception:
        pass

    return {
        "enabled": _bool(os.getenv("ARGO_HEDRA_AVATAR_ENABLED", False)),
        "provider": "hedra_live_avatar",
        "api_key_ready": bool(os.getenv("HEDRA_API_KEY", "").strip()),
        "avatar_id_ready": bool(os.getenv("HEDRA_AVATAR_ID", "").strip()),
        "image_ready": bool(image_path and image_path.exists()),
        "image": image_path_raw,
        "plugin_ready": plugin_ready,
        "plugin_version": plugin_version,
        "ready": False,
        "service_retired": HEDRA_REALTIME_RETIRED,
        "api_url": os.getenv("HEDRA_API_URL", "https://api.hedra.com/public/livekit/v1/session"),
        "mode": "livekit_video_track",
        "fallback": "local_cortana_portrait",
        "local_media": local_avatar_media_status(config),
        "error": HEDRA_REALTIME_NOTICE,
    }
