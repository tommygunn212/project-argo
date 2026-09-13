"""The realtime agent must be able to act on the machine and its own install.

The classic pipeline answers these through _respond_with_* handlers; the
realtime worker never imports the pipeline, so every capability has to be
re-exposed as a tool. These tests pin the tool surface and the containment
boundary, and exercise the read-only tools against the real machine.
"""

import json

import pytest

import os

# Importing the agent runs build_agent_server() at module scope, which does
# os.environ.setdefault("LIVEKIT_URL", ...). That leaked into the rest of the
# suite and made tests using a fake unreachable URL see the real server.
# Snapshot before the import, restore after.
_LIVEKIT_ENV = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_AGENT_NAME")
_env_before = {k: os.environ.get(k) for k in _LIVEKIT_ENV}

import livekit_realtime_agent as agent_mod  # noqa: E402

for _key, _value in _env_before.items():
    if _value is None:
        os.environ.pop(_key, None)
    else:
        os.environ[_key] = _value

from core import realtime_tools as T  # noqa: E402


EXPECTED_TOOLS = [
    "repair_argo",
    "get_pc_specs", "get_drive_space", "get_system_status", "run_self_diagnostics",
    "list_argo_files", "list_folder", "read_text_file", "find_files",
    "play_music", "stop_music", "next_track", "get_music_status",
    "open_app", "close_app", "focus_app", "list_running_apps",
    "set_volume", "get_volume",
]


@pytest.mark.parametrize("name", EXPECTED_TOOLS)
def test_tool_is_exposed_to_the_model(name):
    assert hasattr(agent_mod.ArgoRealtimeAgent, name), f"{name} is not callable by voice"


# --- machine ---------------------------------------------------------------

def test_pc_specs_returns_real_hardware():
    d = T.pc_specs()
    assert d["ok"]
    assert d["cpu"] and d["memory_total_gb"] and d["graphics"]
    assert d["motherboard"] or d["motherboard_maker"]


def test_drive_space_reports_real_drives():
    d = T.drive_space()
    assert d["ok"] and d["drives"]
    first = next(iter(d["drives"].values()))
    assert "free_gb" in first and "total_gb" in first


def test_system_status_reports_memory():
    d = T.system_status()
    assert d["ok"] and d["memory_used_percent"] is not None


def test_diagnostics_runs():
    assert T.diagnostics()["ok"]


# --- filesystem containment ------------------------------------------------

def test_lists_its_own_install():
    d = T.list_folder("")
    assert d["ok"]
    assert "core" in d["subfolders"]
    assert "main.py" in d["files"], "own files must be visible, not truncated away"


def test_lists_a_subfolder():
    d = T.list_folder("core")
    assert d["ok"] and "pipeline.py" in d["files"]


@pytest.mark.parametrize("bad", ["..", "../..", r"C:\Windows", r"C:\Users", "../../Windows"])
def test_refuses_anything_outside_the_allowlist(bad):
    d = T.list_folder(bad)
    assert not d["ok"] and d["error"] == "not_allowed", f"escaped via {bad!r}"


def test_read_text_file_is_also_contained():
    d = T.read_text_file(r"C:\Windows\win.ini")
    assert not d["ok"] and d["error"] == "not_allowed"


def test_read_text_file_reads_inside_the_install():
    d = T.read_text_file("VERSION")
    assert d["ok"] and d["content"].strip()


def test_granted_folder_is_honoured_without_restart(tmp_path, monkeypatch):
    """A folder granted in config must become readable on the next call."""
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(T, "allowed_roots", lambda: [T.ROOT, tmp_path.resolve()])
    d = T.list_folder(str(tmp_path))
    assert d["ok"] and "note.txt" in d["files"]


def test_find_files_searches_argos_own_folders():
    """Regression: search_files defaults to document folders and found nothing."""
    d = T.find_files("livekit")
    assert d["ok"]
    assert any(str(T.ROOT) in str(r) for r in d.get("results", [])) or d["count"] > 0


# --- controls report honestly ---------------------------------------------

def test_music_status_is_readable():
    d = T.music_status()
    assert d["ok"] and "playing" in d


def test_apps_running_lists_processes():
    d = T.apps_running()
    assert d["ok"] and isinstance(d["running"], list)


def test_volume_status_is_readable():
    d = T.volume_status()
    assert d["ok"] and 0 <= d["volume_percent"] <= 100


def test_failures_are_reported_not_raised(monkeypatch):
    """A broken dependency must surface as ok:false, never as an exception."""
    def boom(*a, **k):
        raise RuntimeError("device gone")
    monkeypatch.setattr("core.system_volume.get_status", boom)
    d = T.volume_status()
    assert d["ok"] is False and "device gone" in d["error"]
