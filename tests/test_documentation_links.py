import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@pytest.mark.parametrize("relative_path", ["README.md", "docs/README.md"])
def test_primary_documentation_has_no_broken_local_links(relative_path):
    source = ROOT / relative_path
    broken = []
    for target in MARKDOWN_LINK.findall(source.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = target.split("#", 1)[0]
        if path_part and not (source.parent / path_part).resolve().exists():
            broken.append(target)

    assert broken == []
