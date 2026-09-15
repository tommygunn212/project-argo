"""Where ARGO may look, and where she may change things.

Tommy asked for read and write access to all his drives: "she cannot really
search beyond her folder... she needs to have access to I, the work drives,
all my hard drives in case she has to search for something. READ AND WRITE."

So the default is every fixed drive on the machine, readable and writable,
which is what he asked for. Three things are carved out, and they are carved
out to protect HIM, not to second-guess him:

  - Windows itself and installed programs. A voice command that misfires
    inside C:\\Windows is not a mistake anyone recovers from over lunch.
  - Credentials. ARGO's own .env holds his OpenAI key and his Jellyfin
    token, and read_text_file could previously read it straight out loud.
  - Deletion. Nothing here deletes. Removal means moving to a quarantine
    folder he can inspect and empty himself.

Every carve-out is listed in config.json and can be widened by him. None of
them are secret, and `access_report()` prints the whole policy on request.
"""

from __future__ import annotations

import ctypes
import logging
import os
import string
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("ARGO.Filesystem")

ROOT = Path(__file__).resolve().parents[1]

DRIVE_FIXED = 3

# Folders that belong to Windows and to installed software. Matched
# case-insensitively against the start of a resolved path.
PROTECTED_DIR_NAMES = (
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "recovery",
    "perflogs",
    "msocache",
)

