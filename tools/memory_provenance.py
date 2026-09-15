"""Show what provenance the durable store actually records. Read-only."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.memory_store import MemoryRecord, get_memory_store


def main() -> int:
    print("  MemoryRecord fields:", [f.name for f in dataclasses.fields(MemoryRecord)])
    print()
    store = get_memory_store()
    for kind in ("FACT", "PREFERENCE", "PROJECT"):
        rows = store.list_memory(kind) or []
        print(f"  {kind} rows: {len(rows)}")
        for row in rows:
            source = getattr(row, "source", None)
            created = getattr(row, "created_at", None) or getattr(row, "timestamp", None)
            print(f"    key={row.key!r} source={source!r} created={created!r}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
