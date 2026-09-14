"""Movies and TV: find them in Jellyfin, play them off disk.

Tommy has 238 movies and 30 series on his Jellyfin server. ARGO had no way
to reach any of it - every media tool it owned was pointed at the music
index, so "launch a movie" was never going to work. Nothing was broken; the
capability did not exist.

Jellyfin is used for SEARCH only, because that is what it is good at: real
titles, years, and the local path of every file. Playback is a local player
on the local file. Nothing streams, so a media-server hiccup cannot silence
a film that is sitting on the same disk.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ARGO.Video")

# Full-screen players, best first. ffplay is the fallback of last resort: it
# works, but it is a developer's tool and looks like one.
PLAYER_CANDIDATES = (
    (r"C:\Program Files\VideoLAN\VLC\vlc.exe", ["--fullscreen", "--play-and-exit"]),
    (r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe", ["--fullscreen", "--play-and-exit"]),
    ("vlc", ["--fullscreen", "--play-and-exit"]),
    ("mpv", ["--fullscreen"]),
    ("ffplay", ["-fs", "-autoexit"]),
)

VIDEO_SUFFIXES = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".mpg", ".mpeg", ".webm"}

_process: Optional[subprocess.Popen] = None
_now_playing: dict = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Finding things
# ---------------------------------------------------------------------------

def _credentials() -> tuple[str, str, str]:
    url = os.getenv("JELLYFIN_URL") or ""
    key = os.getenv("JELLYFIN_API_KEY") or ""
    uid = os.getenv("JELLYFIN_USER_ID") or ""
    if not (url and key and uid):
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        url = os.getenv("JELLYFIN_URL") or ""
        key = os.getenv("JELLYFIN_API_KEY") or ""
        uid = os.getenv("JELLYFIN_USER_ID") or ""
    return url.rstrip("/"), key, uid


def _jellyfin(path: str, params: dict) -> Optional[dict]:
    import json

    url, key, uid = _credentials()
    if not (url and key):
        return None
    params = {**params, "userId": uid}
    full = f"{url}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        full, headers={"X-MediaBrowser-Token": key, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        logger.warning("[Video] Jellyfin search failed", exc_info=True)
        return None


ITEM_TYPES = {
    "movie": "Movie",
    "episode": "Episode",
    "series": "Series",
    "any": "Movie,Episode",
}


def _episodes_of_series(name: str, limit: int) -> list[dict]:
    """Episodes of the show whose NAME matches, earliest first."""
    shows = _jellyfin("/Items", {
        "IncludeItemTypes": "Series", "Recursive": "true",
        "SearchTerm": name, "Limit": "1",
    })
    items = (shows or {}).get("Items") or []
    if not items:
        return []
    episodes = _jellyfin("/Items", {
        "ParentId": items[0].get("Id"),
        "IncludeItemTypes": "Episode",
        "Recursive": "true",
        "Limit": str(max(1, min(50, int(limit)))),
        "Fields": "Path,ProductionYear,SeriesName",
        "SortBy": "ParentIndexNumber,IndexNumber",
    })
    return list((episodes or {}).get("Items") or [])


def search(query: str, kind: str = "movie", limit: int = 10) -> list[dict]:
    """Find watchable items by title. Returns newest-first on ties."""
    include = ITEM_TYPES.get((kind or "movie").lower(), "Movie")
    data = _jellyfin(
        "/Items",
        {
            "IncludeItemTypes": include,
            "Recursive": "true",
            "SearchTerm": query,
            "Limit": str(max(1, min(50, int(limit)))),
            "Fields": "Path,ProductionYear,SeriesName",
            "SortBy": "SortName",
        },
    )
    items = list(data.get("Items", [])) if data else []

    # "Play True Detective" finds nothing by episode title, because episode
    # titles do not contain the show's name. Fall back to locating the series
    # and taking its episodes in order.
    if not items and include == "Episode":
        items = _episodes_of_series(query, limit)

    results = []
    for item in items:
        path = item.get("Path") or ""
        results.append({
            "id": item.get("Id"),
            "title": item.get("Name"),
            "year": item.get("ProductionYear"),
            "series": item.get("SeriesName"),
            "type": item.get("Type"),
            "path": path,
            "on_disk": bool(path) and Path(path).exists(),
        })
    return results


def catalogue_size() -> dict:
    """How much there is to watch, straight from the server."""
    data = _jellyfin("/Items/Counts", {})
    if not data:
        return {}
    return {
        "movies": data.get("MovieCount", 0),
        "series": data.get("SeriesCount", 0),
        "episodes": data.get("EpisodeCount", 0),
    }


# ---------------------------------------------------------------------------
# Playing them
# ---------------------------------------------------------------------------

def _find_player() -> Optional[tuple[str, list[str]]]:
    for candidate, flags in PLAYER_CANDIDATES:
        resolved = candidate if os.path.exists(candidate) else shutil.which(candidate)
        if resolved:
            return resolved, flags
    return None


def is_playing() -> bool:
    with _lock:
        return _process is not None and _process.poll() is None


def now_playing() -> dict:
    with _lock:
        return dict(_now_playing)


def stop() -> bool:
    """Close whatever is on screen. Safe to call when nothing is."""
    global _process
    with _lock:
        process, _process = _process, None
        _now_playing.clear()
    if process is None:
        return False
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    except Exception:
        logger.debug("[Video] stop failed", exc_info=True)
    return True


# A film that is going to fail on a missing codec or a bad file fails fast.
# One that is playing is still playing after this.
PLAYBACK_SETTLE_SECONDS = 2.0


def play(path: str, title: str = "", *, settle: float | None = None) -> dict:
    """Open a video file full screen, and report whether it stayed open.

    Launching a player is not playing. The same distinction that let ARGO
    announce music into silence applies here, so this waits and checks.
    """
    global _process

    if not path:
        return {"ok": False, "error": "no_path", "message": "No file to play."}
    file = Path(path)
    if not file.exists():
        return {"ok": False, "error": "missing_file", "path": path,
                "message": f"{title or file.name} is in the library but the file is not on disk."}

    found = _find_player()
    if not found:
        return {"ok": False, "error": "no_player",
                "message": "No video player is installed - VLC, mpv or ffplay would do."}
    player, flags = found

    stop()
    try:
        process = subprocess.Popen(
            [player, *flags, str(file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.exception("[Video] could not start %s", player)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "message": f"I could not start the player for {title or file.name}."}

    with _lock:
        _process = process
        _now_playing.clear()
        _now_playing.update({"title": title or file.stem, "path": str(file),
                             "player": Path(player).name, "started_at": time.time()})

    time.sleep(PLAYBACK_SETTLE_SECONDS if settle is None else settle)

    if process.poll() is not None:
        with _lock:
            _now_playing.clear()
            _process = None
        return {
            "ok": False,
            "error": "playback_died",
            "title": title or file.stem,
            "path": str(file),
            "message": (
                f"{title or file.stem} started and then closed straight away - "
                "nothing is on screen. The file may be damaged or need a codec."
            ),
        }

    logger.info("[Video] playing %s via %s", file.name, Path(player).name)
    return {"ok": True, "playing": True, "title": title or file.stem,
            "path": str(file), "player": Path(player).name,
            "message": f"Playing {title or file.stem}."}
