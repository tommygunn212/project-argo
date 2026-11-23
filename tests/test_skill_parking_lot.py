import asyncio
import json
from pathlib import Path

import pytest

from argo_skills import parking_lot as parking


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def lot(tmp_path, monkeypatch):
    monkeypatch.setattr(parking, "PARKING_ROOT", tmp_path / "projects")
    monkeypatch.setattr(parking, "RESULTS_FILE", tmp_path / "last_model_results.json")
    return tmp_path


@pytest.mark.parametrize("alias,expected", [
    ("chefs byte", "ChefsByte"), ("cooking school", "ChefsByte"),
    ("bambu", "H2D Workbench"), ("msud", "MSUDBytes"),
    ("pku", "PKUBytes"), ("argo", "Argo"), ("video", "YouTube"),
    ("family tree", "Archives"), ("", "Inbox"),
])
def test_aliases_and_traversal(lot, alias, expected):
    assert expected in run(parking.park_idea(alias, "A", "Text"))
    assert (parking.PARKING_ROOT / expected / "ideas").is_dir()
    run(parking.park_idea("../x", "Traversal", "Text"))
    assert (parking.PARKING_ROOT / "X" / "ideas").is_dir()
    assert not (lot / "x").exists()


def test_duplicates_index_and_kind(lot):
    run(parking.park_idea("h2d", "Same title", "First", why="Reason"))
    run(parking.park_idea("h2d", "Same title", "Second"))
    run(parking.park_idea("h2d", "Chosen", "Third", kind="decision"))
    folder = parking.PARKING_ROOT / "H2D Workbench"
    files = sorted((folder / "ideas").glob("*.md"))
    assert len(files) == 2 and any(p.stem.endswith("-2") for p in files)
    assert any('why: "Reason"' in p.read_text(encoding="utf-8") for p in files)
    index = (folder / "index.md").read_text(encoding="utf-8")
    assert index.count("[Same title]") == 2
    assert index.index("[Chosen]") < index.index("[Same title]")
    assert "decisions/" in index and "ideas/" in index
    assert "choose" in run(parking.park_idea("h2d", "No", "No", "invalid")).lower()


@pytest.mark.parametrize("data", [
    [{"id": "thing-1", "url": "https://example.test/a"}],
    {"results": [{"model_id": "thing-1", "page_url": "https://example.test/a", "title": "Useful model", "creator": "Maker"}]},
])
def test_save_pick_shapes_and_bounds(lot, data):
    assert "no saved" in run(parking.save_pick(1, "h2d")).lower()
    parking.RESULTS_FILE.write_text(json.dumps(data), encoding="utf-8")
    assert "out of range" in run(parking.save_pick(0, "h2d")).lower()
    assert "out of range" in run(parking.save_pick(2, "h2d")).lower()
    assert "H2D Workbench" in run(parking.save_pick(1, "h2d", "looks useful"))
    run(parking.save_pick(1, "h2d"))
    folder = parking.PARKING_ROOT / "H2D Workbench"
    files = list((folder / "finds").glob("*.md"))
    assert len(files) == 2
    assert any("https://example.test/a" in p.read_text(encoding="utf-8") and "looks useful" in p.read_text(encoding="utf-8") for p in files)
    assert (folder / "index.md").read_text(encoding="utf-8").count("finds/") == 2
    if isinstance(data, dict):
        assert any("Useful model" in p.read_text(encoding="utf-8") and "Maker" in p.read_text(encoding="utf-8") for p in files)


def test_notes_list_recall_and_dashboard(lot, monkeypatch):
    shown = []

    async def show(title, page, caption=""):
        shown.append((title, page))

    monkeypatch.setattr(parking, "show_html", show)
    for i in range(9):
        run(parking.project_note("h2d", f"note {i}"))
    for i in range(7):
        run(parking.park_idea("h2d", f"Item {i}", "body"))
    notes = (parking.PARKING_ROOT / "H2D Workbench" / "notes.md").read_text(encoding="utf-8")
    assert notes.count("- 20") == 9
    spoken = run(parking.list_parked("h2d"))
    assert "7 parked items" in spoken and "Item 6" in spoken and "Item 0" not in spoken
    assert "Item 6" in shown[-1][1]
    assert "H2D Workbench: 7" in run(parking.list_parked())
    recalled = run(parking.recall_project("h2d"))
    assert "note 8" in recalled and "note 0" not in recalled
    assert "Item 6" in recalled and "Item 3" not in recalled

    async def broken(*args, **kwargs):
        raise OSError("dashboard offline")

    monkeypatch.setattr(parking, "show_html", broken)
    assert "7 parked items" in run(parking.list_parked("h2d"))


def test_symlink_cannot_escape_root(lot):
    root = parking.PARKING_ROOT
    root.mkdir()
    try:
        (root / "Escape").symlink_to(lot, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable")
    with pytest.raises(ValueError):
        run(parking.park_idea("escape", "x", "x"))


def test_tool_contract():
    assert [fn.__name__ for fn in parking.TOOLS] == [
        "park_idea", "save_pick", "project_note", "list_parked", "recall_project"]
    assert all(asyncio.iscoroutinefunction(fn) and fn.__doc__ for fn in parking.TOOLS)
