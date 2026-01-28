"""
Global audio ownership authority.

Single-owner gate for microphone/speaker usage across ARGO.
"""

import threading


class AudioOwner:
    def __init__(self):
        self._lock = threading.Lock()
        self._owner = None

    def acquire(self, owner: str) -> None:
        with self._lock:
            if self._owner and self._owner != owner:
                raise RuntimeError("Audio already owned")
            self._owner = owner

    def release(self, owner: str) -> None:
        with self._lock:
            if self._owner == owner:
                self._owner = None

    def force_release(self, reason: str = "") -> str | None:
        with self._lock:
            prior = self._owner
            self._owner = None
            return prior

    def get_owner(self) -> str | None:
        with self._lock:
            return self._owner


_audio_owner_instance: AudioOwner | None = None
_audio_owner_lock = threading.Lock()


def get_audio_owner() -> AudioOwner:
    global _audio_owner_instance
    if _audio_owner_instance is None:
        with _audio_owner_lock:
            if _audio_owner_instance is None:
                _audio_owner_instance = AudioOwner()
    return _audio_owner_instance
