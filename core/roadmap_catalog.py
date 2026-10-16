"""Read documented ARGO plans without treating old notes as runtime truth."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "AGENTS.md",
    "docs/TODO.md",
    "docs/ARGO_NEXT_UPGRADES.md",
    "docs/specs/master-feature-list.md",
)


def _items(root: Path):
    for source in SOURCES:
        path = root / source
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        in_open_work = False
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if source == "AGENTS.md":
                if stripped == "## Open work":
                    in_open_work = True
                elif in_open_work and stripped.startswith("## "):
                    in_open_work = False
                if in_open_work and stripped.startswith("- "):
                    yield {"title": stripped[2:][:300], "source": source, "line": number,
                           "kind": "open work"}
            elif source == "docs/TODO.md" and stripped.startswith("- [ ] "):
                yield {"title": stripped[6:][:300], "source": source, "line": number,
                       "kind": "open work"}
            elif source == "docs/ARGO_NEXT_UPGRADES.md" and re.match(r"^## \d+\. ", stripped):
                yield {"title": stripped[3:][:300], "source": source, "line": number,
                       "kind": "upgrade note"}
            elif source == "docs/specs/master-feature-list.md" and re.match(r"^\d+\. ", stripped):
                yield {"title": stripped[:300], "source": source, "line": number,
                       "kind": "planned capability"}


def search_argo_roadmap(query: str = "", limit: int = 12, *, root: Path = ROOT) -> dict:
    """Return bounded source-linked matches; an entry is never proof of status."""
    query = str(query or "").strip()[:200]
    tokens = re.findall(r"[\w-]+", query.casefold())
    limit = max(1, min(int(limit), 30))
    matches = []
    for item in _items(Path(root)):
        if not tokens and item["kind"] == "planned capability":
            continue  # The 200-item scope list would bury immediate work.
        if tokens and not all(token in item["title"].casefold() for token in tokens):
            continue
        matches.append(item)
        if len(matches) >= limit:
            break
    return {"ok": True, "query": query, "items": matches,
            "note": "These are documented plans, not proof that an item is still missing or complete. Inspect current code before implementation."}