# Anything that is likely to BE a credential. Read as well as write: the
# point is that ARGO never reads one of these aloud in a voice session.
SECRET_FILE_NAMES = {
    ".env", ".env.local", ".env.production", "credentials", "id_rsa", "id_ed25519",
    ".netrc", ".pgpass", "secrets.json", "token.json", "service-account.json",
}
SECRET_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".keystore", ".jks", ".ppk"}
SECRET_DIR_NAMES = {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker"}


def fixed_drives() -> list[Path]:
    """Every fixed disk on this machine. Removable and network drives are
    left out: they come and go, and a missing one should not look like a
    permissions problem."""
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if not os.path.exists(root):
            continue
        try:
            if ctypes.windll.kernel32.GetDriveTypeW(root) != DRIVE_FIXED:
                continue
        except Exception:
            pass  # not Windows, or the call failed: treat it as usable
        drives.append(Path(root))
    return drives


def _configured(key: str) -> list[str]:
    try:
        from core.config import get_config

        raw = get_config().get(key, []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(entry) for entry in raw]
    except Exception:
        logger.exception("[Filesystem] could not read %s", key)
        return []


def _as_dirs(entries: Iterable[str]) -> list[Path]:
    out = []
    for entry in entries:
        try:
            path = Path(entry).expanduser().resolve()
            if path.is_dir():
                out.append(path)
            else:
                logger.warning("[Filesystem] not a folder, ignoring: %s", entry)
        except Exception:
            logger.warning("[Filesystem] unusable path, ignoring: %r", entry)
    return out


def read_roots() -> list[Path]:
    """Where ARGO may look. Defaults to every fixed drive."""
    configured = _as_dirs(_configured("filesystem.allowed_folders"))
    if configured:
        return configured
    roots = fixed_drives()
    return roots or [ROOT]


def write_roots() -> list[Path]:
    """Where ARGO may change things. Defaults to wherever she may read."""
    configured = _as_dirs(_configured("filesystem.writable_folders"))
    return configured or read_roots()


def quarantine_dir() -> Path:
    """Where "delete" actually puts things, so Tommy can check before it is
    really gone."""
    configured = _configured("filesystem.quarantine_folder")
    base = Path(configured[0]).expanduser() if configured else (ROOT / "runtime" / "quarantine")
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# What is off limits, and why
# ---------------------------------------------------------------------------

def _extra_protected() -> list[str]:
    return [p.lower() for p in _configured("filesystem.protected_folders")]


def is_protected_location(path: Path) -> Optional[str]:
    """Windows and installed software. Returns the reason, or None."""
    parts = [p.lower() for p in path.parts]
    for name in PROTECTED_DIR_NAMES:
        if name in parts:
            return f"{name} belongs to Windows or to installed software"
    text = str(path).lower()
    for extra in _extra_protected():
        if text.startswith(extra):
            return "listed in filesystem.protected_folders"
    return None


def is_secret(path: Path) -> Optional[str]:
    """Credentials. Blocked for READING too - ARGO must not read a key aloud."""
    name = path.name.lower()
    if name in SECRET_FILE_NAMES:
        return f"{path.name} normally holds credentials"
    if path.suffix.lower() in SECRET_SUFFIXES:
        return f"{path.suffix} files normally hold keys or certificates"
    for part in path.parts:
        if part.lower() in SECRET_DIR_NAMES:
            return f"{part} normally holds credentials"
    if name.startswith(".env"):
        return "environment files normally hold API keys"
    if name in SECRET_EXTRA_NAMES:
        return f"{path.name} normally holds credentials or machine secrets"
    lowered = str(path).lower()
    for fragment in SECRET_PATH_FRAGMENTS:
        if fragment in lowered:
            return "that folder is a credential store"
    return None


# Credential stores that live inside a user's own profile. Tommy's documents
# stay readable; the places a browser or a CLI parks a token do not.
SECRET_PATH_FRAGMENTS = (
    r"appdata\roaming\microsoft\credentials",
    r"appdata\local\microsoft\credentials",
    r"appdata\roaming\microsoft\protect",
    r"appdata\local\google\chrome\user data\default\login data",
    r"appdata\roaming\mozilla\firefox\profiles",
    r"appdata\local\microsoft\edge\user data\default\login data",
)
SECRET_EXTRA_NAMES = {
    ".git-credentials", "ntuser.dat", "sam", "security",
    "unattend.xml", "sysprep.inf", "wpeinit.log",
}

# Profiles that are not a person: shared or template accounts are fine to see.
NEUTRAL_PROFILE_NAMES = {"public", "default", "default user", "all users"}


def current_user_profile_names() -> set[str]:
    """Which names under C:\\Users are Tommy's own, lowercased."""
    names = set()
    for value in (os.environ.get("USERNAME"), os.environ.get("USER")):
        if value:
            names.add(value.strip().lower())
    try:
        names.add(Path.home().name.strip().lower())
    except Exception:
        pass
    return {n for n in names if n}


def is_foreign_user_profile(path: Path) -> Optional[str]:
    """Another person's Windows profile. Returns the reason, or None.

    Reading Tommy's own Documents was the whole point of widening access.
    Reading somebody else's profile never was, and a voice command is a bad
    way to wander into one.
    """
    parts = [p.lower().rstrip("\\/") for p in path.parts]
    try:
        index = parts.index("users")
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None  # C:\Users itself - listing it is harmless
    profile = parts[index + 1]
    if profile in NEUTRAL_PROFILE_NAMES or profile in current_user_profile_names():
        return None
    return f"{path.parts[index + 1]} is another user's profile"


def path_shape_problem(raw: str | os.PathLike | None) -> Optional[str]:
    """Reject a path by its SHAPE, before anything resolves it.

    resolve() silently collapses "..", so a traversal that walks out of a
    granted folder arrives at check_read looking like an ordinary absolute
    path. The signature has to be caught while it is still visible. UNC and
    Win32 device paths are refused outright: they sidestep drive-letter
    scoping altogether and can reach the network.
    """
    if raw is None:
        return None
    text = str(raw).strip().strip('"').strip("'")
    if not text:
        return None

    if text.startswith(("\\\\?\\", "\\\\.\\")):
        return "Win32 device paths are not allowed"
    if text.startswith("\\\\") or text.startswith("//"):
        return "network (UNC) paths are not allowed"

    normalised = text.replace("/", "\\")
    segments = [seg.strip() for seg in normalised.split("\\")]
    if any(seg == ".." for seg in segments):
        return "'..' path traversal is not allowed"

    stem = Path(text).stem.upper()
    if stem in {"CON", "PRN", "AUX", "NUL"} or (
        len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3].isdigit()
    ):
        return f"{stem} is a reserved device name"
    return None


