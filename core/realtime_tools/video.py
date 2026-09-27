"""Movies and TV from the local library, verified to stay on screen.
"""

from __future__ import annotations

from core.realtime_tools._base import capability

__all__ = [
    "video_search",
    "video_play",
    "video_stop",
    "video_status",
]


@capability
def video_search(query: str, kind: str = "movie", limit: int = 10) -> dict:
    """Find a movie or episode by title."""
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


@capability
def video_play(query: str, kind: str = "movie") -> dict:
    """Find something by title and put it on screen.

    Reports whether the player STAYED open, not merely that it was launched -
    the same distinction that had ARGO announcing music into silence.
    """
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


@capability
def video_stop() -> dict:
    """Close whatever is on screen."""
    from core import video_library

    was_playing = video_library.stop()
    return {"ok": True, "stopped": was_playing,
            "message": "Stopped." if was_playing else "Nothing was playing."}


@capability
def video_status() -> dict:
    """What is on screen, and how much there is to watch."""
    from core import video_library

    return {
        "ok": True,
        "playing": video_library.is_playing(),
        "now_playing": video_library.now_playing() or None,
        "library": video_library.catalogue_size(),
    }
