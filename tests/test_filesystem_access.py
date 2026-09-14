"""Reach the whole machine, without being able to break it.

Tommy: "she cannot really search beyond her folder... she needs to have
access to I, the work drives, all my hard drives... READ AND WRITE."

She was confined to I:\\argo because filesystem.allowed_folders was never
set, and she had no write tools at all. Both are fixed. The carve-outs exist
to protect him, not to second-guess him: Windows and installed software,
credential files, and no real deletion.
"""

import pytest

from core import filesystem_access as FS
from core import realtime_tools as T
from pathlib import Path


# --- the scope ------------------------------------------------------------

def test_every_fixed_drive_is_readable_by_default(monkeypatch):
    monkeypatch.setattr(FS, "_configured", lambda key: [])
    monkeypatch.setattr(FS, "fixed_drives", lambda: [Path("C:\\"), Path("H:\\")])
    assert FS.read_roots() == [Path("C:\\"), Path("H:\\")]


def test_writing_follows_reading_unless_narrowed(monkeypatch):
    monkeypatch.setattr(FS, "_configured", lambda key: [])
    monkeypatch.setattr(FS, "fixed_drives", lambda: [Path("H:\\")])
    assert FS.write_roots() == FS.read_roots()


def test_config_can_narrow_the_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(FS, "_configured",
                        lambda key: [str(tmp_path)] if key.endswith("allowed_folders") else [])
    assert FS.read_roots() == [tmp_path.resolve()]


# --- what Windows keeps ---------------------------------------------------

@pytest.mark.parametrize("path", [
    r"C:\Windows\System32\drivers\etc\hosts",
    r"C:\Program Files\something\app.exe",
    r"C:\ProgramData\thing.dat",
    r"D:\$Recycle.Bin\file",
])
def test_system_locations_are_never_written(path):
    assert FS.is_protected_location(Path(path)) is not None
    assert FS.check_write(Path(path))["error"] == "protected_location"


@pytest.mark.parametrize("path", [
    r"H:\My Music\song.mp3",
    r"I:\down movies\film.mkv",
    r"C:\Users\KITTY\Documents\notes.txt",
])
def test_his_own_files_are_not_protected(path):
    assert FS.is_protected_location(Path(path)) is None


# --- what a voice assistant must never read aloud -------------------------

@pytest.mark.parametrize("path", [
    r"I:\argo\.env",
    r"C:\Users\KITTY\.ssh\id_rsa",
    r"C:\Users\KITTY\.aws\credentials",
    r"D:\certs\server.pem",
    r"D:\keys\private.key",
])
def test_credentials_are_refused_for_reading(path):
    """read_text_file could previously read I:\\argo\\.env - the OpenAI key
    and the Jellyfin token - straight out loud in a voice session."""
    assert FS.is_secret(Path(path)) is not None
    assert FS.check_read(Path(path))["error"] == "secret_file"


def test_credentials_are_refused_for_writing_too():
    assert FS.check_write(Path(r"I:\argo\.env"))["error"] == "secret_file"


def test_an_ordinary_file_is_not_mistaken_for_a_secret():
    assert FS.is_secret(Path(r"H:\notes\shopping.txt")) is None


# --- the write tools ------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    def configured(key):
        if key.endswith("quarantine_folder"):
            return [str(tmp_path / "quarantine")]
        if key.endswith("protected_folders"):
            return []          # nothing extra protected inside the sandbox
        return [str(tmp_path)]  # readable and writable

    monkeypatch.setattr(FS, "_configured", configured)
    return tmp_path


def test_writing_then_reading_back(sandbox):
    target = sandbox / "note.txt"
    assert T.write_text_file(str(target), "hello")["ok"]
    assert T.read_text_file(str(target))["content"] == "hello"


def test_an_existing_file_is_not_clobbered_silently(sandbox):
    target = sandbox / "note.txt"
    T.write_text_file(str(target), "original")

    refused = T.write_text_file(str(target), "replacement")

    assert refused["ok"] is False and refused["error"] == "exists"
    assert target.read_text() == "original"


def test_overwrite_when_actually_asked(sandbox):
    target = sandbox / "note.txt"
    T.write_text_file(str(target), "original")
    assert T.write_text_file(str(target), "replacement", overwrite=True)["replaced"] is True
    assert target.read_text() == "replacement"


def test_appending_creates_or_extends(sandbox):
    target = sandbox / "log.txt"
    T.append_text_file(str(target), "one\n")
    T.append_text_file(str(target), "two\n")
    assert target.read_text() == "one\ntwo\n"


def test_move_and_copy(sandbox):
    source = sandbox / "a.txt"
    source.write_text("x")
    assert T.copy_item(str(source), str(sandbox / "b.txt"))["ok"]
    assert (sandbox / "b.txt").exists()
    assert T.move_item(str(sandbox / "b.txt"), str(sandbox / "c.txt"))["ok"]
    assert (sandbox / "c.txt").exists() and not (sandbox / "b.txt").exists()


# --- nothing is ever really deleted ---------------------------------------

def test_removal_quarantines_instead_of_deleting(sandbox):
    """A voice command is a bad way to lose a file for good."""
    target = sandbox / "precious.txt"
    target.write_text("do not lose me")

    result = T.remove_item(str(target))

    assert result["ok"] is True
    assert not target.exists()
    recovered = Path(result["moved_to"])
    assert recovered.exists()
    assert recovered.read_text() == "do not lose me"
    assert "not deleted" in result["message"]


def test_removing_something_that_is_not_there(sandbox):
    assert T.remove_item(str(sandbox / "ghost.txt"))["error"] == "not_found"


# --- the report he can ask for --------------------------------------------

def test_the_policy_is_reportable():
    report = T.file_access_report()
    assert report["ok"]
    assert report["readable"] and report["writable"]
    assert "quarantine" in report["deletes"]
    assert ".env" in report["never_read_or_written"]