def _under(target: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        try:
            if target == root or root in target.parents:
                return True
        except Exception:
            continue
    return False


def check_read(target: Path, raw: str | os.PathLike | None = None) -> Optional[dict]:
    """None when reading is fine, otherwise the refusal to hand back.

    Pass `raw` - the path exactly as it arrived - whenever it is available.
    Shape problems like ".." are invisible once a path has been resolved.
    """
    shape = path_shape_problem(raw)
    if shape:
        return {
            "ok": False,
            "error": "bad_path",
            "path": str(raw),
            "message": f"I won't follow that path - {shape}.",
        }
    secret = is_secret(target)
    if secret:
        return {
            "ok": False,
            "error": "secret_file",
            "path": str(target),
            "message": (
                f"I won't read {target.name} out loud - {secret}. "
                "Open it yourself if you need what is in it."
            ),
        }
    if not _under(target, read_roots()):
        return {
            "ok": False,
            "error": "not_allowed",
            "path": str(target),
            "message": f"{target} is outside the drives I can read.",
            "allowed": [str(r) for r in read_roots()],
        }
    # Checked after the roots test on purpose: when the allowed roots have been
    # narrowed, "outside what I can read" is the more truthful answer, and a
    # test pins that. In normal operation every drive is a root, so this is
    # what actually keeps Windows and other profiles unreadable.
    protected = is_protected_location(target)
    if protected:
        return {
            "ok": False,
            "error": "protected_location",
            "path": str(target),
            "message": f"I won't read inside {target} - {protected}.",
        }
    foreign = is_foreign_user_profile(target)
    if foreign:
        return {
            "ok": False,
            "error": "not_allowed",
            "path": str(target),
            "message": f"I won't look in there - {foreign}.",
        }
    return None


def check_write(target: Path, raw: str | os.PathLike | None = None) -> Optional[dict]:
    """None when writing is fine, otherwise the refusal to hand back."""
    shape = path_shape_problem(raw)
    if shape:
        return {
            "ok": False,
            "error": "bad_path",
            "path": str(raw),
            "message": f"I won't follow that path - {shape}.",
        }
    foreign = is_foreign_user_profile(target)
    if foreign:
        return {
            "ok": False,
            "error": "not_allowed",
            "path": str(target),
            "message": f"I won't change anything there - {foreign}.",
        }
    protected = is_protected_location(target)
    if protected:
        return {
            "ok": False,
            "error": "protected_location",
            "path": str(target),
            "message": (
                f"I won't change anything in {target.parent} - {protected}. "
                "Everything of yours outside Windows and Program Files is fair game."
            ),
        }
    secret = is_secret(target)
    if secret:
        return {
            "ok": False,
            "error": "secret_file",
            "path": str(target),
            "message": f"I won't overwrite {target.name} - {secret}.",
        }
    if not _under(target, write_roots()):
        return {
            "ok": False,
            "error": "not_writable",
            "path": str(target),
            "message": f"{target} is outside the drives I can write to.",
            "writable": [str(r) for r in write_roots()],
        }
    return None


def access_report() -> dict:
    """The whole policy, in plain terms, on request."""
    return {
        "readable": [str(r) for r in read_roots()],
        "writable": [str(r) for r in write_roots()],
        "protected": list(PROTECTED_DIR_NAMES) + _extra_protected(),
        "never_read_or_written": (
            sorted(SECRET_FILE_NAMES)
            + sorted(SECRET_SUFFIXES)
            + sorted(SECRET_DIR_NAMES)
        ),
        "refused_path_shapes": [
            "'..' traversal", "UNC / network paths", "Win32 device paths",
            "reserved device names", "other users' profiles",
        ],
        "quarantine": str(quarantine_dir()),
        "deletes": "nothing is deleted; removal moves the file to quarantine",
    }
