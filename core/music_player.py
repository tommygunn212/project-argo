"""
MUSIC PLAYER MODULE

Local music playback for ARGO.

Features:
- Directory scanning on startup (cached in memory)
- Random track selection
- Fire-and-forget playback (non-blocking)
- Voice interrupt support (uses existing stop mechanism)
- Minimal logging

Configuration:
- MUSIC_ENABLED (env): Enable/disable music entirely
- MUSIC_DIR (env): Path to music directory (e.g., I:\My Music)

File types supported:
- .mp3
- .wav
- .flac
- .m4a

No streaming, no playlists, no metadata obsession.
"""

import os
import logging
import random
import threading
from pathlib import Path
from typing import Optional, List

# ============================================================================
# LOGGER
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

MUSIC_ENABLED = os.getenv("MUSIC_ENABLED", "false").lower() == "true"
"""Enable/disable music playback entirely."""

MUSIC_DIR = os.getenv("MUSIC_DIR", "I:\\My Music")
"""Path to local music directory."""

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".m4a"}
"""Supported audio file extensions."""


# ============================================================================
# MUSIC PLAYER CLASS
# ============================================================================

class MusicPlayer:
    """
    Local music playback manager.
    
    Behavior:
    - Scans directory recursively on initialization
    - Caches file paths in memory (no rescans until restart)
    - Plays random track on voice command
    - Fire-and-forget playback (non-blocking)
    - Announces what's playing
    """

    def __init__(self):
        """Initialize music player and scan directory."""
        self.tracks: List[str] = []
        self.current_process: Optional[object] = None
        self.is_playing = False

        if not MUSIC_ENABLED:
            logger.info("[ARGO] Music disabled (MUSIC_ENABLED=false)")
            return

        self._scan_library()

    def _scan_library(self) -> None:
        """Recursively scan music directory and cache file paths."""
        if not os.path.exists(MUSIC_DIR):
            logger.warning(f"[ARGO] Music directory not found: {MUSIC_DIR}")
            return

        try:
            music_path = Path(MUSIC_DIR)
            self.tracks = [
                str(p)
                for p in music_path.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_FORMATS
            ]

            if self.tracks:
                logger.info(f"[ARGO] Music library loaded: {len(self.tracks)} tracks")
            else:
                logger.warning(f"[ARGO] No music files found in {MUSIC_DIR}")

        except Exception as e:
            logger.error(f"[ARGO] Error scanning music directory: {e}")

    def play_random(self, output_sink=None) -> bool:
        """
        Play a random track from the library.
        
        Args:
            output_sink: Optional output sink to announce track name
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED or not self.tracks:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        track = random.choice(self.tracks)
        filename = Path(track).stem  # Filename without extension
        
        return self.play(track, filename, output_sink)

    def play(self, track_path: str, track_name: str, output_sink=None) -> bool:
        """
        Play a specific track.
        
        Args:
            track_path: Absolute path to audio file
            track_name: Human-readable track name (for announcement)
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not os.path.exists(track_path):
            logger.error(f"[ARGO] Track not found: {track_path}")
            return False

        try:
            # Announce what's playing
            if output_sink:
                output_sink.speak(f"Playing: {track_name}")

            # Start playback in background thread (fire-and-forget)
            thread = threading.Thread(
                target=self._play_background,
                args=(track_path,),
                daemon=True
            )
            thread.start()

            logger.info(f"[ARGO] Playing music: {track_path}")
            self.is_playing = True
            return True

        except Exception as e:
            logger.error(f"[ARGO] Error starting playback: {e}")
            return False

    def _play_background(self, track_path: str) -> None:
        """Play audio in background thread."""
        try:
            # Try simpleaudio first (lightweight, fast)
            try:
                import simpleaudio
                wave_obj = simpleaudio.WaveObject.from_wave_file(track_path)
                self.current_process = wave_obj.play()
                self.current_process.wait_done()
            except ImportError:
                # Fallback to ffplay if available
                import subprocess
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", track_path],
                    capture_output=True,
                    timeout=3600  # Max 1 hour
                )
        except Exception as e:
            logger.error(f"[ARGO] Playback error: {e}")
        finally:
            self.is_playing = False
            logger.info("[ARGO] Music playback stopped")

    def stop(self) -> None:
        """Stop current playback (idempotent)."""
        if not self.is_playing:
            return

        try:
            if self.current_process:
                # For simpleaudio
                if hasattr(self.current_process, "stop"):
                    self.current_process.stop()
                # For ffplay, process will be killed by parent
            self.is_playing = False
            logger.info("[ARGO] Music playback stopped")
        except Exception as e:
            logger.error(f"[ARGO] Error stopping music: {e}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_music_player_instance: Optional[MusicPlayer] = None


def get_music_player() -> MusicPlayer:
    """Get or create the global music player instance."""
    global _music_player_instance
    if _music_player_instance is None:
        _music_player_instance = MusicPlayer()
    return _music_player_instance
