"""Writing into apps and saving drafts, over the realtime path.

core.app_control.write_text_to_app and tools/writing existed but nothing
reached them from a voice session, so ARGO could open Notepad and then had
no way to put anything in it. These cover the bridge, and - just as
important - that a request it cannot honour comes back as a refusal rather
than a cheerful lie.
"""

import pytest

from core import realtime_tools as T


# --- typing into an app ---------------------------------------------------

def test_writable_apps_are_named():
    d = T.writable_apps()
    assert d["ok"]
    assert "notepad" in d["apps"]


def test_unwritable_app_is_refused_not_faked():
    d = T.app_write("orca slicer", "hello")
    assert d["ok"] is False
    assert d["error"] == "not_writable"
    assert "notepad" in " ".join(d["writable"])


def test_empty_text_is_refused_before_opening_anything():
    d = T.app_write("notepad", "   ")
    assert d["ok"] is False and d["error"] == "empty_text"


def test_app_write_never_raises(monkeypatch):
    monkeypatch.setattr(
        "core.app_control.write_text_to_app",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    d = T.app_write("notepad", "text")
    assert d["ok"] is False and "RuntimeError" in d["error"]


# --- drafts ---------------------------------------------------------------

def test_unknown_draft_kind_is_reported_with_the_valid_ones():
    d = T.draft_write("telegram", "hi", "body")
    assert d["ok"] is False and d["error"] == "unknown_kind"
    assert set(d["kinds"]) == set(T.DRAFT_KINDS)


def test_empty_body_saves_nothing():
    d = T.draft_write("note", "title", "  ")
    assert d["ok"] is False and d["error"] == "empty_body"


@pytest.mark.parametrize("kind", ["email", "document", "blog", "note"])
def test_each_draft_kind_actually_writes_a_file(kind, tmp_path):
    from pathlib import Path

    d = T.draft_write(kind, "ARGO realtime test", "Body written by the test suite.",
                      recipient="nobody@example.com")
    assert d["ok"], d
    path = Path(d["path"])
    assert path.exists(), "the draft must be on disk, not just reported"
    assert "Body written by the test suite." in path.read_text(encoding="utf-8")
    path.unlink()


def test_drafts_list_reports_real_entries():
    saved = T.draft_write("note", "listing probe", "listing probe body")
    assert saved["ok"]
    try:
        d = T.drafts_list(limit=50)
        assert d["ok"]
        assert any(row["name"] == saved["name"] for row in d["drafts"])
    finally:
        from pathlib import Path
        Path(saved["path"]).unlink(missing_ok=True)


def test_draft_read_returns_the_body_and_misses_are_reported():
    saved = T.draft_write("note", "readback probe", "readback probe body")
    assert saved["ok"]
    try:
        d = T.draft_read("readback probe")
        assert d["ok"] and "readback probe body" in d["content"]
    finally:
        from pathlib import Path
        Path(saved["path"]).unlink(missing_ok=True)

    assert T.draft_read("no such draft xyzzy")["error"] == "not_found"


# --- sending --------------------------------------------------------------

def test_email_status_is_honest_about_voice_sending():
    d = T.email_status()
    assert d["ok"]
    assert d["can_send_by_voice"] is False, "nothing bridges sending to a voice session"
    assert isinstance(d["configured"], bool)


# --- the write is verified, not assumed -----------------------------------

def _pretend_paste_succeeded(monkeypatch):
    monkeypatch.setattr("core.app_control.write_text_to_app",
                        lambda *a, **k: (True, "Inserted it into Notepad."))


def test_paste_that_never_arrived_is_reported_as_failure(monkeypatch):
    """The real bug: AppActivate can match the wrong window and the
    keystroke goes nowhere, but write_text_to_app still reported success."""
    _pretend_paste_succeeded(monkeypatch)
    monkeypatch.setattr(T, "read_app_text", lambda key: "something else entirely")
    d = T.app_write("notepad", "the payload")
    assert d["ok"] is False and d["error"] == "not_verified"


def test_verified_write_says_so(monkeypatch):
    _pretend_paste_succeeded(monkeypatch)
    monkeypatch.setattr(T, "read_app_text", lambda key: "before the payload after")
    d = T.app_write("notepad", "the payload")
    assert d["ok"] is True and d["verified"] is True


def test_unreadable_window_is_not_counted_as_proof_either_way(monkeypatch):
    _pretend_paste_succeeded(monkeypatch)
    monkeypatch.setattr(T, "read_app_text", lambda key: None)
    d = T.app_write("notepad", "the payload")
    assert d["ok"] is True and d["verified"] is False


def test_read_app_text_declines_apps_it_has_no_class_for():
    assert T.read_app_text("orcaslicer") is None
