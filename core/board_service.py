"""The board: data for the card workspace at /board.

Cards are Jobs, the latest thing Argo showed, parked ideas, project notes and
status. This module only reads them (parked items and notes live as plain files
under the projects root; jobs and the show board come from their own services)
and keeps two small things of its own: the layout Tommy chose per project (so it
survives a reload and shows up the same on his iPad) and which project Argo last
asked the board to switch to ("show me the H2D stuff").
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = Path(os.environ.get("ARGO_PROJECTS_ROOT") or "I:/argo-workspace/projects")
LAYOUT_FILE = ROOT / "runtime" / "board_layouts.json"
DEFAULT_PROJECTS = ["ChefsByte", "H2D Workbench", "MSUDBytes", "PKUBytes", "Argo", "YouTube",
                    "Archives", "Inbox"]
ALIASES = {
    **dict.fromkeys(("chefsbyte", "chefs byte", "cooking school", "cook school"), "ChefsByte"),
    **dict.fromkeys(("h2d", "printer", "workbench", "bambu", "h2d workbench"), "H2D Workbench"),
    **dict.fromkeys(("msud", "msudbytes"), "MSUDBytes"),
    **dict.fromkeys(("pku", "pkubytes"), "PKUBytes"),
    "argo": "Argo", "youtube": "YouTube", "video": "YouTube",
    **dict.fromkeys(("archive", "archives", "cat club", "family tree", "cheu"), "Archives"),
    "inbox": "Inbox",
}
COLORS = {"slate", "teal", "green", "amber", "rose", "violet", "blue", "gray"}
KINDS = ("ideas", "lists", "decisions", "finds")
ALL = "All"

_lock = threading.Lock()
_focus = {"project": "", "seq": 0, "tidy_seq": 0}


def normalize(project: str) -> str:
    """A project name as the board knows it: aliases resolved, 'All' for none."""
    raw = " ".join(str(project or "").split())[:80]
    if not raw or raw.casefold() in ("all", "everything"):
        return ALL
    if raw.casefold() in ALIASES:
        return ALIASES[raw.casefold()]
    safe = re.sub(r"[^\w -]", " ", raw, flags=re.UNICODE)
    return " ".join(safe.split()).strip(" .-")[:60].title() or ALL


def project_names() -> list[str]:
    names = list(DEFAULT_PROJECTS)
    try:
        for p in sorted(PROJECTS_ROOT.iterdir()):
            if p.is_dir() and not p.name.startswith((".", "_")) and p.name not in names:
                names.append(p.name)
    except OSError:
        pass
    return names


def _front_matter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                key, _, value = line.partition(":")
                if key.strip():
                    meta[key.strip()] = value.strip().strip('"')
            body = parts[2]
    return meta, body.strip()


def parked(project: str, limit: int = 30) -> list[dict]:
    """Newest-first parked items for a project (all projects when 'All')."""
    name = normalize(project)
    folders = ([PROJECTS_ROOT / name] if name != ALL
               else [PROJECTS_ROOT / n for n in project_names()])
    items = []
    for folder in folders:
        for kind in KINDS:
            try:
                files = list((folder / kind).glob("*.md"))
            except OSError:
                continue
            for path in files:
                try:
                    meta, body = _front_matter(path.read_text(encoding="utf-8"))
                except OSError:
                    continue
                items.append({"title": meta.get("title") or path.stem, "kind": meta.get("kind") or kind[:-1],
                              "date": meta.get("date") or path.name[:10], "why": meta.get("why", ""),
                              "project": folder.name, "preview": body[:240], "file": path.name})
    items.sort(key=lambda i: (i["date"], i["file"]), reverse=True)
    return items[:limit]


def notes(project: str, limit: int = 12) -> list[str]:
    name = normalize(project)
    if name == ALL:
        return []
    try:
        lines = (PROJECTS_ROOT / name / "notes.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    bullets = [ln.lstrip("-* ").strip() for ln in lines if ln.strip().startswith(("-", "*"))]
    return bullets[-limit:][::-1]


def _topic_slug(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.casefold()).strip("-")
    return slug[:60] or "general"


def add_topic_note(project: str, topic: str, text: str) -> dict:
    """Append a dated line to one topic under a project (a named stream of notes)."""
    name = normalize(project)
    if name == ALL:
        name = "Inbox"
    title = " ".join(topic.split())[:60] or "General"
    line = " ".join(text.split())[:1000]
    if not line:
        raise ValueError("nothing to note")
    folder = PROJECTS_ROOT / name / "topics"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (_topic_slug(title) + ".md")
    if not path.exists():
        path.write_text(f'---\ntitle: "{title}"\nproject: "{name}"\n---\n\n', encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {time.strftime('%Y-%m-%d')}: {line}\n")
    return {"project": name, "topic": title}


def topics(project: str, per_topic: int = 6) -> list[dict]:
    """Topics under a project (or every project for All): name, count, newest entries first."""
    name = normalize(project)
    names = project_names() if name == ALL else [name]
    found = []
    for proj in names:
        folder = PROJECTS_ROOT / proj / "topics"
        if not folder.is_dir():
            continue
        for path in folder.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _front_matter(text)
            entries = [ln.lstrip("-* ").strip() for ln in body.splitlines() if ln.strip().startswith(("-", "*"))]
            found.append({"project": proj, "topic": meta.get("title") or path.stem, "count": len(entries),
                          "entries": entries[-per_topic:][::-1], "mtime": path.stat().st_mtime})
    found.sort(key=lambda x: x["mtime"], reverse=True)
    for item in found:
        del item["mtime"]
    return found[:40]


def activity(limit: int = 15) -> list[dict]:
    """What Argo just did, newest first, from the action log."""
    try:
        from core.voice import action_log
        rows = action_log.recent(limit)
    except Exception:
        return []
    out = []
    for row in rows[::-1]:
        res = row.get("output")
        said = res.get("message") if isinstance(res, dict) else ""
        out.append({"clock": str(row.get("clock", ""))[:19], "tool": row.get("tool", "?"),
                    "ok": bool(row.get("ok")), "said": str(said or "")[:140]})
    return out


def _jobs_for(project: str, jobs: list[dict]) -> list[dict]:
    name = normalize(project)
    if name == ALL:
        return jobs
    return [j for j in jobs if j.get("project") and normalize(j["project"]) == name]


def snapshot(project: str, jobs: list[dict], show_items: list[dict]) -> dict:
    name = normalize(project)
    with _lock:
        focus = dict(_focus)
    return {
        "project": name, "projects": [ALL] + project_names(), "focus": focus,
        "jobs": _jobs_for(name, jobs),
        "show": [{k: it.get(k, "") for k in ("id", "title", "kind", "caption")} for it in show_items][-6:],
        "parked": parked(name), "notes": notes(name),
        "topics": topics(name), "activity": activity(), "layout": get_layout(name),
        "server_time": time.time(),
    }


# --- what Argo asked the board to do -------------------------------------

def set_focus(project: str) -> str:
    name = normalize(project)
    with _lock:
        _focus["project"], _focus["seq"] = name, _focus["seq"] + 1
    return name


def tidy(project: str) -> str:
    name = normalize(project)
    save_layout(name, {})
    with _lock:
        _focus["tidy_seq"] += 1
    return name


# --- layouts ---------------------------------------------------------------

def _load_all() -> dict:
    try:
        data = json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_layout(project: str) -> dict:
    return _load_all().get(normalize(project), {})


def _clean_layout(layout: dict) -> dict:
    clean = {}
    if not isinstance(layout, dict):
        return clean
    for card_id, spec in list(layout.items())[:40]:
        if not isinstance(spec, dict) or not re.fullmatch(r"[a-z0-9_-]{1,40}", str(card_id)):
            continue
        entry = {}
        for key, low, high in (("x", -2000, 20000), ("y", -2000, 20000), ("w", 180, 2400),
                               ("h", 90, 2400), ("z", 0, 10000)):
            try:
                entry[key] = int(max(low, min(high, float(spec.get(key)))))
            except (TypeError, ValueError):
                pass
        if spec.get("color") in COLORS:
            entry["color"] = spec["color"]
        if spec.get("collapsed") in (True, False):
            entry["collapsed"] = spec["collapsed"]
        if entry:
            clean[str(card_id)] = entry
    return clean


def save_layout(project: str, layout: dict) -> dict:
    name = normalize(project)
    clean = _clean_layout(layout)
    with _lock:
        data = _load_all()
        if clean:
            data[name] = clean
        else:
            data.pop(name, None)
        try:
            LAYOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = LAYOUT_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, LAYOUT_FILE)
        except OSError:
            pass
    return clean
