"""Containment for paths ARGO is told to open by voice.

Tommy kept the wide drive access he asked for - his own documents, his work
drives, his music - and asked for the escapes to be shut. These are the
escapes: a traversal that walks out of wherever it started, a path that
leaves drive-letter scoping altogether, somebody else's Windows profile, and
the places a browser or a CLI parks a token inside his own profile.

Nothing here narrows what he can reach on purpose. Every test that fails
would be ARGO reading or writing somewhere nobody asked her to go.
"""

import os
from pathlib import Path

import pytest

from core import filesystem_access as FS
from core import realtime_tools as T


# --- shape: caught before resolve() can hide it ---------------------------

@pytest.mark.parametrize("raw", [
    r"I:\argo\..\..\Windows\System32",
    r"..\..\secrets",
    r"I:/argo/../../etc",
    r"core\..\..\..\Users",
])
def test_traversal_is_refused(raw):
    """resolve() collapses '..' silently, so it has to be caught while the
    original shape is still visible."""
    assert FS.path_shape_problem(raw) is not None
    assert FS.check_read(Path(r"I:\argo"), raw)["error"] == "bad_path"


@pytest.mark.parametrize("raw", [
    r"\\fileserver\share\payroll.xlsx",
    r"//evil-host/share",
    r"\\?\C:\Windows\System32",
    r"\\.\PhysicalDrive0",
])
def test_network_and_device_paths_are_refused(raw):
    """UNC and Win32 device paths sidestep drive-letter scoping entirely."""
    assert FS.path_shape_problem(raw) is not None


@pytest.mark.parametrize("raw", ["NUL", "CON", r"H:\notes\COM1.txt"])
def test_reserved_device_names_are_refused(raw):
    assert FS.path_shape_problem(raw) is not None


@pytest.mark.parametrize("raw", [
    r"I:\argo\core\pipeline.py",
    r"H:\My Music\song.mp3",
    r"C:\Users\KITTY\Documents\notes.txt",
    "core",
    "",
])
def test_ordinary_paths_are_left_alone(raw):
    """The point of the widening stands: normal paths must not trip any of this."""
    assert FS.path_shape_problem(raw) is None


def test_a_refused_shape_reaches_the_model_as_an_answer_not_a_crash():
    """The model has to be able to say why, so a refusal is an ok:false
    result with a reason - never a raised exception or a generic failure."""
    result = T.list_folder(r"I:\argo\..\..\Windows")
    assert result["ok"] is False
    assert result["error"] == "bad_path"
    assert "traversal" in result["message"]


def test_read_text_file_refuses_a_traversal_too():
    result = T.read_text_file(r"..\..\..\Windows\win.ini")
    assert result["ok"] is False and result["error"] == "bad_path"


# --- Windows stays unreadable, not merely unwritable ----------------------

@pytest.mark.parametrize("path", [
    r"C:\Windows\System32\drivers\etc\hosts",
    r"C:\Program Files\App\readme.txt",
    r"C:\ProgramData\secrets\thing.dat",
])
def test_system_locations_are_refused_for_reading(path):
    """Write was already blocked. Reading was not, so ARGO could read out of
    C:\\Windows aloud."""
    assert FS.check_read(Path(path))["error"] == "protected_location"


@pytest.mark.parametrize("path", [
    r"C:\Windows\System32\config\SAM",
    r"C:\Program Files\App\licence.key",
])
def test_a_system_file_that_is_also_a_credential_is_refused_as_a_secret(path):
    """Order matters: "I won't read a credential aloud" is the more useful
    refusal than "that folder belongs to Windows", and it is the one that
    still applies if the folder rules are ever widened."""
    assert FS.check_read(Path(path))["error"] == "secret_file"


def test_narrowed_roots_still_answer_out_of_scope_first(monkeypatch):
    """When the roots have been narrowed, 'outside what I can read' is the
    more truthful refusal than 'protected'. Pins the check order."""
    monkeypatch.setattr(FS, "read_roots", lambda: [FS.ROOT])
    assert FS.check_read(Path(r"C:\Windows"))["error"] == "not_allowed"


# --- other people's profiles ----------------------------------------------

@pytest.fixture
def as_kitty(monkeypatch):
    monkeypatch.setenv("USERNAME", "KITTY")
    monkeypatch.setattr(FS.Path, "home", staticmethod(lambda: Path(r"C:\Users\KITTY")))
    return "KITTY"


@pytest.mark.parametrize("path", [
    r"C:\Users\Administrator\Desktop\payroll.xlsx",
    r"C:\Users\bob\Documents\diary.txt",
])
def test_another_users_profile_is_refused(as_kitty, path):
    assert FS.is_foreign_user_profile(Path(path)) is not None
    assert FS.check_read(Path(path))["error"] == "not_allowed"
    assert FS.check_write(Path(path))["error"] == "not_allowed"


@pytest.mark.parametrize("path", [
    r"C:\Users",
    r"C:\Users\KITTY\Documents\notes.txt",
    r"C:\Users\Public\Desktop\shared.txt",
    r"H:\My Music\song.mp3",
])
def test_his_own_and_shared_locations_stay_open(as_kitty, path):
    """This is the access he asked for and it must not regress."""
    assert FS.is_foreign_user_profile(Path(path)) is None


# --- credential stores inside his own profile ------------------------------

@pytest.mark.parametrize("path", [
    r"C:\Users\KITTY\AppData\Roaming\Microsoft\Credentials\ABC123",
    r"C:\Users\KITTY\AppData\Local\Google\Chrome\User Data\Default\Login Data",
    r"C:\Users\KITTY\.git-credentials",
    r"C:\Users\KITTY\NTUSER.DAT",
])
def test_credential_stores_are_refused_even_in_his_own_profile(as_kitty, path):
    """His documents are his. A saved browser password is still a credential,
    and a voice assistant must not read one aloud."""
    assert FS.is_secret(Path(path)) is not None
    assert FS.check_read(Path(path))["error"] == "secret_file"


def test_an_ordinary_appdata_file_is_not_a_secret(as_kitty):
    assert FS.is_secret(Path(r"C:\Users\KITTY\AppData\Roaming\MyApp\settings.ini")) is None


# --- the policy is still reportable ----------------------------------------

def test_the_new_rules_are_in_the_report():
    report = T.file_access_report()
    assert report["ok"]
    shapes = " ".join(report["refused_path_shapes"]).lower()
    assert "traversal" in shapes and "unc" in shapes and "profile" in shapes
