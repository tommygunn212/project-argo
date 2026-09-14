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
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

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
        if not started:
            return {
                "ok": False,
                "error": "no_match",
                "kind": kind,
                "query": query,
                "playing": False,
                "message": f"Nothing matched {query!r}.",
            }
        return _confirm_playing(player, kind=kind, query=query)
    except Exception as exc:
        return _fail("music_play", exc)


# How long to wait before believing that playback started. A stream that
# 404s kills ffplay in well under this; a stream that works is still going.
PLAYBACK_SETTLE_SECONDS = 1.2


def _confirm_playing(player, *, kind: str, query: str) -> dict:
    """Report what is actually coming out of the speakers.

    Launching a player is not playing. When the source 404s, ffplay exits
    with code 0 before anyone looks, and ARGO used to announce the track
    anyway - which is how Tommy was told music was playing in silence.
    """
    track = {}
    try:
        track = dict(getattr(player, "current_track", {}) or {})
    except Exception:
        track = {}

    time.sleep(PLAYBACK_SETTLE_SECONDS)

    try:
        playing = bool(player.is_playing())
    except Exception:
        logger.debug("[Tools] is_playing failed", exc_info=True)
        playing = False

    song = track.get("song") or track.get("title")
    artist = track.get("artist")
    named = " - ".join(p for p in (artist, song) if p) or "the track"

    if playing:
        return {"ok": True, "kind": kind, "query": query, "playing": True,
                "track": {"artist": artist, "song": song},
                "message": f"Playing {named}."}

    return {
        "ok": False,
        "error": "playback_died",
        "kind": kind,
        "query": query,
        "playing": False,
        "track": {"artist": artist, "song": song},
        "message": (
            f"I found {named} and started it, but playback stopped immediately - "
            "no sound is coming out. The track is in ARGO's index but the "
            "media server could not serve it."
        ),
    }


_DECADE_WORDS = {
    "twenties": 1920, "thirties": 1930, "forties": 1940, "fifties": 1950,
    "sixties": 1960, "seventies": 1970, "eighties": 1980, "nineties": 1990,
    "noughties": 2000, "two thousands": 2000, "tens": 2010, "twenty tens": 2010,
}


