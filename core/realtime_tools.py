"""Capabilities the realtime voice agent can call.

The classic pipeline reaches these through its _respond_with_* handlers. The
realtime worker runs in its own process and never imports the pipeline, so
without this module the model has nothing to call and refuses — which reads to
the user as ARGO losing abilities it used to have.

Every function here:
  - is safe to call from a worker thread (callers wrap in asyncio.to_thread),
  - returns a JSON-serialisable dict, never raises to the caller,
  - reports failure as {"ok": False, "error": ...} so the model can say what
    actually went wrong instead of inventing a result.

Filesystem access is confined to an allowlist. The ARGO install is always
readable; anything else must be granted by Tommy in config.json under
filesystem.allowed_folders. Granting is deliberately NOT callable by voice.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("ARGO.RealtimeTools")

ROOT = Path(__file__).resolve().parents[1]

# Names returned by a folder listing before it is truncated. A silently short
# alphabetical list makes the model report that a file is absent when it is
# merely past the cut-off, so truncation is always reported.
LIST_CAP = 200


def _fail(action: str, exc: Exception) -> dict:
    logger.exception("[Tools] %s failed", action)
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Machine
# ---------------------------------------------------------------------------

def _memory() -> tuple:
    try:
        from system_health import get_memory_info

        return get_memory_info()
    except Exception:
        logger.exception("[Tools] memory info unavailable")
        return None, None


def pc_specs() -> dict:
    """Motherboard, BIOS, CPU, RAM and graphics for this machine."""
    try:
        from system_profile import get_system_profile, get_gpu_profile

        p = get_system_profile() or {}
        gpus = get_gpu_profile() or []
        total_gb, used_pct = _memory()
        return {
            "ok": True,
            "motherboard": p.get("motherboard") or p.get("motherboard_product"),
            "motherboard_maker": p.get("motherboard_maker"),
            "bios_version": p.get("bios_version"),
            "cpu": p.get("cpu"),
            "cpu_cores": p.get("cpu_cores"),
            "cpu_threads": p.get("cpu_threads"),
            "cpu_max_mhz": p.get("cpu_max_mhz"),
            "memory_total_gb": total_gb,
            "memory_used_percent": used_pct,
            "memory_speed_mhz": p.get("memory_speed_mhz"),
            "memory_modules": p.get("memory_modules"),
            "graphics": [
                {"name": g.get("name"), "driver": g.get("driver_version")} for g in gpus
            ],
            "os": p.get("os"),
        }
    except Exception as exc:
        return _fail("pc_specs", exc)


def drive_space() -> dict:
    """Free and used space for every drive."""
    try:
        from system_health import get_disk_info

        return {"ok": True, "drives": get_disk_info() or {}}
    except Exception as exc:
        return _fail("drive_space", exc)


def system_status() -> dict:
    """Live health: memory, temperatures, overall status."""
    try:
        from system_health import get_system_health, get_temperatures

        total_gb, used_pct = _memory()
        return {
            "ok": True,
            "health": get_system_health() or {},
            "temperatures_c": get_temperatures() or {},
            "memory_total_gb": total_gb,
            "memory_used_percent": used_pct,
        }
    except Exception as exc:
        return _fail("system_status", exc)


def diagnostics() -> dict:
    """Run ARGO's own self-diagnostics and report component health."""
    try:
        from core.self_diagnostics import run_diagnostics

        return {"ok": True, "report": run_diagnostics() or {}}
    except Exception as exc:
        return _fail("diagnostics", exc)


# ---------------------------------------------------------------------------
# Filesystem — allowlisted
# ---------------------------------------------------------------------------

def allowed_roots() -> list[Path]:
    """ARGO's install plus any folder Tommy granted in config.json.

    Read fresh on every call so a granted folder takes effect without a restart.
    """
    roots = [ROOT]
    try:
        from core.config import get_config

        raw = get_config().get("filesystem.allowed_folders", []) or []
        if isinstance(raw, str):
            raw = [raw]
        for entry in raw:
            try:
                p = Path(str(entry)).expanduser().resolve()
                if p.is_dir():
                    roots.append(p)
            except Exception:
                logger.warning("[Tools] ignoring unusable allowed folder: %r", entry)
    except Exception:
        logger.exception("[Tools] could not read filesystem.allowed_folders")
    return roots


def _within_allowed(target: Path) -> bool:
    for root in allowed_roots():
        if target == root or root in target.parents:
            return True
    return False


def list_folder(path: str = "") -> dict:
    """List a folder ARGO is allowed to read.

    "" or a relative path means inside the ARGO install. An absolute path must
    fall inside a granted folder.
    """
    try:
        raw = (path or "").strip().strip('"')
        candidate = Path(raw).expanduser() if raw else ROOT
        target = candidate if candidate.is_absolute() else (ROOT / raw)
        target = target.resolve()

        if not _within_allowed(target):
            return {
                "ok": False,
                "error": "not_allowed",
                "message": (
                    f"{target} is outside the folders I'm allowed to read. "
                    "Add it to filesystem.allowed_folders in config.json to grant access."
                ),
                "allowed": [str(r) for r in allowed_roots()],
            }
        if not target.is_dir():
            return {"ok": False, "error": "not_found", "message": f"There is no folder at {target}."}

        dirs, files = [], []
        for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if item.name.startswith((".", "__")):
                continue
            (dirs if item.is_dir() else files).append(item.name)
        return {
            "ok": True,
            "folder": str(target),
            "subfolders": dirs[:LIST_CAP],
            "files": files[:LIST_CAP],
            "counts": {"subfolders": len(dirs), "files": len(files)},
            "truncated": len(dirs) > LIST_CAP or len(files) > LIST_CAP,
        }
    except Exception as exc:
        return _fail("list_folder", exc)


