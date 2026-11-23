"""core/board_service.py: project names, parked items, notes, saved layouts, focus."""

import json

import pytest

from core import board_service as B


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(B, "LAYOUT_FILE", tmp_path / "layouts.json")
    monkeypatch.setattr(B, "_focus", {"project": "", "seq": 0, "tidy_seq": 0})
    return tmp_path


def park(root, project, kind, name, title, date="2026-11-23", why="", body="body text"):
    folder = root / "projects" / project / kind
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(
        f'---\ntitle: "{title}"\ndate: "{date}"\nproject: "{project}"\nkind: "{kind[:-1]}"\nwhy: "{why}"\n---\n\n{body}\n',
        encoding="utf-8")


def test_names_resolve_aliases_and_blank_means_all():
    assert B.normalize("h2d") == "H2D Workbench" and B.normalize("Cooking School") == "ChefsByte"
    assert B.normalize("") == B.ALL and B.normalize("everything") == B.ALL
    assert B.normalize("my new thing!!") == "My New Thing"


def test_parked_items_are_newest_first_and_read_their_front_matter(board):
    park(board, "Argo", "ideas", "2026-11-22-old.md", "Old idea", date="2026-11-22")
    park(board, "Argo", "finds", "2026-11-23-new.md", "New find", why="fits my setup")
    items = B.parked("argo")
    assert [i["title"] for i in items] == ["New find", "Old idea"]
    assert items[0]["why"] == "fits my setup" and items[0]["kind"] == "find" and items[0]["preview"] == "body text"
    assert len(B.parked("All")) == 2 and B.parked("YouTube") == []


def test_notes_are_newest_first(board):
    folder = board / "projects" / "H2D Workbench"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("# Notes\n\n- 2026-11-20: first\n- 2026-11-23: second\n", encoding="utf-8")
    assert B.notes("h2d") == ["2026-11-23: second", "2026-11-20: first"]
    assert B.notes("All") == [] and B.notes("Argo") == []


def test_layout_is_validated_and_clamped(board):
    saved = B.save_layout("argo", {
        "jobs": {"x": 40.7, "y": -9000, "w": 5, "h": 99999, "color": "teal", "collapsed": True, "evil": "x"},
        "../bad": {"x": 1}, "show": {"color": "hotpink"}, "notes": "nope"})
    assert saved == {"jobs": {"x": 40, "y": -2000, "w": 180, "h": 2400, "color": "teal", "collapsed": True}}
    assert B.get_layout("Argo") == saved
    assert B.get_layout("H2D") == {}  # layouts are per project


def test_empty_layout_removes_the_saved_one(board):
    B.save_layout("argo", {"jobs": {"x": 1, "y": 2}})
    B.save_layout("argo", {})
    assert B.get_layout("argo") == {} and json.loads(B.LAYOUT_FILE.read_text()) == {}


def test_focus_and_tidy_bump_counters_and_tidy_clears_the_layout(board):
    B.save_layout("h2d", {"jobs": {"x": 1, "y": 2}})
    assert B.set_focus("printer") == "H2D Workbench"
    assert B.tidy("h2d") == "H2D Workbench"
    snap = B.snapshot("h2d", [], [])
    assert snap["focus"] == {"project": "H2D Workbench", "seq": 1, "tidy_seq": 1}
    assert snap["layout"] == {}


def test_snapshot_filters_jobs_by_project_and_strips_show_content(board):
    jobs = [{"id": "a", "project": "ChefsByte"}, {"id": "b", "project": "h2d"}, {"id": "c", "project": ""}]
    show = [{"id": "s1", "title": "T", "kind": "image", "caption": "c", "src": "data:big"}]
    snap = B.snapshot("h2d", jobs, show)
    assert [j["id"] for j in snap["jobs"]] == ["b"]
    assert snap["show"] == [{"id": "s1", "title": "T", "kind": "image", "caption": "c"}]
    assert [j["id"] for j in B.snapshot("", jobs, show)["jobs"]] == ["a", "b", "c"]
    assert "All" in snap["projects"] and "Argo" in snap["projects"]


def test_the_agent_has_the_board_tools():
    import livekit_realtime_agent as agent_mod

    for name in ("show_board", "tidy_board"):
        assert hasattr(agent_mod.ArgoRealtimeAgent, name)

def test_topic_notes_are_kept_per_project_and_newest_first(board):
    done = B.add_topic_note("cooking school", "Promotions", "try a launch week discount")
    assert done == {"project": "ChefsByte", "topic": "Promotions"}
    B.add_topic_note("chefsbyte", "promotions", "email the list first")
    B.add_topic_note("chefsbyte", "Mentor", "Dot suggested weekly review")
    found = B.topics("chefsbyte")
    by = {t["topic"]: t for t in found}
    assert by["Promotions"]["count"] == 2
    assert by["Promotions"]["entries"][0].endswith("email the list first")
    assert B.topics("Argo") == [] and len(B.topics("All")) == 2


def test_topic_note_rejects_empty_and_unsafe_names(board):
    with pytest.raises(ValueError):
        B.add_topic_note("argo", "x", "   ")
    B.add_topic_note("argo", "../../evil", "text")
    assert not (board / "evil.md").exists()
    assert [p.name for p in (B.PROJECTS_ROOT / "Argo" / "topics").iterdir()] == ["evil.md"]


def test_snapshot_carries_topics_and_activity(board, monkeypatch):
    B.add_topic_note("argo", "Board", "cards")
    from core.voice import action_log
    monkeypatch.setattr(action_log, "recent", lambda n=20: [
        {"clock": "2026-11-23T12:00:00.000", "tool": "show_image", "ok": True, "output": {"message": "Showing it."}}])
    snap = B.snapshot("argo", [], [])
    assert snap["topics"][0]["topic"] == "Board"
    assert snap["activity"] == [{"clock": "2026-11-23T12:00:00", "tool": "show_image", "ok": True, "said": "Showing it."}]


def test_the_agent_has_topic_tools():
    import livekit_realtime_agent as agent_mod

    for name in ("note_to_topic", "list_topics"):
        assert hasattr(agent_mod.ArgoRealtimeAgent, name)


def test_activity_shows_old_log_rows_that_said_failed_as_failed(board, monkeypatch):
    from core.voice import action_log
    monkeypatch.setattr(action_log, "recent", lambda n=20: [
        {"clock": "2026-11-22T23:17:17.175", "tool": "work_on_project", "ok": True,
         "output": {"status": "failed", "message": "Commit first."}}])
    assert B.activity()[0]["ok"] is False
