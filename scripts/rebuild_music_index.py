"""Rebuild local JSON music index from disk.

Usage:
    I:/argo/.venv/Scripts/python.exe scripts/rebuild_music_index.py
"""

import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path for core imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.music_index import get_music_index


def main() -> None:
    index_path = os.getenv("MUSIC_INDEX_FILE", "data/music_index.json")
    if os.path.exists(index_path):
        os.remove(index_path)
        print(f"Deleted existing index: {index_path}")

    idx = get_music_index()
    print(f"Index tracks: {len(idx.tracks)}")
    print(f"Index file: {index_path}")


if __name__ == "__main__":
    main()
