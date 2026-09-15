"""Show what ARGO's durable memory already holds. Read-only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.memory_store import get_memory_store


def main() -> int:
    store = get_memory_store()
    print(f"  backend: {store.backend_name}")
    print()
    for kind in ("FACT", "PREFERENCE", "PROJECT"):
        try:
            rows = store.list_memory(kind)
        except Exception as exc:
            print(f"  {kind:11} error: {exc}")
            continue
        print(f"  {kind:11} count={len(rows)}")
        for row in rows[:8]:
            print(f"      {row.key} = {str(row.value)[:70]}")
    print()
    for probe in ("argo", "voice", "tommy"):
        try:
            turns = store.search_turns(probe, limit=3)
        except Exception as exc:
            print(f"  search_turns({probe!r}) error: {exc}")
            continue
        print(f"  search_turns({probe!r}) -> {len(turns)} row(s)")
        for turn in turns[:2]:
            print(f"      U: {str(turn.user_text)[:64]}")
            print(f"      A: {str(turn.assistant_text)[:64]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
