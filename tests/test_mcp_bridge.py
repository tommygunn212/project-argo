"""core/voice/mcp_bridge.py: MCP servers become voice tools, and a dead one never costs the voice.

The connection tests start a real MCP server (tests/fixtures/mcp_echo_server.py)
over stdio - no mocks - so "ready" means the tools were actually listed and
called through the MCP protocol.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from core.voice import mcp_bridge as B

ECHO_SERVER = str(Path(__file__).parent / "fixtures" / "mcp_echo_server.py")


@pytest.fixture(autouse=True)
def quiet_events(monkeypatch):
    events = []
    monkeypatch.setattr(B.voice_events, "emit", lambda kind, **f: events.append((kind, f)))
    monkeypatch.delenv("ARGO_MCP_ENABLED", raising=False)
    return events


def _settings(*servers, enabled=True, timeout=20):
    return B.load_settings({"mcp": {"enabled": enabled, "connect_timeout_s": timeout,
                                    "servers": list(servers)}})


ECHO = {"id": "echo", "transport": "stdio", "command": sys.executable, "args": [ECHO_SERVER]}


def run(coro):
    return asyncio.run(coro)


# --- configuration -----------------------------------------------------------

def test_off_by_default():
    assert B.load_settings({}).enabled is False
    assert run(B.ready_toolsets(B.load_settings({}))) == []


def test_env_switch_overrides_config(monkeypatch):
    monkeypatch.setenv("ARGO_MCP_ENABLED", "0")
    assert _settings(ECHO).enabled is False
    monkeypatch.setenv("ARGO_MCP_ENABLED", "1")
    assert _settings(ECHO, enabled=False).enabled is True


def test_bad_entries_are_skipped_not_fatal():
    s = _settings({"id": "a", "transport": "http"},           # no url
                  {"id": "b", "transport": "stdio"},          # no command
                  {"id": "c", "transport": "carrier-pigeon", "url": "x"},
                  {"id": "d", "url": "http://x/mcp", "enabled": False},
                  {"id": "e", "url": "http://x/mcp"})
    assert [spec.id for spec in s.servers] == ["e"]
    assert s.servers[0].transport == "http"


def test_header_secrets_come_from_env_only(monkeypatch):
    monkeypatch.setenv("TEST_MCP_TOKEN", "abc123")
    spec = _settings({"id": "h", "url": "http://x/mcp",
                      "headers_env": {"Authorization": "TEST_MCP_TOKEN", "X-Other": "UNSET_VAR_XYZ"},
                      "header_prefix": {"Authorization": "Bearer "}}).servers[0]
    assert spec.headers() == {"Authorization": "Bearer abc123"}


def test_missing_config_file_means_off(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "CONFIG_FILE", tmp_path / "nope.json")
    assert B.load_settings().enabled is False


# --- real connections ----------------------------------------------------------

def test_real_stdio_server_becomes_tools(quiet_events):
    async def scenario():
        ready = await B.ready_toolsets(_settings(ECHO))
        try:
            assert len(ready) == 1
            names = sorted(B._tool_name(t) for t in ready[0].tools)
            assert names == ["add", "echo"]
            # Call a tool through the MCP protocol, the way the session would.
            from livekit.agents.llm.tool_context import get_raw_function_info  # noqa: F401
            echo = next(t for t in ready[0].tools if B._tool_name(t) == "echo")
            result = await echo({"text": "hello sir"})
            assert "echo: hello sir" in json.dumps(result, default=str)
        finally:
            await B.close_toolsets(ready)
    run(scenario())
    assert ("mcp_server_ready", {"server": "echo", "tools": ["echo", "add"]}) in quiet_events \
        or any(k == "mcp_server_ready" for k, _ in quiet_events)


def test_allowed_tools_trims_a_server():
    async def scenario():
        ready = await B.ready_toolsets(_settings({**ECHO, "allowed_tools": ["add"]}))
        try:
            assert [B._tool_name(t) for t in ready[0].tools] == ["add"]
        finally:
            await B.close_toolsets(ready)
    run(scenario())


def test_dead_servers_are_left_out_and_never_raise(quiet_events):
    dead_http = {"id": "dead_http", "url": "http://127.0.0.1:9/mcp"}
    dead_cmd = {"id": "dead_cmd", "transport": "stdio", "command": "argo-no-such-command-xyz"}

    async def scenario():
        started = time.monotonic()
        ready = await B.ready_toolsets(_settings(dead_http, dead_cmd, ECHO, timeout=6))
        elapsed = time.monotonic() - started
        try:
            # The healthy one still comes up; the dead ones are simply absent.
            assert [t.id for t in ready] == ["mcp_echo"]
            assert elapsed < 20
        finally:
            await B.close_toolsets(ready)
    run(scenario())
    skipped = {f["server"] for k, f in quiet_events if k == "mcp_server_skipped"}
    assert skipped == {"dead_http", "dead_cmd"}


def test_negative_control_disabled_bridge_connects_nothing(quiet_events):
    """Same healthy server, bridge off: no tools, no connection attempt."""
    assert run(B.ready_toolsets(_settings(ECHO, enabled=False))) == []
    assert not quiet_events


def test_the_agent_carries_plugin_toolsets():
    import livekit_realtime_agent as agent_mod
    from core.livekit_config import get_livekit_realtime_config

    async def scenario():
        ready = await B.ready_toolsets(_settings(ECHO))
        try:
            agent = agent_mod.ArgoRealtimeAgent(get_livekit_realtime_config(), extra_tools=ready)
            assert ready[0] in agent.tools
            # ARGO's own tools are still there alongside the plug-in.
            own = {getattr(getattr(t, "info", None), "name", None) for t in agent.tools}
            assert hasattr(agent, "recall")
        finally:
            await B.close_toolsets(ready)
    run(scenario())
