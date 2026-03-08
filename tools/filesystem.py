"""
ARGO File System Agent — "Let ARGO organize and search your drives."

Search for files by name/type/date, analyze disk usage, find large files,
show recent downloads, and get file info — all via voice.
"""

import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("argo.tools.filesystem")

# Sensible default search roots (Windows)
DEFAULT_SEARCH_ROOTS = ["C:\\Users", "D:\\", "E:\\"]

# Extensions by category for natural-language queries
CATEGORY_EXTENSIONS = {
    "document":   {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".pages"},
    "image":      {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".ico"},
    "video":      {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "audio":      {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "spreadsheet": {".xlsx", ".xls", ".csv", ".ods"},
    "presentation": {".pptx", ".ppt", ".odp", ".key"},
    "code":       {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".rb", ".html", ".css"},
    "archive":    {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "executable": {".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh"},
}


# ---------------------------------------------------------------------------
# File search
# ---------------------------------------------------------------------------

def search_files(
    query: str,
    roots: Optional[list] = None,
    extensions: Optional[set] = None,
    max_results: int = 20,
    max_depth: int = 8,
    max_scan_seconds: float = 15.0,
) -> list[dict]:
    """Search for files matching a name query across specified roots.

    Returns list of dicts: {"path", "name", "size", "modified"}
    """
    if roots is None:
        roots = _get_search_roots()

    results = []
    query_lower = query.lower()
    start = time.time()

    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Depth limit
            depth = dirpath.replace(root, "").count(os.sep)
            if depth >= max_depth:
                dirnames.clear()
                continue

            # Skip hidden/system directories
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {
                "$Recycle.Bin", "System Volume Information", "Windows",
                "node_modules", "__pycache__", ".git", ".venv", "venv",
            }]

            # Time limit
            if time.time() - start > max_scan_seconds:
                logger.info(f"[FILESYSTEM] Search time limit reached ({max_scan_seconds}s)")
                return results

            for fname in filenames:
                if query_lower in fname.lower():
                    if extensions and not any(fname.lower().endswith(ext) for ext in extensions):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        stat = os.stat(fpath)
                        results.append({
                            "path": fpath,
                            "name": fname,
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        })
                    except (OSError, PermissionError):
                        pass
                    if len(results) >= max_results:
                        return results
    return results


def search_by_extension(
    extensions: set,
    roots: Optional[list] = None,
    max_results: int = 20,
    max_depth: int = 6,
    modified_after: Optional[datetime] = None,
    max_scan_seconds: float = 15.0,
) -> list[dict]:
    """Search for files by extension, optionally filtered by modification date."""
    if roots is None:
        roots = _get_search_roots()

    results = []
    start = time.time()

    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath.replace(root, "").count(os.sep)
            if depth >= max_depth:
                dirnames.clear()
                continue

            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {
                "$Recycle.Bin", "System Volume Information", "Windows",
                "node_modules", "__pycache__", ".git", ".venv", "venv",
            }]

            if time.time() - start > max_scan_seconds:
                return results

            for fname in filenames:
                if any(fname.lower().endswith(ext) for ext in extensions):
                    fpath = os.path.join(dirpath, fname)
                    try:
                        stat = os.stat(fpath)
                        mtime = datetime.fromtimestamp(stat.st_mtime)
                        if modified_after and mtime < modified_after:
                            continue
                        results.append({
                            "path": fpath,
                            "name": fname,
                            "size": stat.st_size,
                            "modified": mtime.isoformat(),
                        })
                    except (OSError, PermissionError):
                        pass
                    if len(results) >= max_results:
                        return results
    return results


# ---------------------------------------------------------------------------
# Large file finder
# ---------------------------------------------------------------------------

def find_large_files(
    root: str,
    min_size_mb: float = 100,
    max_results: int = 15,
    max_depth: int = 6,
    max_scan_seconds: float = 15.0,
) -> list[dict]:
    """Find files larger than min_size_mb under a root path."""
    results = []
    min_bytes = int(min_size_mb * 1024 * 1024)
    start = time.time()

    if not os.path.isdir(root):
        return results

    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.replace(root, "").count(os.sep)
        if depth >= max_depth:
            dirnames.clear()
            continue

        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {
            "$Recycle.Bin", "System Volume Information", "Windows",
            "node_modules", "__pycache__", ".git",
        }]

        if time.time() - start > max_scan_seconds:
            break

        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                stat = os.stat(fpath)
                if stat.st_size >= min_bytes:
                    results.append({
                        "path": fpath,
                        "name": fname,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
            except (OSError, PermissionError):
                pass

    results.sort(key=lambda f: f["size"], reverse=True)
    return results[:max_results]


# ---------------------------------------------------------------------------
# Recent files (downloads, etc.)
# ---------------------------------------------------------------------------

def find_recent_files(
    directory: Optional[str] = None,
    hours: int = 24,
    max_results: int = 15,
) -> list[dict]:
    """Find files modified within the last N hours in a directory."""
    if directory is None:
        directory = str(Path.home() / "Downloads")

    if not os.path.isdir(directory):
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    results = []

    for entry in os.scandir(directory):
        if entry.is_file():
            try:
                stat = entry.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)
                if mtime >= cutoff:
                    results.append({
                        "path": entry.path,
                        "name": entry.name,
                        "size": stat.st_size,
                        "modified": mtime.isoformat(),
                    })
            except (OSError, PermissionError):
                pass

    results.sort(key=lambda f: f["modified"], reverse=True)
    return results[:max_results]


# ---------------------------------------------------------------------------
# File / directory info
# ---------------------------------------------------------------------------

def get_file_info(path: str) -> dict:
    """Get detailed info about a file or directory."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return {"error": f"Path not found: {path}"}

    stat = os.stat(path)
    info = {
        "path": os.path.abspath(path),
        "name": os.path.basename(path),
        "is_directory": os.path.isdir(path),
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
    }
    if os.path.isdir(path):
        try:
            entries = list(os.scandir(path))
            info["file_count"] = sum(1 for e in entries if e.is_file())
            info["folder_count"] = sum(1 for e in entries if e.is_dir())
        except PermissionError:
            info["file_count"] = -1
            info["folder_count"] = -1
    return info


def get_directory_size(path: str, max_scan_seconds: float = 10.0) -> dict:
    """Calculate total size of a directory."""
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}

    total = 0
    file_count = 0
    start = time.time()

    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {
            "$Recycle.Bin", "System Volume Information",
        }]
        if time.time() - start > max_scan_seconds:
            return {"path": path, "size": total, "file_count": file_count, "truncated": True}

        for fname in filenames:
            try:
                total += os.stat(os.path.join(dirpath, fname)).st_size
                file_count += 1
            except (OSError, PermissionError):
                pass

    return {"path": path, "size": total, "file_count": file_count, "truncated": False}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _human_size(nbytes: int) -> str:
    """Convert bytes to human-readable string."""
    if nbytes < 0:
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def format_file_list_for_speech(files: list[dict], label: str = "files") -> str:
    """Format a file list into a speakable summary."""
    if not files:
        return f"No {label} found."

    count = len(files)
    summary = f"Found {count} {label}. "

    # Speak the first 5
    spoken = []
    for f in files[:5]:
        name = f["name"]
        size = _human_size(f.get("size", 0))
        spoken.append(f"{name}, {size}")

    summary += ". ".join(spoken)
    if count > 5:
        summary += f". Plus {count - 5} more."
    return summary


def format_file_info_for_speech(info: dict) -> str:
    """Format file/directory info for speech."""
    if "error" in info:
        return info["error"]

    name = info["name"]
    if info["is_directory"]:
        fc = info.get("file_count", 0)
        dc = info.get("folder_count", 0)
        size_info = ""
        if "size" in info:
            size_info = f", total size {_human_size(info['size'])}"
        return f"{name} is a folder with {fc} files and {dc} subfolders{size_info}."
    else:
        size = _human_size(info["size"])
        mod = info.get("modified", "unknown")
        return f"{name} is {size}, last modified {mod}."


# ---------------------------------------------------------------------------
# Smart search root detection
# ---------------------------------------------------------------------------

def _get_search_roots() -> list[str]:
    """Detect available drive roots on Windows, fall back to home."""
    roots = []
    home = str(Path.home())
    if os.name == "nt":
        # Check common drive letters
        for letter in "CDEFGHIJ":
            drive = f"{letter}:\\"
            if os.path.isdir(drive):
                if letter == "C":
                    roots.append(home)  # Don't scan entire C:, just user home
                else:
                    roots.append(drive)
    else:
        roots.append(home)

    if not roots:
        roots.append(home)
    return roots


# ---------------------------------------------------------------------------
# Voice command parser
# ---------------------------------------------------------------------------

def parse_filesystem_command(text: str) -> dict:
    """Parse a filesystem voice command into structured action.

    Returns:
        {"action": "search"|"large_files"|"recent"|"info"|"size",
         "query": str, "drive": str|None, "extensions": set|None,
         "hours": int|None, "min_size_mb": float|None}
    """
    lower = text.lower()
    result = {
        "action": "search",
        "query": "",
        "drive": None,
        "extensions": None,
        "hours": None,
        "min_size_mb": None,
    }

    # Extract drive letter
    drive_match = re.search(r"\b([a-z])\s*(?:drive|:)", lower)
    if drive_match:
        result["drive"] = drive_match.group(1).upper() + ":\\"

    # Detect file category
    for category, exts in CATEGORY_EXTENSIONS.items():
        pattern = category.replace("_", " ")
        if re.search(r"\b" + re.escape(pattern) + r"s?\b", lower):
            result["extensions"] = exts
            break

    # Specific extension mention
    ext_match = re.search(r"\b(pdf|doc|docx|txt|xlsx|csv|mp3|mp4|jpg|png|zip|exe|py)\b", lower)
    if ext_match:
        ext = "." + ext_match.group(1)
        result["extensions"] = {ext}

    # Action: large files
    if re.search(r"\b(large|larger|big|bigger|huge|biggest|largest)\b.*\bfiles?\b", lower) or \
       re.search(r"\bfiles?\b.*\b(large|larger|big|bigger|huge|biggest|largest|taking\s+space)\b", lower):
        result["action"] = "large_files"
        size_match = re.search(r"(\d+)\s*(?:mb|megabyte|gig|gb)", lower)
        if size_match:
            val = int(size_match.group(1))
            if re.search(r"gig|gb", lower):
                val *= 1024
            result["min_size_mb"] = float(val)
        else:
            result["min_size_mb"] = 100.0
        return result

    # Action: recent files / downloads
    if re.search(r"\b(recent|latest|new|today|downloaded)\b.*\b(files?|downloads?)\b", lower) or \
       re.search(r"\bdownloads?\b.*\b(today|recent|latest|new)\b", lower) or \
       re.search(r"\bwhat\b.*\bdownload", lower):
        result["action"] = "recent"
        hours_match = re.search(r"(\d+)\s*hours?", lower)
        if hours_match:
            result["hours"] = int(hours_match.group(1))
        elif "today" in lower:
            result["hours"] = 24
        elif "week" in lower:
            result["hours"] = 168
        else:
            result["hours"] = 24
        return result

    # Action: directory size
    if re.search(r"\b(size|how\s+big|space)\b.*\b(folder|directory|drive)\b", lower) or \
       re.search(r"\b(folder|directory)\b.*\b(size|how\s+big|space)\b", lower):
        result["action"] = "size"
        # Try to extract a path
        path_match = re.search(r'(?:of|for)\s+"?([^"]+)"?', lower)
        if path_match:
            result["query"] = path_match.group(1).strip()
        return result

    # Action: file info
    if re.search(r"\b(info|details?|about|properties)\b.*\bfile\b", lower):
        result["action"] = "info"
        path_match = re.search(r'(?:about|for|called|named)\s+"?([^"]+)"?', lower)
        if path_match:
            result["query"] = path_match.group(1).strip()
        return result

    # Default: extract search query
    # Remove common preamble words
    query = re.sub(
        r"^.*?\b(?:find|search|look\s+for|locate|where(?:'s| is| are)?)\s+(?:my\s+|the\s+|a\s+)?",
        "", lower,
    ).strip()
    # Remove trailing filler
    query = re.sub(r"\s+(?:files?|on\s+\w+\s+drive|please|for\s+me)\s*$", "", query).strip()
    if not query:
        query = text  # fallback
    result["query"] = query

    return result
