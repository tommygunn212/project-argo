"""Plug-in abilities for Smooth Voice: MCP servers as voice tools.

Every Model Context Protocol server listed in ``config.json`` -> ``mcp`` becomes
a set of tools the realtime model can call, next to ARGO's own 53. Home
Assistant, a printer, a slicer, a browser - anything that speaks MCP - is a
config entry, not new ARGO code.

    "mcp": {
      "enabled": true,
      "connect_timeout_s": 8,
      "servers": [
        {"id": "home", "transport": "http",
         "url": "http://172.26.52.139:8123/api/mcp",
         "headers_env": {"Authorization": "HA_MCP_TOKEN"},
         "header_prefix": {"Authorization": "Bearer "},
         "allowed_tools": ["HassTurnOn", "HassTurnOff", "GetLiveContext"]},
        {"id": "files", "transport": "stdio", "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-filesystem", "I:/"]}
      ]
    }

Rules this module keeps:

  * **A plug-in must never cost ARGO her voice.** Each server is connected and
    asked for its tools *before* the session starts, under a timeout. One that
    is down, slow, misconfigured or not installed is logged, reported to the
    event stream, and left out - the session starts without it.
  * **Secrets stay in .env.** A server's headers name environment variables
    (``headers_env``); values never live in config.json and never reach the log.
  * **Off unless switched on.** ``mcp.enabled`` (or ``ARGO_MCP_ENABLED``) must be
    true. ``ARGO_MCP_ENABLED=0`` is the kill switch for every plug-in at once.
  * **Few tools beat many.** Realtime voice models choose worse as the tool list
    grows, so ``allowed_tools`` trims a server to what is actually wanted and a
    warning fires when the total gets large.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import voice_events

logger = logging.getLogger("ARGO.MCP")

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "config.json"
DEFAULT_CONNECT_TIMEOUT_S = 8.0
TOOL_COUNT_WARNING = 40


@dataclass(frozen=True)
class MCPServerSpec:
    """One plug-in as written in config.json, validated."""

    id: str
    transport: str  # "http" or "stdio"
    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers_env: dict[str, str] = field(default_factory=dict)
    header_prefix: dict[str, str] = field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ()

    def headers(self) -> dict[str, str]:
        """HTTP headers with values pulled from the environment (.env)."""
        out = {}
        for header, env_name in self.headers_env.items():
            value = os.getenv(env_name, "")
            if value:
                out[header] = f"{self.header_prefix.get(header, '')}{value}"
            else:
                logger.warning("[MCP] %s: header %s wants $%s, which is not set",
                               self.id, header, env_name)
        return out


@dataclass(frozen=True)
class MCPSettings:
    enabled: bool = False
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S
    servers: tuple[MCPServerSpec, ...] = ()


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _spec_from(raw: dict, index: int) -> MCPServerSpec | None:
    if not isinstance(raw, dict) or raw.get("enabled", True) is False:
        return None
    sid = str(raw.get("id") or f"mcp{index}").strip()
    transport = str(raw.get("transport") or ("stdio" if raw.get("command") else "http")).lower()
    if transport not in {"http", "stdio"}:
        logger.warning("[MCP] %s: unknown transport %r, skipped", sid, transport)
        return None
    if transport == "http" and not raw.get("url"):
        logger.warning("[MCP] %s: http server with no url, skipped", sid)
        return None
    if transport == "stdio" and not raw.get("command"):
        logger.warning("[MCP] %s: stdio server with no command, skipped", sid)
        return None
    return MCPServerSpec(
        id=sid,
        transport=transport,
        url=str(raw.get("url") or ""),
        command=str(raw.get("command") or ""),
        args=tuple(str(a) for a in raw.get("args") or ()),
        cwd=str(raw.get("cwd") or ""),
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        headers_env={str(k): str(v) for k, v in (raw.get("headers_env") or {}).items()},
        header_prefix={str(k): str(v) for k, v in (raw.get("header_prefix") or {}).items()},
        allowed_tools=tuple(str(t) for t in raw.get("allowed_tools") or ()),
    )


def load_settings(config: dict | None = None) -> MCPSettings:
    """MCP settings from config.json (or a given dict), env override applied."""
    if config is None:
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            config = {}
        except Exception:
            logger.warning("[MCP] could not read config.json; plug-ins off", exc_info=True)
            config = {}
    section = config.get("mcp") or {}
    enabled = bool(section.get("enabled", False))
    override = os.getenv("ARGO_MCP_ENABLED")
    if override is not None and override.strip():
        enabled = _truthy(override)
    specs = tuple(s for i, raw in enumerate(section.get("servers") or [])
                  if (s := _spec_from(raw, i)) is not None)
    try:
        timeout = float(section.get("connect_timeout_s", DEFAULT_CONNECT_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = DEFAULT_CONNECT_TIMEOUT_S
    return MCPSettings(enabled=enabled, connect_timeout_s=timeout, servers=specs)


def _build_toolset(spec: MCPServerSpec):
    """An MCPToolset for one spec. Raises ImportError if the mcp package is missing."""
    from livekit.agents.llm.mcp import MCPServerHTTP, MCPServerStdio, MCPToolset

    allowed = list(spec.allowed_tools) or None
    if spec.transport == "http":
        server = MCPServerHTTP(url=spec.url, headers=spec.headers() or None,
                               allowed_tools=allowed)
    else:
        env = {**os.environ, **spec.env} if spec.env else None
        server = MCPServerStdio(command=spec.command, args=list(spec.args), env=env,
                                cwd=spec.cwd or None)
    toolset = MCPToolset(id=f"mcp_{spec.id}", mcp_server=server)
    return toolset, allowed


async def _connect_one(spec: MCPServerSpec, timeout: float):
    try:
        toolset, allowed = _build_toolset(spec)
    except ImportError:
        logger.warning("[MCP] the 'mcp' package is not installed; %s skipped "
                       "(pip install \"livekit-agents[mcp]\")", spec.id)
        voice_events.emit("mcp_server_skipped", server=spec.id, reason="mcp package missing")
        return None
    try:
        await asyncio.wait_for(toolset.setup(), timeout=timeout)
    except Exception as exc:
        reason = "timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__
        logger.warning("[MCP] %s could not connect (%s); starting without it", spec.id, reason)
        voice_events.emit("mcp_server_skipped", server=spec.id, reason=reason)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(toolset.aclose(), timeout=3)
        return None
    if allowed and spec.transport == "stdio":
        # MCPServerStdio has no allowed_tools argument; trim after listing.
        names = set(allowed)
        toolset.filter_tools(lambda tool: _tool_name(tool) in names)
    names = [_tool_name(t) for t in toolset.tools]
    logger.info("[MCP] %s ready with %d tool(s): %s", spec.id, len(names), ", ".join(names))
    voice_events.emit("mcp_server_ready", server=spec.id, tools=names)
    return toolset


def _tool_name(tool) -> str:
    try:
        from livekit.agents.llm.tool_context import get_raw_function_info

        return get_raw_function_info(tool).name
    except Exception:
        return str(getattr(tool, "name", None) or getattr(tool, "__name__", "?"))


async def ready_toolsets(settings: MCPSettings | None = None) -> list:
    """Connected MCP toolsets for this session; never raises, may be empty."""
    try:
        settings = settings or load_settings()
        if not settings.enabled or not settings.servers:
            return []
        results = await asyncio.gather(
            *(_connect_one(s, settings.connect_timeout_s) for s in settings.servers),
            return_exceptions=True,
        )
        ready = [r for r in results if r is not None and not isinstance(r, BaseException)]
        total = sum(len(t.tools) for t in ready)
        if total > TOOL_COUNT_WARNING:
            logger.warning("[MCP] %d plug-in tools on top of ARGO's own - realtime models "
                           "choose worse with long tool lists; trim with allowed_tools", total)
        return ready
    except Exception:
        logger.warning("[MCP] plug-in setup failed; starting without plug-ins", exc_info=True)
        return []


async def close_toolsets(toolsets: list) -> None:
    for toolset in toolsets or []:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(toolset.aclose(), timeout=3)
