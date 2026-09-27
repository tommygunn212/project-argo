"""Tommy's own written record, from the local AnythingLLM workspace.
"""

from __future__ import annotations

from core.realtime_tools._base import capability

__all__ = [
    "rag_search",
]


@capability
def rag_search(query: str) -> dict:
    """Ask ARGO's local knowledge base about Tommy's life, writing and history.

    Backed by the AnythingLLM desktop app's "Tommy Knowledge Base" workspace
    - his about-me profile, wiki notes, blog mirrors, and book manuscript,
    not anything from ordinary conversation (that's recall(), a different
    tool). Use this for biographical, historical or written-record questions
    about Tommy that his standing instructions and memory don't already
    answer - not for small talk or facts about the here and now.
    """
    from core.config import get_config
    from core import anythingllm_client

    config = get_config()
    if not config.get("rag.enabled", True):
        return {
            "ok": False,
            "error": "not_configured",
            "message": "The knowledge base is turned off in config.json under rag.enabled.",
        }
    return anythingllm_client.query_workspace(
        query,
        base_url=config.get("rag.base_url", anythingllm_client.DEFAULT_BASE_URL),
        workspace=config.get("rag.workspace", anythingllm_client.DEFAULT_WORKSPACE),
        timeout=float(config.get("rag.timeout_seconds", anythingllm_client.DEFAULT_TIMEOUT)),
    )