def read_text_file(path: str, max_chars: int = 4000) -> dict:
    """Read a text file inside an allowed folder."""
    try:
        raw = (path or "").strip().strip('"')
        candidate = Path(raw).expanduser()
        target = (candidate if candidate.is_absolute() else (ROOT / raw)).resolve()
        if not _within_allowed(target):
            return {"ok": False, "error": "not_allowed",
                    "message": f"{target} is outside the folders I'm allowed to read."}
        if not target.is_file():
            return {"ok": False, "error": "not_found", "message": f"There is no file at {target}."}
        if target.stat().st_size > 5_000_000:
            return {"ok": False, "error": "too_large", "message": "That file is too big to read aloud."}
        text = target.read_text(encoding="utf-8", errors="replace")
        return {
            "ok": True,
            "file": str(target),
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
        }
    except Exception as exc:
        return _fail("read_text_file", exc)


def find_files(query: str) -> dict:
    """Search for files by name or keyword."""
    try:
        from tools.filesystem import search_files

        # search_files defaults to the user's document folders, which do not
        # include the ARGO install — "find the livekit config" returned nothing.
        # Search exactly what ARGO is allowed to read.
        roots = [str(r) for r in allowed_roots()]
        hits = search_files(query, roots=roots, max_results=12) or []
        return {"ok": True, "query": query, "count": len(hits),
                "searched": roots, "results": hits}
    except Exception as exc:
        return _fail("find_files", exc)


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

_PLAY_KINDS = {"song", "artist", "genre", "keyword", "random"}


def music_play(query: str = "", kind: str = "keyword") -> dict:
    """Start music. kind is song, artist, genre, keyword or random."""
    try:
        from core.music_player import get_music_player

        kind = (kind or "keyword").strip().lower()
        if kind not in _PLAY_KINDS:
            kind = "keyword"
        player = get_music_player()
        if kind == "random" or not query.strip():
            started = player.play_random()
            kind = "random"
        else:
            started = {
                "song": player.play_by_song,
                "artist": player.play_by_artist,
                "genre": player.play_by_genre,
                "keyword": player.play_by_keyword,
            }[kind](query)
        return {
            "ok": bool(started),
            "kind": kind,
            "query": query,
            "playing": player.is_playing(),
            "message": "Playing." if started else f"Nothing matched {query!r}.",
        }
    except Exception as exc:
        return _fail("music_play", exc)


def music_stop() -> dict:
    try:
        from core.music_player import get_music_player

        get_music_player().stop()
        return {"ok": True, "playing": False}
    except Exception as exc:
        return _fail("music_stop", exc)


def music_next() -> dict:
    try:
        from core.music_player import get_music_player

        player = get_music_player()
        return {"ok": bool(player.play_next()), "playing": player.is_playing()}
    except Exception as exc:
        return _fail("music_next", exc)


def music_status() -> dict:
    try:
        from core.music_player import get_music_player, get_playback_state

        state = get_playback_state()
        now = getattr(state, "current_track", None) or getattr(state, "track_name", None)
        return {"ok": True, "playing": get_music_player().is_playing(), "now_playing": now}
    except Exception as exc:
        return _fail("music_status", exc)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def app_open(name: str) -> dict:
    """Launch an app by the name Tommy said."""
    try:
        from core.app_control import open_app, resolve_app_name

        key = resolve_app_name(name) or name
        ok, message = open_app(key)
        return {"ok": bool(ok), "app": key, "requested": name, "message": message}
    except Exception as exc:
        return _fail("app_open", exc)


def app_close(name: str) -> dict:
    try:
        from core.app_control import close_app, resolve_app_name

        key = resolve_app_name(name) or name
        ok, message = close_app(key)
        return {"ok": bool(ok), "app": key, "requested": name, "message": message}
    except Exception as exc:
        return _fail("app_close", exc)


def app_focus(name: str) -> dict:
    try:
        from core.app_control import focus_app, resolve_app_name

        key = resolve_app_name(name) or name
        ok, message = focus_app(key)
        return {"ok": bool(ok), "app": key, "requested": name, "message": message}
    except Exception as exc:
        return _fail("app_focus", exc)


def apps_running() -> dict:
    try:
        from core.app_control import get_active_app, list_running_apps, get_supported_app_displays

        active, title = get_active_app()
        return {
            "ok": True,
            "running": list_running_apps() or [],
            "active": active,
            "active_window_title": title,
            "known_apps": get_supported_app_displays() or [],
        }
    except Exception as exc:
        return _fail("apps_running", exc)


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

def volume_set(percent: int) -> dict:
    try:
        from core.system_volume import set_volume_percent

        pct = max(0, min(100, int(percent)))
        ok, message, level, _prev, muted = set_volume_percent(pct)
        return {"ok": bool(ok), "volume_percent": level, "muted": muted, "message": message}
    except Exception as exc:
        return _fail("volume_set", exc)


def volume_status() -> dict:
    try:
        from core.system_volume import get_status

        level, muted = get_status()
        return {"ok": True, "volume_percent": level, "muted": muted}
    except Exception as exc:
        return _fail("volume_status", exc)
