"""The realtime agent must be able to inspect the PC and its own install.

The classic pipeline answers these through _respond_with_* handlers. The
realtime worker never imports the pipeline, so without these tools the model
has nothing to call and correctly refuses - which reads to the user as ARGO
losing an ability it used to have.
"""

import asyncio
import json

import pytest

import livekit_realtime_agent as agent_mod


EXPECTED_TOOLS = [
    "get_pc_specs", "get_drive_space", "get_system_status",
    "find_files", "list_argo_files", "repair_argo",
]


def _call(name, **kw):
    """Invoke the underlying function behind livekit's @function_tool wrapper."""
    tool = getattr(agent_mod.ArgoRealtimeAgent, name)
    fn = getattr(tool, "__wrapped__", None) or getattr(tool, "fn", None) or tool
    return asyncio.run(fn(None, **kw))


@pytest.mark.parametrize("name", EXPECTED_TOOLS)
def test_tool_is_registered(name):
    assert hasattr(agent_mod.ArgoRealtimeAgent, name)


def test_pc_specs_returns_real_hardware():
    d = json.loads(_call("get_pc_specs"))
    assert d.get("cpu"), "no CPU reported"
    assert d.get("motherboard") or d.get("motherboard_maker"), "no motherboard reported"
    assert d.get("memory_total_gb"), "no RAM reported"
    assert d.get("graphics"), "no graphics card reported"


def test_drive_space_reports_drives():
    d = json.loads(_call("get_drive_space"))
    assert d, "no drives reported"
    first = next(iter(d.values()))
    assert "free_gb" in first and "total_gb" in first


def test_system_status_has_memory():
    d = json.loads(_call("get_system_status"))
    assert d.get("memory_total_gb") is not None


def test_list_argo_files_sees_own_install():
    d = json.loads(_call("list_argo_files", subfolder=""))
    assert "core" in d["subfolders"]
    assert any(f == "main.py" for f in d["files"])


def test_list_argo_files_reads_a_subfolder():
    d = json.loads(_call("list_argo_files", subfolder="core"))
    assert "pipeline.py" in d["files"]


def test_list_argo_files_refuses_to_escape_the_install():
    for attempt in ["..", "../..", "../Windows"]:
        out = _call("list_argo_files", subfolder=attempt)
        assert "did not look there" in out, f"escaped with {attempt!r}: {out[:80]}"
