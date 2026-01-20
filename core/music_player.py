"""
MUSIC PLAYER MODULE

Local music playback for ARGO with genre/keyword support.

Uses music_index.py for track discovery and filtering.

Features:
- Persistent JSON catalog (fast startup)
- Genre filtering (punk, classic rock, glam, etc.)
- Keyword search (artist, album, track names)
- Fire-and-forget playback (non-blocking)
- Voice interrupt support (uses existing stop mechanism)
- Minimal logging

Configuration:
- MUSIC_ENABLED (env): Enable/disable music entirely
- MUSIC_DIR (env): Path to music directory
- MUSIC_INDEX_FILE (env): Path to JSON catalog

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
from typing import Optional, List, Dict

# Import music index for catalog and filtering
from core.music_index import get_music_index

# ============================================================================
# LOGGER
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

MUSIC_ENABLED = os.getenv("MUSIC_ENABLED", "false").lower() == "true"
"""Enable/disable music playback entirely."""

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".m4a"}
"""Supported audio file extensions."""


# ============================================================================
# MUSIC PLAYER CLASS
# ============================================================================

class MusicPlayer:
    """
    Local music playback manager with genre/keyword support.
    
    Behavior:
    - Uses persistent JSON index (fast startup, no rescans)
    - Supports genre filtering (punk, classic rock, etc.)
    - Supports keyword search (artist, album, track names)
    - Plays random track on voice command
    - Fire-and-forget playback (non-blocking)
    - Announces what's playing
    """

    def __init__(self):
        """Initialize music player and load index."""
        self.index = None
        self.current_process: Optional[object] = None
        self.is_playing = False

        if not MUSIC_ENABLED:
            logger.info("[ARGO] Music disabled (MUSIC_ENABLED=false)")
            return

        # Load the music index (fast, persistent JSON)
        try:
            self.index = get_music_index()
            track_count = len(self.index.tracks) if self.index.tracks else 0
            logger.info(f"[ARGO] Music index loaded: {track_count} tracks")
        except Exception as e:
            logger.error(f"[ARGO] Error loading music index: {e}")
            self.index = None

    def play_random(self, output_sink=None) -> bool:
        """
        Play a random track from the library.
        
        Args:
            output_sink: Optional output sink to announce track name
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED or not self.index or not self.index.tracks:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        track = self.index.get_random_track()
        if not track:
            if output_sink:
                output_sink.speak("No music available.")
            return False

        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        return self.play(track_path, announcement, output_sink)

    def play_by_genre(self, genre: str, output_sink=None) -> bool:
        """
        Play a random track from specified genre.
        
        Args:
            genre: Genre name (canonical or alias)
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED or not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        tracks = self.index.filter_by_genre(genre)
        if not tracks:
            if output_sink:
                output_sink.speak(f"No {genre} music found.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        return self.play(track_path, announcement, output_sink)

    def play_by_artist(self, artist: str, output_sink=None) -> bool:
        """
        Play a random track by specified artist.
        
        Args:
            artist: Artist name
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED or not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        tracks = self.index.filter_by_artist(artist)
        if not tracks:
            if output_sink:
                output_sink.speak(f"No tracks by {artist} found.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        return self.play(track_path, announcement, output_sink)

    def play_by_song(self, song: str, output_sink=None) -> bool:
        """
        Play a specific song by name.
        
        Args:
            song: Song name
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED or not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        tracks = self.index.filter_by_song(song)
        if not tracks:
            if output_sink:
                output_sink.speak(f"Song {song} not found.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        return self.play(track_path, announcement, output_sink)

    def play_by_keyword(self, keyword: str, output_sink=None) -> bool:
        """
        Play a random track matching keyword search (artist/song/filename).
        
        Priority: Try artist first, then song name, then generic keyword search.
        
        Args:
            keyword: Search term (artist, song name, or keyword)
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED or not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        # Priority 1: Try exact artist match
        tracks = self.index.filter_by_artist(keyword)
        if tracks:
            track = random.choice(tracks)
            track_path = track.get("path", "")
            announcement = self._build_announcement(track)
            return self.play(track_path, announcement, output_sink)

        # Priority 2: Try exact song match
        tracks = self.index.filter_by_song(keyword)
        if tracks:
            track = random.choice(tracks)
            track_path = track.get("path", "")
            announcement = self._build_announcement(track)
            return self.play(track_path, announcement, output_sink)

        # Priority 3: Generic keyword search
        tracks = self.index.filter_by_keyword(keyword)
        if not tracks:
            if output_sink:
                output_sink.speak(f"No music found for '{keyword}'.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        return self.play(track_path, announcement, output_sink)

    def _build_announcement(self, track: Dict) -> str:
        """
        Build friendly announcement from track data.
        
        Formats:
        - With artist and song: "Song Name by Artist Name"
        - With artist only: "Artist Name"
        - With song only: "Song Name"
        - Fallback: filename without extension
        
        Args:
            track: Track dictionary
            
        Returns:
            Announcement string
        """
        song = track.get("song")
        artist = track.get("artist")
        name = track.get("name", "track")
        
        if song and artist:
            return f"{song} by {artist}"
        elif song:
            return song
        elif artist:
            return artist
        else:
            return name

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
            # Try Python audio libraries (no external dependency)
            import os
            
            # Method 1: Try pygame (if available)
            try:
                import pygame
                pygame.mixer.init()
                pygame.mixer.music.load(track_path)
                pygame.mixer.music.play()
                
                # Wait for playback to finish
                while pygame.mixer.music.get_busy():
                    import time
                    time.sleep(0.1)
                
                logger.info(f"[ARGO] Playback completed via pygame")
                return
            except ImportError:
                pass  # pygame not installed
            except Exception as e:
                logger.debug(f"[ARGO] pygame playback failed: {e}")
            
            # Method 2: Try pydub + simpleaudio
            try:
                from pydub import AudioSegment
                import simpleaudio
                
                logger.info(f"[ARGO] Loading audio with pydub...")
                sound = AudioSegment.from_file(track_path)
                
                logger.info(f"[ARGO] Playing audio with simpleaudio...")
                playback = simpleaudio.play_buffer(
                    sound.raw_data,
                    num_channels=sound.channels,
                    bytes_per_sample=sound.sample_width,
                    sample_rate=sound.frame_rate
                )
                playback.wait_done()
                logger.info(f"[ARGO] Playback completed via pydub+simpleaudio")
                return
            except ImportError:
                pass  # pydub/simpleaudio not installed
            except Exception as e:
                logger.debug(f"[ARGO] pydub playback failed: {e}")
            
            # Method 3: Try ffplay via subprocess
            try:
                import subprocess
                import shutil
                
                ffplay_path = shutil.which("ffplay")
                if ffplay_path:
                    logger.info(f"[ARGO] Playing via ffplay: {ffplay_path}")
                    subprocess.run(
                        [ffplay_path, "-nodisp", "-autoexit", track_path],
                        capture_output=True,
                        timeout=3600
                    )
                    logger.info(f"[ARGO] Playback completed via ffplay")
                    return
            except Exception as e:
                logger.debug(f"[ARGO] ffplay not available: {e}")
            
            # If all methods failed
            logger.error(f"[ARGO] No audio playback method available (install pygame or ffmpeg)")
                
        except Exception as e:
            logger.error(f"[ARGO] Playback error: {type(e).__name__}: {e}")
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
