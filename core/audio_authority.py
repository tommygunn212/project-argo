"""
AudioAuthority: Explicit ownership pattern for audio resources.

HARDENING STEP 3: Central gatekeeper for microphone and speaker access.
Prevents resource conflicts and ensures atomic acquisition/release.

This pattern ensures:
- Only one component can acquire a resource at a time
- Hard kills can terminate resource access immediately
- No shared state or implicit ownership
- Explicit acquire/release/kill operations (no silent failures)

Usage:
    audio = AudioAuthority()
    
    # Before recording
    audio.acquire("mic")
    try:
        record_audio()
    finally:
        audio.release("mic")
    
    # Before TTS
    audio.acquire("speaker")
    try:
        tts.play()
    finally:
        audio.release("speaker")
    
    # On interrupt: atomic kill
    audio.hard_kill_output()  # Kills speaker immediately
"""

import threading
from typing import Literal


class AudioAuthority:
    """Central authority for microphone and speaker acquisition."""
    
    # Resource types
    RESOURCE_MIC = "mic"
    RESOURCE_SPEAKER = "speaker"
    
    def __init__(self):
        """Initialize audio authority with empty ownership."""
        self._lock = threading.RLock()
        self._owner_mic: str | None = None      # Who owns the mic
        self._owner_speaker: str | None = None  # Who owns the speaker
        self._speaker_killed = False            # Emergency kill state
    
    def acquire(self, resource: Literal["mic", "speaker"], owner: str = "system") -> bool:
        """
        Acquire a resource (blocking if already owned).
        
        Args:
            resource: "mic" or "speaker"
            owner: Name of component acquiring resource (for debugging)
        
        Returns:
            True if acquired, False if invalid resource
        
        Raises:
            RuntimeError: If resource already owned by another component
        """
        if resource not in [self.RESOURCE_MIC, self.RESOURCE_SPEAKER]:
            raise ValueError(f"Invalid resource: {resource}")
        
        with self._lock:
            if resource == self.RESOURCE_MIC:
                if self._owner_mic and self._owner_mic != owner:
                    raise RuntimeError(f"Mic already owned by {self._owner_mic}, cannot acquire for {owner}")
                self._owner_mic = owner
                return True
            else:  # speaker
                if self._speaker_killed:
                    return False  # Speaker was hard-killed, cannot acquire
                if self._owner_speaker and self._owner_speaker != owner:
                    raise RuntimeError(f"Speaker already owned by {self._owner_speaker}, cannot acquire for {owner}")
                self._owner_speaker = owner
                return True
    
    def release(self, resource: Literal["mic", "speaker"], owner: str = "system") -> bool:
        """
        Release a resource.
        
        Args:
            resource: "mic" or "speaker"
            owner: Name of component releasing resource (must match acquirer)
        
        Returns:
            True if released, False if not owned by caller
        """
        if resource not in [self.RESOURCE_MIC, self.RESOURCE_SPEAKER]:
            raise ValueError(f"Invalid resource: {resource}")
        
        with self._lock:
            if resource == self.RESOURCE_MIC:
                if self._owner_mic == owner:
                    self._owner_mic = None
                    return True
                return False
            else:  # speaker
                if self._owner_speaker == owner:
                    self._owner_speaker = None
                    return True
                return False
    
    def hard_kill_output(self) -> None:
        """
        Emergency kill: Invalidate speaker and prevent future acquisition.
        
        Used by interrupt handler to ensure TTS cannot resume after barge-in.
        Called synchronously from coordinator thread when wake word detected.
        """
        with self._lock:
            self._speaker_killed = True
            self._owner_speaker = None
    
    def reset(self) -> None:
        """
        Reset authority state (test only).
        
        Used after interrupt to allow speaker to be acquired again.
        """
        with self._lock:
            self._owner_mic = None
            self._owner_speaker = None
            self._speaker_killed = False
    
    def is_owned(self, resource: Literal["mic", "speaker"]) -> bool:
        """Check if resource is currently owned."""
        if resource not in [self.RESOURCE_MIC, self.RESOURCE_SPEAKER]:
            raise ValueError(f"Invalid resource: {resource}")
        
        with self._lock:
            if resource == self.RESOURCE_MIC:
                return self._owner_mic is not None
            else:
                return self._owner_speaker is not None
    
    def get_owner(self, resource: Literal["mic", "speaker"]) -> str | None:
        """Get current owner of resource (for debugging)."""
        if resource not in [self.RESOURCE_MIC, self.RESOURCE_SPEAKER]:
            raise ValueError(f"Invalid resource: {resource}")
        
        with self._lock:
            if resource == self.RESOURCE_MIC:
                return self._owner_mic
            else:
                return self._owner_speaker


# Singleton instance
_audio_authority: AudioAuthority | None = None
_authority_lock = threading.Lock()


def get_audio_authority() -> AudioAuthority:
    """Get singleton AudioAuthority instance."""
    global _audio_authority
    if _audio_authority is None:
        with _authority_lock:
            if _audio_authority is None:
                _audio_authority = AudioAuthority()
    return _audio_authority
