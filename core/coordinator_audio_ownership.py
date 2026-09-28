"""Serialized audio-owner operations for the classic coordinator."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CoordinatorAudioOwnershipDependencies:
    lock: threading.Lock
    get_owner: Callable[[], str | None]
    acquire_owner: Callable[[str], None]
    release_owner: Callable[[str], None]
    force_release_owner: Callable[[str], None]
    event_logger: Callable[[str], None]


class CoordinatorAudioOwnershipService:
    """Enforce one audio owner and emit the coordinator audit events."""

    def __init__(self, dependencies: CoordinatorAudioOwnershipDependencies):
        self._dependencies = dependencies

    def acquire(self, owner: str) -> None:
        dependencies = self._dependencies
        with dependencies.lock:
            current_owner = dependencies.get_owner()
            if current_owner and current_owner != owner:
                dependencies.event_logger(
                    f"AUDIO_CONTESTED owner={current_owner} requested={owner}"
                )
                raise RuntimeError("Audio already owned")
            dependencies.acquire_owner(owner)
            dependencies.event_logger(f"AUDIO_ACQUIRED owner={owner}")

    def release(self, owner: str) -> None:
        dependencies = self._dependencies
        with dependencies.lock:
            if dependencies.get_owner() == owner:
                dependencies.release_owner(owner)
                dependencies.event_logger(f"AUDIO_RELEASED owner={owner}")

    def force_release(self, reason: str = "") -> None:
        dependencies = self._dependencies
        with dependencies.lock:
            prior = dependencies.get_owner()
            if prior:
                dependencies.force_release_owner(reason)
                dependencies.event_logger(
                    f"AUDIO_FORCED_RELEASE prior={prior} reason={reason}"
                )
