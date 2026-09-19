"""Client for ARGO's local AnythingLLM RAG workspace.

AnythingLLM (the desktop app on this machine) hosts the "Tommy Knowledge
Base" workspace: Tommy's about-me profile, wiki notes, blog mirrors, and
book manuscript, embedded from I:\\tommy-rags. This module talks to it over
its local, unauthenticated frontend API - the desktop app runs with
multi-user mode off, so the workspace read/chat routes it uses here take no
API key, exactly the way the app's own UI reaches them from the same
machine. Document upload is a separate, v1, API-key-gated route this module
does not touch; adding new material to the workspace still goes through the
AnythingLLM UI.

The chat route is a Server-Sent-Events stream. A workspace whose chatMode is
"automatic" and whose model supports native tool calling will route every
message into an interactive agent session instead of answering directly -
that is a dead end for a voice tool that can't drive a back-and-forth agent
loop, so this module treats an agent handoff as a failure and reports why,
rather than silently returning nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger("ARGO.AnythingLLM")

DEFAULT_BASE_URL = "http://127.0.0.1:3001"
DEFAULT_WORKSPACE = "tommy-knowledge-base"
DEFAULT_TIMEOUT = 45.0


def query_workspace(
    message: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    workspace: str = DEFAULT_WORKSPACE,
    mode: str = "chat",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Ask the AnythingLLM workspace a question and return its grounded answer.

    Returns {"ok": True, "answer": str, "sources": [{"title", "source"}]}
    on success, or {"ok": False, "error": str} - never raises.
    """
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "empty query"}
    if not workspace:
        return {"ok": False, "error": "no AnythingLLM workspace configured"}

    url = f"{base_url.rstrip('/')}/api/workspace/{workspace}/stream-chat"
    try:
        response = requests.post(
            url,
            json={"message": message, "mode": mode},
            stream=True,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[AnythingLLM] request to %s failed: %s", url, exc)
        return {"ok": False, "error": f"AnythingLLM unreachable: {type(exc).__name__}"}

    answer_parts: list[str] = []
    sources: list[dict] = []
    saw_finalize = False
    error_message: str | None = None

    try:
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            payload = raw_line[len("data:"):].strip()
            if not payload:
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                logger.debug("[AnythingLLM] unparsable SSE line: %r", payload[:200])
                continue

            event_type = event.get("type")
            if event.get("error"):
                error_message = str(event.get("error"))

            if event_type == "agentInitWebsocketConnection":
                # chatMode "automatic" handed this to the agent loop instead
                # of answering. This workspace is meant to be set to "chat".
                return {
                    "ok": False,
                    "error": (
                        "AnythingLLM routed this to agent chat instead of "
                        "answering directly. Set the workspace's chatMode to "
                        '"chat" (not "automatic") in AnythingLLM.'
                    ),
                }
            elif event_type == "textResponseChunk":
                text = event.get("textResponse") or ""
                if text:
                    answer_parts.append(text)
                if event.get("sources"):
                    sources = event["sources"]
            elif event_type == "finalizeResponseStream":
                saw_finalize = True
                break
    finally:
        response.close()

    if error_message:
        return {"ok": False, "error": error_message}
    if not answer_parts and not saw_finalize:
        return {"ok": False, "error": "AnythingLLM closed the connection with no answer"}

    return {
        "ok": True,
        "answer": "".join(answer_parts).strip(),
        "sources": [
            {"title": s.get("title"), "source": s.get("url") or s.get("chunkSource")}
            for s in sources
            if isinstance(s, dict)
        ],
    }
