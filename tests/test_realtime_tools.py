"""The realtime agent must be able to act on the machine and its own install.

The classic pipeline answers these through _respond_with_* handlers; the
realtime worker never imports the pipeline, so every capability has to be
re-exposed as a tool. These tests pin the tool surface and the containment
boundary, and exercise the read-only tools against the real machine.
"""

import json

import pytest

# The agent module no longer builds a server at import, so importing it here
# no longer sets LIVEKIT_URL and friends. The snapshot/restore dance that used
# to sit here is gone with its cause; test_agent_import_is_clean guards it.
import livekit_realtime_agent as agent_mod

from core import realtime_tools as T


EXPECTED_TOOLS = [
    "repair_argo",
    "get_pc_specs", "get_drive_space", "get_system_status", "run_self_diagnostics",
    "list_argo_files", "list_folder", "read_text_file", "find_files",
    "play_music", "stop_music", "next_track", "get_music_status",
    "open_app", "close_app", "focus_app", "list_running_apps",
    "set_volume", "get_volume",
    "set_pc_profile", "get_pc_profile_status",
    "search_knowledge_base",
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


def test_reads_across_the_whole_machine_now():
    """Tommy asked for access to all his drives, so the old confinement to
    I:\\argo is gone on purpose. Searching his work drives was the point."""
    d = T.list_folder(r"C:\Users")
    assert d["ok"], "reading outside the install is intended now"


def test_a_folder_outside_every_drive_is_still_refused(monkeypatch):
    from core import filesystem_access as FS

    monkeypatch.setattr(FS, "read_roots", lambda: [T.ROOT])
    d = T.list_folder(r"C:\Windows")
    assert not d["ok"] and d["error"] == "not_allowed"


def test_credentials_are_refused_however_they_are_reached():
    """The line that matters for a VOICE assistant: it must not read a key
    aloud, wherever that key happens to live."""
    d = T.read_text_file(str(T.ROOT / ".env"))
    assert not d["ok"] and d["error"] == "secret_file"


def test_windows_itself_is_never_written():
    d = T.write_text_file(r"C:\Windows\System32\drivers\etc\hosts", "x", overwrite=True)
    assert not d["ok"] and d["error"] == "protected_location"


def test_read_text_file_reads_inside_the_install():
    d = T.read_text_file("VERSION")
    assert d["ok"] and d["content"].strip()


def test_granted_folder_is_honoured_without_restart(tmp_path, monkeypatch):
    """A folder granted in config must become readable on the next call."""
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(T, "allowed_roots", lambda: [T.ROOT, tmp_path.resolve()])
    d = T.list_folder(str(tmp_path))
    assert d["ok"] and "note.txt" in d["files"]


def test_find_files_searches_every_drive_and_finds_folders():
    """Two regressions: the search used to cover only document folders, and
    it matched file names only - so "vzbot", a FOLDER, came back empty."""
    d = T.find_files("argo", want="folder")
    assert d["ok"] and d["count"] > 0
    assert any(r["type"] == "folder" for r in d["results"])
    assert len(d["searched"]) >= 1


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


# --- knowledge base (AnythingLLM) ------------------------------------------

def test_rag_search_returns_the_client_answer(monkeypatch):
    from core import anythingllm_client as ALLM

    def fake_query(message, **kwargs):
        assert message == "what's my maker background"
        return {"ok": True, "answer": "You build things.", "sources": []}

    monkeypatch.setattr(ALLM, "query_workspace", fake_query)
    d = T.rag_search("what's my maker background")
    assert d["ok"] and d["answer"] == "You build things."


def test_rag_search_reports_when_turned_off(monkeypatch):
    class FakeConfig:
        def get(self, key, default=None):
            if key == "rag.enabled":
                return False
            return default

    monkeypatch.setattr("core.config.get_config", lambda: FakeConfig())
    d = T.rag_search("anything")
    assert d["ok"] is False and d["error"] == "not_configured"


def test_rag_search_failure_is_reported_not_raised(monkeypatch):
    from core import anythingllm_client as ALLM

    def boom(*a, **k):
        raise RuntimeError("AnythingLLM is down")

    monkeypatch.setattr(ALLM, "query_workspace", boom)
    d = T.rag_search("anything")
    assert d["ok"] is False and "AnythingLLM is down" in d["error"]
