"""What every capability shares: the install root, the log, and the failure contract."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("ARGO.RealtimeTools")

ROOT = Path(__file__).resolve().parents[2]


def _fail(action: str, exc: Exception) -> dict:
    # A refused path is a policy answer, not a crash: hand back the refusal
    # itself so the model can say why, instead of a generic tool failure.
    refusal = getattr(exc, "refusal", None)
    if isinstance(refusal, dict):
        logger.info("[Tools] %s refused: %s", action, refusal.get("message"))
        return refusal
    logger.exception("[Tools] %s failed", action)
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def capability(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Make a capability honour the contract: never raise, report failure as data.

    Any exception becomes ``{"ok": False, "error": ...}`` (or the refusal it
    carries), so the model can say what went wrong instead of inventing a
    result.
    """
    @functools.wraps(fn)
    def guarded(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return _fail(fn.__name__, exc)
    return guarded
