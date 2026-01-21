"""
MUSIC STATUS QUERY

Read-only query for current playback status.

Returns what's currently playing without:
- Stopping music
- Changing state
- Triggering interrupts
- LLM involvement

Uses existing PlaybackState singleton as source of truth.
"""

from typing import Optional
from core.playback_state import get_playback_state


def query_music_status() -> str:
    """
    Get human-readable status of current playback.
    
    Returns:
        Status string to speak to user
        
    Behavior:
        - If nothing playing: "Nothing is playing."
        - If song+artist: "You're listening to <song> by <artist>."
        - If only song: "You're listening to <song>."
        - If only artist: "You're listening to <artist>."
        - Fallback: "Music is playing."
    """
    playback_state = get_playback_state()
    
    # Check if music is currently playing
    if playback_state.current_track is None:
        return "Nothing is playing."
    
    # Extract track information
    song = playback_state.current_track.get("song")
    artist = playback_state.current_track.get("artist")
    
    # Construct response based on what information is available
    if song and artist:
        return f"You're listening to {song} by {artist}."
    elif song:
        return f"You're listening to {song}."
    elif artist:
        return f"You're listening to {artist}."
    else:
        # Fallback if no metadata available
        return "Music is playing."
