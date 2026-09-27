"""Reading, finding and writing files - allowlisted, and never deleting.

Reads default to every fixed drive; writes refuse Windows, installed software
and credential files (core.filesystem_access holds the policy). Nothing here
deletes: removal moves the item to a dated quarantine folder Tommy empties
himself. Relative paths mean "inside the ARGO install".
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from core.realtime_tools._base import capability, ROOT

__all__ = [
    "LIST_CAP",
    "PathRefused",
    "list_folder",
    "read_text_file",
    "find_files",
    "file_access_report",
    "write_text_file",
    "append_text_file",
    "create_folder",
    "move_item",
    "copy_item",
    "remove_item",
]


# Names returned by a folder listing before it is truncated. A silently short
# alphabetical list makes the model report that a file is absent when it is
# merely past the cut-off, so truncation is always reported.
LIST_CAP = 200


class PathRefused(Exception):
    """A path was rejected on its shape, before anything touched the disk.

    resolve() collapses "..", so by the time a traversal reaches check_read it
    looks like an ordinary absolute path. _resolve is the last place the
    original shape is still visible, so the refusal is raised from here and
    each tool turns it into an ordinary ok:false result.
    """

    def __init__(self, refusal: dict) -> None:
        super().__init__(refusal.get("message", "path refused"))
        self.refusal = refusal


def _refuse_bad_shape(raw: str) -> None:
    from core.filesystem_access import path_shape_problem

    problem = path_shape_problem(raw)
    if problem:
        raise PathRefused({
            "ok": False,
            "error": "bad_path",
            "path": str(raw),
            "message": f"I won't follow that path - {problem}.",
        })


def _resolve(raw: str) -> Path:
    """Interpret a spoken path. Empty or relative means inside the ARGO install.

    The shape check runs on ``raw`` exactly as it arrived, because resolve()
    hides a ".." traversal. Raises PathRefused, which @capability turns into
    an ordinary ok:false result.
    """
    _refuse_bad_shape(raw)
    text = (raw or "").strip().strip('"').strip("'")
    candidate = Path(text).expanduser() if text else ROOT
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def _quarantine(target: Path) -> Path:
    """Move ``target`` into the dated quarantine folder and return where it went.

    Every name is unique: two removals of the same name within one second
    used to share a destination, and shutil.move onto an existing folder
    nests the second item inside the first.
    """
    from core.filesystem_access import quarantine_dir

    folder = quarantine_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = folder / f"{stamp}_{target.name}"
    copy = 2
    while destination.exists():
        destination = folder / f"{stamp}-{copy}_{target.name}"
        copy += 1
    shutil.move(str(target), str(destination))
    return destination


@capability
def list_folder(path: str = "") -> dict:
    """List a folder ARGO is allowed to read.

    "" or a relative path means inside the ARGO install. An absolute path must
    fall inside a granted folder.
    """
    from core.filesystem_access import check_read

    target = _resolve(path)
    refusal = check_read(target, path)
    if refusal:
        return refusal
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


@capability
def read_text_file(path: str, max_chars: int = 4000) -> dict:
    """Read a text file inside an allowed folder."""
    from core.filesystem_access import check_read

    target = _resolve(path)
    refusal = check_read(target, path)
    if refusal:
        return refusal
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


@capability
def find_files(query: str, want: str = "any", limit: int = 25) -> dict:
    """Search every drive for a file or folder by name.

    want is any, file or folder. Folders matter as much as files here: most
    of what Tommy asks for by name - "my vzbot build", "the davinci assets" -
    is a folder, and the old search matched filenames only.
    """
    from core.file_search import search

    return search(query, limit=limit, want=want)


@capability
def file_access_report() -> dict:
    """Which drives ARGO can read and write, and what is off limits."""
    from core.filesystem_access import access_report

    report = access_report()
    report["ok"] = True
    report["message"] = (
        f"I can read {len(report['readable'])} locations and write to "
        f"{len(report['writable'])}. Windows, installed programs and anything "
        "that looks like a credential are off limits, and I never delete - "
        "removal moves things to quarantine."
    )
    return report


@capability
def write_text_file(path: str, content: str, overwrite: bool = False) -> dict:
    """Write a text file. Refuses to clobber an existing file unless told to."""
    from core.filesystem_access import check_write

    target = _resolve(path)
    refusal = check_write(target)
    if refusal:
        return refusal

    existed = target.exists()
    if existed and not overwrite:
        return {
            "ok": False,
            "error": "exists",
            "path": str(target),
            "message": (
                f"{target.name} already exists. Say overwrite if you want me to "
                "replace it."
            ),
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target and swap, so an interrupted write cannot
    # leave a half-file where a good one used to be.
    staging = target.with_name(target.name + ".argo-tmp")
    staging.write_text(content or "", encoding="utf-8")
    staging.replace(target)

    return {"ok": True, "path": str(target), "characters": len(content or ""),
            "replaced": existed,
            "message": f"{'Replaced' if existed else 'Wrote'} {target.name}."}


@capability
def append_text_file(path: str, content: str) -> dict:
    """Add to the end of a text file, creating it if it is not there."""
    from core.filesystem_access import check_write

    target = _resolve(path)
    refusal = check_write(target)
    if refusal:
        return refusal

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(content or "")
    return {"ok": True, "path": str(target), "added": len(content or ""),
            "message": f"Added to {target.name}."}


@capability
def create_folder(path: str) -> dict:
    """Make a folder, including any parents."""
    from core.filesystem_access import check_write

    target = _resolve(path)
    refusal = check_write(target)
    if refusal:
        return refusal
    existed = target.is_dir()
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(target), "already_existed": existed,
            "message": f"{'That folder already exists' if existed else 'Created ' + target.name}."}


@capability
def move_item(source: str, destination: str, overwrite: bool = False) -> dict:
    """Move or rename a file or folder. Both ends must be writable."""
    from core.filesystem_access import check_read, check_write

    src = _resolve(source)
    dst = _resolve(destination)

    for check, target in ((check_read, src), (check_write, src), (check_write, dst)):
        refusal = check(target)
        if refusal:
            return refusal

    if not src.exists():
        return {"ok": False, "error": "not_found", "path": str(src),
                "message": f"There is nothing at {src}."}
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists() and not overwrite:
        return {"ok": False, "error": "exists", "path": str(dst),
                "message": f"{dst.name} is already there. Say overwrite to replace it."}

    # Overwriting never destroys: whatever was at the destination goes to
    # quarantine first. (shutil.move onto an existing file also fails
    # outright on Windows, so overwrite=True never worked there.)
    replaced = _quarantine(dst) if dst.exists() else None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    result = {"ok": True, "from": str(src), "to": str(dst),
              "message": f"Moved {src.name} to {dst.parent}."}
    if replaced is not None:
        result["replaced_moved_to"] = str(replaced)
        result["message"] += f" The {dst.name} that was there is in quarantine, not deleted."
    return result


@capability
def copy_item(source: str, destination: str, overwrite: bool = False) -> dict:
    """Copy a file or folder."""
    from core.filesystem_access import check_read, check_write

    src = _resolve(source)
    dst = _resolve(destination)

    refusal = check_read(src) or check_write(dst)
    if refusal:
        return refusal
    if not src.exists():
        return {"ok": False, "error": "not_found", "path": str(src),
                "message": f"There is nothing at {src}."}
    if dst.is_dir() and src.is_file():
        dst = dst / src.name
    if dst.exists() and not overwrite:
        return {"ok": False, "error": "exists", "path": str(dst),
                "message": f"{dst.name} is already there. Say overwrite to replace it."}

    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=overwrite)
    else:
        shutil.copy2(src, dst)
    return {"ok": True, "from": str(src), "to": str(dst),
            "message": f"Copied {src.name} to {dst.parent}."}


@capability
def remove_item(path: str) -> dict:
    """Move something to quarantine. Nothing is ever really deleted here.

    A voice command is a bad way to lose a file permanently, so removal is
    reversible by design: everything lands in a dated quarantine folder that
    Tommy empties himself.
    """
    from core.filesystem_access import check_write

    target = _resolve(path)
    refusal = check_write(target)
    if refusal:
        return refusal
    if not target.exists():
        return {"ok": False, "error": "not_found", "path": str(target),
                "message": f"There is nothing at {target}."}

    destination = _quarantine(target)
    return {
        "ok": True,
        "moved_to": str(destination),
        "original": str(target),
        "message": (
            f"{target.name} is in quarantine, not deleted. It is at "
            f"{destination} until you empty that folder."
        ),
    }