def parse_era(era: str) -> Optional[tuple]:
    """Turn a spoken era into a (year_start, year_end) range.

    Handles "80s", "1980s", "the eighties", "1975", "1975 to 1980". Bare
    two-digit decades below 30 are read as 2000s, so "20s" is 2020 not 1920 -
    ask for "the roaring twenties" era by year if you mean the other one.
    """
    import re

    text = (era or "").strip().lower().replace("'", "").replace("the ", "")
    if not text:
        return None

    span = re.search(r"(\d{4})\s*(?:to|-|until|through)\s*(\d{4})", text)
    if span:
        a, b = int(span.group(1)), int(span.group(2))
        return (min(a, b), max(a, b))

    for word, start in _DECADE_WORDS.items():
        if word in text:
            return (start, start + 9)

    decade = re.search(r"(\d{2,4})\s*s\b", text)
    if decade:
        raw = decade.group(1)
        year = int(raw)
        if len(raw) == 2:
            year = 2000 + year if year < 30 else 1900 + year
        year = (year // 10) * 10
        return (year, year + 9)

    single = re.search(r"\b(\d{4})\b", text)
    if single:
        y = int(single.group(1))
        return (y, y)

    return None


def music_play_era(era: str, genre: str = "", artist: str = "") -> dict:
    """Play music from a period, optionally narrowed by genre or artist.

    The track database already stores a year and query_tracks accepts
    year_start/year_end; nothing exposed it, so era was not something that
    could be asked for.
    """
    try:
        rng = parse_era(era)
        if not rng:
            return {"ok": False, "error": "unparsed_era",
                    "message": f"I couldn't work out what period {era!r} means."}
        year_start, year_end = rng

        from core.music_player import MusicDatabase, get_music_player

        tracks = MusicDatabase().query_tracks(
            year_start=year_start,
            year_end=year_end,
            genre=genre or None,
            artist=artist or None,
            limit=200,
        ) or []
        if not tracks:
            return {"ok": False, "error": "no_matches", "era": era,
                    "years": [year_start, year_end],
                    "message": f"I have nothing from {year_start} to {year_end}"
                               + (f" by {artist}" if artist else "")
                               + (f" in {genre}" if genre else "") + "."}

        import random

        pick = random.choice(tracks)
        player = get_music_player()
        path = pick.get("path") or pick.get("file_path") or pick.get("track_path")
        # query_tracks returns the track name under "song", not "title".
        title = pick.get("song") or pick.get("title") or pick.get("name") or "that"
        started = player.play(path, title, track_data=pick) if path else False
        if not started:
            return {"ok": False, "error": "no_match", "era": era,
                    "years": [year_start, year_end], "matches": len(tracks),
                    "playing": False,
                    "message": f"I could not start {title}."}
        result = _confirm_playing(player, kind="era", query=era)
        result.update({
            "era": era,
            "years": [year_start, year_end],
            "matches": len(tracks),
            "now_playing": {"title": title, "artist": pick.get("artist"), "year": pick.get("year")},
        })
        return result
    except Exception as exc:
        return _fail("music_play_era", exc)


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
    """Launch an app by the name Tommy said.

    ARGO's curated registry knows five apps, so anything else used to fail
    silently. Fall through to what is actually installed - taskbar pins first,
    then the registry's App Paths, the Start Menu, and PATH.
    """
    try:
        from core.app_control import open_app, resolve_app_name

        key = resolve_app_name(name)
        if key:
            ok, message = open_app(key)
            return {"ok": bool(ok), "app": key, "requested": name,
                    "source": "argo_registry", "message": message}

        from core.app_resolver import resolve

        hit = resolve(name)
        if not hit:
            return {
                "ok": False,
                "error": "not_installed",
                "requested": name,
                "message": f"I couldn't find anything installed called {name}.",
            }

        os.startfile(hit["target"])  # handles .lnk shortcuts and .exe alike
        return {
            "ok": True,
            "app": hit["name"],
            "requested": name,
            "source": hit["source"],
            "message": f"Opening {hit['name']}.",
        }
    except Exception as exc:
        return _fail("app_open", exc)


def apps_launchable() -> dict:
    """Everything ARGO could open, and what is pinned to the taskbar."""
    try:
        from core.app_resolver import installed_names, _taskbar_index

        names = installed_names()
        return {
            "ok": True,
            "count": len(names),
            "pinned": sorted(p.stem for p in _taskbar_index().values()),
            "all": names,
        }
    except Exception as exc:
        return _fail("apps_launchable", exc)


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


def music_library_status(sample: int = 60) -> dict:
    """Is the music index still true? Where the library is, and whether it plays.

    The index drifted from the library once already - thousands of tracks
    were announced for weeks while every one of them 404'd, because nothing
    ever checked the index against reality. This checks.
    """
    try:
        import sqlite3

        from core.music_player import MUSIC_DB_PATH

        db = ROOT / MUSIC_DB_PATH
        if not db.exists():
            return {"ok": False, "error": "no_library",
                    "message": "There is no music library indexed."}

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            total = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            streamed = con.execute(
                "SELECT COUNT(*) FROM tracks WHERE path LIKE 'jellyfin://%'"
            ).fetchone()[0]
            rows = con.execute(
                "SELECT path FROM tracks WHERE path NOT LIKE 'jellyfin://%' "
                "ORDER BY RANDOM() LIMIT ?", (max(1, min(500, int(sample))),)
            ).fetchall()
        finally:
            con.close()

        checked = [r[0] for r in rows]
        missing = [p for p in checked if not Path(p).exists()]
        healthy = not missing and not streamed

        result = {
            "ok": True,
            "tracks": total,
            "source": meta.get("source", "unknown"),
            "root": meta.get("root"),
            "indexed_at": meta.get("ingested_at"),
            "checked": len(checked),
            "missing_from_disk": len(missing),
            "streamed_from_server": streamed,
            "healthy": healthy,
        }
        if streamed:
            result["message"] = (
                f"{streamed} of {total} tracks are server streams rather than files. "
                "If the server no longer has them they will announce and then fall silent."
            )
        elif missing:
            result["examples"] = missing[:3]
            result["message"] = (
                f"{len(missing)} of the {len(checked)} tracks I checked are indexed but "
                f"missing from disk. The library may have moved - it needs re-indexing."
            )
        else:
            result["message"] = f"{total} tracks indexed from {meta.get('root')}, and they are there."
        return result
    except Exception as exc:
        return _fail("music_library_status", exc)


# ---------------------------------------------------------------------------
# Movies and TV
# ---------------------------------------------------------------------------

def video_search(query: str, kind: str = "movie", limit: int = 10) -> dict:
    """Find a movie or episode by title."""
    try:
        from core import video_library

        results = video_library.search(query, kind=kind, limit=limit)
        return {
            "ok": True,
            "query": query,
            "kind": kind,
            "count": len(results),
            "results": [
                {"title": r["title"], "year": r["year"], "series": r["series"],
                 "type": r["type"], "on_disk": r["on_disk"]}
                for r in results
            ],
        }
    except Exception as exc:
        return _fail("video_search", exc)


def video_play(query: str, kind: str = "movie") -> dict:
    """Find something by title and put it on screen.

    Reports whether the player STAYED open, not merely that it was launched -
    the same distinction that had ARGO announcing music into silence.
    """
    try:
        from core import video_library

        wanted = (query or "").strip()
        if not wanted:
            return {"ok": False, "error": "no_title", "message": "What should I play?"}

        results = video_library.search(wanted, kind=kind, limit=10)
        if not results:
            return {"ok": False, "error": "not_found", "query": wanted,
                    "message": f"I could not find {wanted} in the library."}

        playable = [r for r in results if r["on_disk"]]
        if not playable:
            missing = results[0]
            return {"ok": False, "error": "missing_file", "query": wanted,
                    "title": missing["title"],
                    "message": (f"{missing['title']} is in the library but its file is "
                                "not on disk.")}

        chosen = playable[0]
        label = chosen["title"]
        if chosen.get("series"):
            label = f"{chosen['series']} - {label}"
        elif chosen.get("year"):
            label = f"{label} ({chosen['year']})"

        result = video_library.play(chosen["path"], label)
        result.setdefault("query", wanted)
        result["alternatives"] = [r["title"] for r in playable[1:4]]
        return result
    except Exception as exc:
        return _fail("video_play", exc)


def video_stop() -> dict:
    """Close whatever is on screen."""
    try:
        from core import video_library

        was_playing = video_library.stop()
        return {"ok": True, "stopped": was_playing,
                "message": "Stopped." if was_playing else "Nothing was playing."}
    except Exception as exc:
        return _fail("video_stop", exc)


def video_status() -> dict:
    """What is on screen, and how much there is to watch."""
    try:
        from core import video_library

        return {
            "ok": True,
            "playing": video_library.is_playing(),
            "now_playing": video_library.now_playing() or None,
            "library": video_library.catalogue_size(),
        }
    except Exception as exc:
        return _fail("video_status", exc)


# ---------------------------------------------------------------------------
# Writing: into a live app window, and into saved drafts
# ---------------------------------------------------------------------------

def writable_apps() -> dict:
    """Which apps ARGO can actually type into, as opposed to merely open."""
    try:
        from core.app_control import WRITABLE_APPS

        return {"ok": True, "apps": sorted(WRITABLE_APPS)}
    except Exception as exc:
        return _fail("writable_apps", exc)


_UIA_READ_PS = """
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ClassNameProperty, '__CLASS__')
$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
foreach ($w in $wins) {
    $docCond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document)
    $doc = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $docCond)
    if ($doc -ne $null) {
        $tp = $doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        Write-Output $tp.DocumentRange.GetText(-1)
    }
}
"""

# Window class names, for reading a window's text back out via UI Automation.
_UIA_CLASS = {"notepad": "Notepad", "word": "OpusApp"}


def read_app_text(app_key: str) -> Optional[str]:
    """Read what is actually in an app's window, or None if it can't be read.

    None means "could not check", which is not the same as "empty" - callers
    must not treat it as proof either way.
    """
    klass = _UIA_CLASS.get(app_key)
    if not klass:
        return None
    script = _UIA_READ_PS.replace("__CLASS__", klass)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        logger.debug("[Tools] read_app_text failed for %s", app_key, exc_info=True)
        return None
    if result.returncode != 0:
        return None
    return result.stdout or ""


def app_write(name: str, text: str) -> dict:
    """Type text into a running app window (Notepad or Word).

    Opens the app first if it is not already running. Anything outside
    WRITABLE_APPS is refused by name rather than silently dropped, so ARGO
    says "I can't type into Orca Slicer" instead of claiming it wrote.
    """
    try:
        from core.app_control import WRITABLE_APPS, resolve_app_name, write_text_to_app

        payload = (text or "").strip()
        if not payload:
            return {"ok": False, "error": "empty_text", "requested": name,
                    "message": "There was nothing to write."}

        key = resolve_app_name(name)
        if key not in WRITABLE_APPS:
            return {
                "ok": False,
                "error": "not_writable",
                "requested": name,
                "writable": sorted(WRITABLE_APPS),
                "message": (
                    f"I can open {name}, but I can only type into "
                    f"{' or '.join(sorted(WRITABLE_APPS))} right now."
                ),
            }

        ok, message = write_text_to_app(key, payload)
        if not ok:
            return {"ok": False, "error": "write_failed", "app": key,
                    "requested": name, "message": message}

        # write_text_to_app reports on whether it sent the paste, not on
        # whether anything arrived - a fuzzy AppActivate can match the wrong
        # window and the keystroke goes nowhere. Read the window back.
        time.sleep(0.4)
        seen = read_app_text(key)
        if seen is None:
            return {"ok": True, "verified": False, "app": key, "requested": name,
                    "characters": len(payload),
                    "message": f"{message} I couldn't check the window to confirm it."}
        if payload not in seen:
            return {
                "ok": False,
                "error": "not_verified",
                "app": key,
                "requested": name,
                "characters": len(payload),
                "message": (
                    f"I sent it to {key}, but the text isn't in the window - "
                    "it may have gone somewhere else."
                ),
            }
        return {"ok": True, "verified": True, "app": key, "requested": name,
                "characters": len(payload), "message": message}
    except Exception as exc:
        return _fail("app_write", exc)


DRAFT_KINDS = ("email", "document", "blog", "note")


def draft_write(kind: str, title: str, body: str, recipient: str = "") -> dict:
    """Save a draft (email, document, blog or note) to ARGO's drafts folder.

    This writes a file. It does not send anything - see email_status().
    """
    try:
        from tools import writing

        wanted = (kind or "").strip().lower()
        if wanted not in DRAFT_KINDS:
            return {"ok": False, "error": "unknown_kind", "requested": kind,
                    "kinds": list(DRAFT_KINDS)}
        if not (body or "").strip():
            return {"ok": False, "error": "empty_body", "kind": wanted,
                    "message": "There was nothing to write into the draft."}

        if wanted == "email":
            draft = writing.draft_email(recipient or "", title or "", body)
        elif wanted == "document":
            draft = writing.draft_document(title or "Untitled", body, recipient=recipient or "")
        elif wanted == "blog":
            draft = writing.draft_blog(title or "Untitled", body)
        else:
            draft = writing.save_note(body, title=title or None)

        return {"ok": True, "kind": wanted, "title": title,
                "recipient": recipient or None,
                "name": getattr(draft, "name", None),
                "path": str(getattr(draft, "path", "")) or None,
                "message": f"Saved the {wanted} draft."}
    except Exception as exc:
        return _fail("draft_write", exc)


def drafts_list(category: str = "", limit: int = 10) -> dict:
    try:
        from tools import writing

        rows = writing.list_drafts(category=category or None, limit=max(1, int(limit))) or []
        return {
            "ok": True,
            "count": len(rows),
            "category": category or "all",
            "drafts": [{"name": d.name, "category": d.category, "path": str(d.path)} for d in rows],
        }
    except Exception as exc:
        return _fail("drafts_list", exc)


def draft_read(name: str) -> dict:
    """Read back a saved draft by name, so ARGO can recite it."""
    try:
        from tools import writing

        def key(value: str) -> str:
            # Draft filenames are slugged ("readback_probe"); people say
            # "readback probe". Compare with the punctuation stripped out.
            return "".join(ch for ch in (value or "").lower() if ch.isalnum())

        wanted = key(name)
        if not wanted:
            return {"ok": False, "error": "no_name"}
        for draft in writing.list_drafts(limit=200) or []:
            if wanted in key(draft.name):
                text = draft.content
                return {"ok": True, "name": draft.name, "category": draft.category,
                        "path": str(draft.path), "characters": len(text), "content": text}
        return {"ok": False, "error": "not_found", "requested": name}
    except Exception as exc:
        return _fail("draft_read", exc)


def email_status() -> dict:
    """Whether sending is configured. Sending itself is not wired to voice."""
    try:
        from tools.email_sender import is_email_configured

        configured = bool(is_email_configured())
        return {
            "ok": True,
            "configured": configured,
            "can_send_by_voice": False,
            "message": (
                "Email sending is configured, but I'm not wired to send by voice yet."
                if configured else
                "Email sending isn't set up - there are no mail credentials configured."
            ),
        }
    except Exception as exc:
        return _fail("email_status", exc)
