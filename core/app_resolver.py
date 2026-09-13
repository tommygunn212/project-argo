"""Resolve a spoken application name to something launchable.

ARGO's own app_registry knows five apps. Asking it to open Chrome, Blender or
OrcaSlicer returned None, so "open <anything>" quietly did nothing. This widens
resolution to what is actually installed, in order of confidence:

  1. ARGO's curated registry      - keeps existing aliases and behaviour
  2. Taskbar pins                 - the apps Tommy actually uses every day
  3. Registry App Paths           - how Windows itself resolves "chrome"
  4. Start Menu shortcuts         - covers everything with a Start Menu entry
  5. PATH                         - command-line tools

Only installed applications are reachable: this resolves names against the
places Windows records installed software, never an arbitrary path typed aloud.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ARGO.AppResolver")

_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

# Spoken shorthand that does not match an installed name on its own.
SPOKEN_ALIASES = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "explorer": "File Explorer",
    "file explorer": "File Explorer",
    "task manager": "taskmgr",
    "cmd": "cmd",
    "terminal": "wt",
    "powershell": "powershell",
}


def _known_start_menus() -> list[Path]:
    """Both Start Menu roots, via the shell API so a missing env var cannot hide one."""
    roots: list[Path] = []
    try:
        import ctypes
        from ctypes import wintypes

        # FOLDERID_Programs (user) and FOLDERID_CommonPrograms (machine)
        folder_ids = [
            "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}",
            "{0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8}",
        ]
        SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
        CoTaskMemFree = ctypes.windll.ole32.CoTaskMemFree
        for guid_str in folder_ids:
            guid = ctypes.create_unicode_buffer(guid_str)
            iid = ctypes.c_byte * 16
            clsid = iid()
            if ctypes.windll.ole32.CLSIDFromString(guid, ctypes.byref(clsid)) != 0:
                continue
            out = ctypes.c_wchar_p()
            if SHGetKnownFolderPath(ctypes.byref(clsid), 0, None, ctypes.byref(out)) == 0:
                roots.append(Path(out.value))
                CoTaskMemFree(out)
    except Exception:
        logger.debug("[AppResolver] shell folder lookup unavailable", exc_info=True)

    # Env fallback, in case the shell call is unavailable in this context.
    for var, tail in (("APPDATA", r"Microsoft\Windows\Start Menu\Programs"),
                      ("PROGRAMDATA", r"Microsoft\Windows\Start Menu\Programs")):
        base = os.environ.get(var)
        if base:
            p = Path(base) / tail
            if p.is_dir() and p not in roots:
                roots.append(p)
    return [r for r in roots if r.is_dir()]


def _taskbar_index() -> dict[str, Path]:
    """Apps pinned to the taskbar - the highest-signal list of what he uses."""
    index: dict[str, Path] = {}
    base = os.environ.get("APPDATA")
    roots = []
    if base:
        roots.append(Path(base) / r"Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar")
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for lnk in root.glob("*.lnk"):
                index.setdefault(lnk.stem.lower(), lnk)
        except Exception:
            logger.debug("[AppResolver] could not read taskbar pins", exc_info=True)
    return index


def _start_menu_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for root in _known_start_menus():
        try:
            for lnk in root.rglob("*.lnk"):
                index.setdefault(lnk.stem.lower(), lnk)
        except Exception:
            logger.debug("[AppResolver] could not walk %s", root, exc_info=True)
    return index


def _registry_app_paths() -> dict[str, str]:
    """What Windows itself uses to resolve "chrome" from the Run box."""
    found: dict[str, str] = {}
    try:
        import winreg
    except ImportError:
        return found
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, _APP_PATHS_KEY) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, name) as sub:
                            target, _ = winreg.QueryValueEx(sub, "")
                        if target:
                            found.setdefault(name.lower(), target.strip('"'))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def _squash(value: str) -> str:
    """Drop spaces and punctuation so 'orca slicer' matches 'OrcaSlicer'."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def _score(said: str, candidate: str) -> int:
    """Exact beats prefix beats substring. 0 means no match.

    Compared twice: once as spoken, once with spaces and punctuation
    squashed out, because installed names run words together
    ("OrcaSlicer") while people say them apart ("orca slicer").
    """
    best = 0
    for a, b in ((said, candidate), (_squash(said), _squash(candidate))):
        if not a or not b:
            continue
        if a == b:
            score = 3
        elif b.startswith(a):
            score = 2
        elif a in b:
            score = 1
        else:
            score = 0
        best = max(best, score)
    return best


def _best(said: str, names) -> Optional[str]:
    best, best_score = None, 0
    for name in names:
        s = _score(said, name)
        # Prefer the shortest name at a given score: "chrome" should beat
        # "chrome remote desktop".
        if s > best_score:
            best, best_score = name, s
        elif s == best_score and s > 0 and best and len(name) < len(best):
            best = name
    return best if best_score else None


def resolve(spoken: str) -> Optional[dict]:
    """Resolve a spoken app name. Returns {name, target, source} or None."""
    said = (spoken or "").strip().lower()
    if not said:
        return None

    # 1) ARGO's curated registry keeps priority so existing aliases still win.
    try:
        from core.app_control import resolve_app_name

        key = resolve_app_name(spoken)
        if key:
            return {"name": key, "target": key, "source": "argo_registry"}
    except Exception:
        logger.debug("[AppResolver] argo registry unavailable", exc_info=True)

    said = SPOKEN_ALIASES.get(said, said).lower()

    # 2) Taskbar pins first: if it is on his taskbar it is what he meant.
    pinned = _taskbar_index()
    hit = _best(said, pinned.keys())
    if hit:
        return {"name": pinned[hit].stem, "target": str(pinned[hit]), "source": "taskbar"}

    # 3) App Paths - how Windows resolves a bare program name.
    app_paths = _registry_app_paths()
    for candidate in (said, f"{said}.exe"):
        if candidate in app_paths:
            return {"name": candidate, "target": app_paths[candidate], "source": "app_paths"}
    hit = _best(said, app_paths.keys())
    if hit:
        return {"name": hit, "target": app_paths[hit], "source": "app_paths"}

    # 4) Start Menu - everything with a shortcut.
    menu = _start_menu_index()
    hit = _best(said, menu.keys())
    if hit:
        return {"name": menu[hit].stem, "target": str(menu[hit]), "source": "start_menu"}

    # 5) PATH.
    which = shutil.which(said) or shutil.which(f"{said}.exe")
    if which:
        return {"name": said, "target": which, "source": "path"}

    return None


def installed_names(limit: int = 400) -> list[str]:
    """Everything ARGO could open, for "what can you launch?"."""
    names = set()
    try:
        from core.app_control import get_supported_app_displays

        names.update(get_supported_app_displays() or [])
    except Exception:
        pass
    names.update(p.stem for p in _taskbar_index().values())
    names.update(p.stem for p in _start_menu_index().values())
    names.update(k.replace(".exe", "") for k in _registry_app_paths())
    return sorted(names)[:limit]
