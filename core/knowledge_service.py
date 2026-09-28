"""One knowledge service for both ARGO voice paths.

AnythingLLM owns Tommy's authored knowledge base.  The old SQLite FTS index
searched this repository, had to be rebuilt manually, and answered a different
question.  Both Classic and Smooth Voice now call this boundary instead.
"""

from __future__ import annotations

from typing import Any

from core import anythingllm_client
from core.config import get_config

SUPPORTED_PROVIDER = "anythingllm"
DEFAULT_TIMEOUT = 15.0
MAX_TIMEOUT = 30.0


def _timeout(value: Any) -> float:
    try:
        return max(1.0, min(float(value), MAX_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def query_knowledge(query: str, *, config: Any | None = None) -> dict[str, Any]:
    """Query the configured authored-knowledge provider; never raise."""
    cfg = config or get_config()
    if not cfg.get("rag.enabled", True):
        return {
            "ok": False,
            "error": "not_configured",
            "message": "The knowledge base is turned off in config.json under rag.enabled.",
        }

    provider = str(cfg.get("rag.provider", SUPPORTED_PROVIDER) or "").strip().lower()
    if provider != SUPPORTED_PROVIDER:
        return {
            "ok": False,
            "error": "unsupported_provider",
            "message": f"Unsupported knowledge provider: {provider or '(blank)' }.",
        }

    return anythingllm_client.query_workspace(
        query,
        base_url=cfg.get("rag.base_url", anythingllm_client.DEFAULT_BASE_URL),
        workspace=cfg.get("rag.workspace", anythingllm_client.DEFAULT_WORKSPACE),
        timeout=_timeout(cfg.get("rag.timeout_seconds", DEFAULT_TIMEOUT)),
    )


def format_prompt_context(result: dict[str, Any]) -> str:
    """Turn a successful result into bounded, source-labelled prompt context."""
    if not result.get("ok"):
        return ""
    answer = str(result.get("answer") or "").strip()
    if not answer:
        return ""
    sources = []
    for source in result.get("sources") or []:
        if not isinstance(source, dict):
            continue
        label = str(source.get("title") or source.get("source") or "").strip()
        if label and label not in sources:
            sources.append(label[:300])
    suffix = f"\nSources: {'; '.join(sources[:5])}" if sources else ""
    return f"AnythingLLM knowledge answer:\n{answer}{suffix}"
