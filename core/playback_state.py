"""
PLAYBACK STATE MANAGEMENT

Global playback state for music system.

Tracks:
- Current playback mode (artist, genre, random)
- Artist being played (if mode=artist)
- Genre being played (if mode=genre)
- Current track metadata

Used by:
- Music player: Sets state when starting playback
- Coordinator: Reads state for NEXT commands
- Bootstrap: Resets on app startup

Thread-safe: Assumes coordinator runs single-threaded
"""

from typing import Dict, Optional


class PlaybackState:
    """
    Global music playback state.
    
    Attributes:
        mode: "artist" | "genre" | "random" | None
        artist: Artist name if mode == "artist", else None
        genre: Genre name if mode == "genre", else None
        current_track: Full track dict {path, name, artist, song, genre, ...} or None
    """

    def __init__(self):
        """Initialize empty playback state."""
        self.mode: Optional[str] = None  # "artist" | "genre" | "random"
        self.artist: Optional[str] = None
        self.genre: Optional[str] = None
        self.current_track: Optional[Dict] = None

    def set_artist_mode(self, artist: str, track: Dict) -> None:
        """
        Set state for artist playback.
        
        Args:
            artist: Artist name
            track: Full track dictionary
        """
        self.mode = "artist"
        self.artist = artist
        self.genre = None
        self.current_track = track

    def set_genre_mode(self, genre: str, track: Dict) -> None:
        """
        Set state for genre playback.
        
        Args:
            genre: Canonicalized genre name
            track: Full track dictionary
        """
        self.mode = "genre"
        self.genre = genre
        self.artist = None
        self.current_track = track

    def set_random_mode(self, track: Dict) -> None:
        """
        Set state for random playback.
        
        Args:
            track: Full track dictionary
        """
        self.mode = "random"
        self.artist = None
        self.genre = None
        self.current_track = track

    def reset(self) -> None:
        """Reset to empty state."""
        self.mode = None
        self.artist = None
        self.genre = None
        self.current_track = None

    def __repr__(self) -> str:
        """Debug representation."""
        return (
            f"PlaybackState(mode={self.mode}, "
            f"artist={self.artist}, "
            f"genre={self.genre}, "
            f"current_track={self.current_track.get('name') if self.current_track else None})"
        )


# Global singleton instance
_playback_state_instance: Optional[PlaybackState] = None


def get_playback_state() -> PlaybackState:
    """
    Get or create the global playback state instance.
    
    Returns:
        PlaybackState singleton
    """
    global _playback_state_instance
    if _playback_state_instance is None:
        _playback_state_instance = PlaybackState()
    return _playback_state_instance


def reset_playback_state() -> None:
    """Reset global playback state."""
    state = get_playback_state()
    state.reset()
