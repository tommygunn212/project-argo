"""
MUSIC PLAYER MODULE

Music playback for ARGO supporting both local files and Jellyfin media server.

Uses either Jellyfin ingestion or local catalog for playback.

Features:
- SQLite-backed lookup for deterministic matching
- Genre filtering (punk, classic rock, glam, etc.)
- Keyword search (artist, album, track names)
- Fire-and-forget playback (non-blocking)
- Voice interrupt support
- Jellyfin server streaming support
- LLM-based metadata extraction for natural language requests
- Minimal logging

Configuration:
- MUSIC_ENABLED (env): Enable/disable music entirely
- MUSIC_SOURCE (env): 'local' or 'jellyfin'
- MUSIC_DIR (env): Path to music directory (local only)
- JELLYFIN_URL (env): Jellyfin server address
- JELLYFIN_API_KEY (env): Jellyfin authentication token
- JELLYFIN_USER_ID (env): Jellyfin user ID
- MUSIC_DB_FILE (env): Path to SQLite database (optional)

File types supported:
- .mp3
- .wav
- .flac
- .m4a

Extraction Methods:
- Regex-based (fast, structured patterns like "metal from 1984")
- LLM-based (flexible, natural language like "play loud rock from the 70s")
- Hybrid fallback (tries LLM first, falls back to regex)

No complex playlists, no metadata obsession.
"""

# AUDIO PATH STABLE
# Verified working. Do not modify without reproduced issue + logs.

import os
import logging
import random
import threading
import json
import time
import re
import subprocess
from pathlib import Path
from typing import Optional, List, Dict

from core.policy import (
    LLM_EXTRACT_TIMEOUT_SECONDS,
    AUDIO_PLAYBACK_TIMEOUT_SECONDS,
    AUDIO_STOP_TIMEOUT_SECONDS,
    AUDIO_WATCHDOG_SECONDS,
)
from core.watchdog import Watchdog
from core.config import get_config, MUSIC_DB_PATH
from core.database import MusicDatabase, music_db_exists
from core.jellyfin_ingest import ingest_jellyfin_library

# Import music index for catalog and filtering
from core.music_index import get_music_index
from core.playback_state import get_playback_state
from core.audio_owner import get_audio_owner

# ============================================================================
# LOGGER
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

def _get_env_bool(name: str):
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return value.lower() == "true"


def _is_music_enabled() -> bool:
    env_value = _get_env_bool("MUSIC_ENABLED")
    if env_value is not None:
        return env_value
    config = get_config()
    return bool(config.get("music.enabled", True))


def _get_music_source() -> str:
    env_value = os.getenv("MUSIC_SOURCE")
    if env_value:
        return env_value.lower()
    config = get_config()
    return str(config.get("music.source", "local")).lower()


def _get_music_backend(music_source: str) -> str:
    config = get_config()
    backend = config.get("music_backend")
    if not backend:
        backend = config.get("music.backend")
    if backend:
        return str(backend).lower()
    return "sqlite" if music_source == "jellyfin" else "json"


MUSIC_ENABLED = _is_music_enabled()
"""Enable/disable music playback entirely."""

MUSIC_SOURCE = _get_music_source()
"""Music source: 'local' or 'jellyfin'"""

MUSIC_BACKEND = _get_music_backend(MUSIC_SOURCE)
"""Music backend: 'sqlite' or 'json'"""

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".m4a"}
"""Supported audio file extensions."""

MUSIC_FIXES = {
    # Common transcription errors (Whisper misheard)
    "ramen": "Ramones",          # Ramen (food) → Ramones (band)
    "ramon": "Ramones",          # Ramon (name) → Ramones
    "the ramon": "The Ramones",  # The Ramon → The Ramones
    "trexx": "T. Rex",           # Trexx → T. Rex
    "t-rex": "T. Rex",           # T-Rex (with hyphen) → T. Rex
    "the doors": "The Doors",    # Capitalize properly
    "pink floyd": "Pink Floyd",  # Capitalize properly
    "david bowie": "David Bowie", # Capitalize properly
}
"""Correction map for common artist name transcription errors."""

KNOWN_ARTISTS = {
    "generation x",
    "ramones",
    "the ramones",
    "t rex",
    "t. rex",
    "the clash",
    "live",
    "yes",
    "boston",
}
"""Known artist names that bypass LLM extraction. Artist sovereignty - no guessing."""


# ============================================================================
# GENRE MAPPING AND ADJACENCY
# ============================================================================

GENRE_ALIASES = {
    # Rock variants
    "rock music": "rock",
    "classic rock": "rock",
    "hard rock": "rock",
    "alternative rock": "alternative",
    "alt rock": "alternative",
    "glam rock": "glam",
    
    # Hip-hop/Rap
    "hip hop": "rap",
    "hiphop": "rap",
    "hip-hop": "rap",
    "rap music": "rap",
    
    # Electronic
    "electronic music": "electronic",
    "house music": "house",
    "techno music": "techno",
    "edm": "electronic",
    
    # Pop/Soul/RB
    "pop music": "pop",
    "rnb": "r&b",
    "rhythm and blues": "r&b",
    "soul music": "soul",
    
    # Jazz/Blues
    "jazz music": "jazz",
    "blues music": "blues",
    "cool jazz": "jazz",
    
    # Country/Folk
    "country music": "country",
    "folk music": "folk",
    "americana": "folk",
    
    # Metal/Punk
    "metal music": "metal",
    "heavy metal": "metal",
    "punk rock": "punk",
    "punk music": "punk",
    
    # Indie/Alternative
    "indie music": "indie",
    "alternative music": "alternative",
}
"""Genre aliases and synonyms for better matching."""

ARTIST_FILLER_WORDS = {
    "play", "me", "a", "the", "some", "good", "song", "music", "from", "by"
}

def normalize_genre(genre: str) -> str:
    """
    Normalize genre name to canonical form using aliases.
    
    Examples:
    - "hip hop" → "rap"
    - "rock music" → "rock"
    - "punk" → "punk" (already canonical)
    
    Args:
        genre: Raw genre input
        
    Returns:
        Canonical genre name
    """
    genre_lower = genre.lower().strip()
    # Check if it's an alias
    return GENRE_ALIASES.get(genre_lower, genre_lower)


def normalize_title_for_match(title: str) -> str:
    if not title:
        return ""
    cleaned = title.lower()
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    cleaned = re.sub(r"\b(a|an|the)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.endswith("s"):
        cleaned = cleaned[:-1]
    return cleaned


def normalize_artist_query(artist: str) -> str:
    if not artist:
        return ""
    tokens = re.findall(r"[A-Za-z0-9']+", artist)
    cleaned_tokens = [token for token in tokens if token.lower() not in ARTIST_FILLER_WORDS]
    return " ".join(cleaned_tokens).strip()

    


# ============================================================================
# MUSIC PLAYER CLASS
# ============================================================================

class MusicPlayer:
    """
    Music playback manager supporting both local files and Jellyfin.
    
    Behavior:
    - Local mode: Uses persistent JSON index (fast startup, no rescans)
    - Jellyfin mode: Queries live Jellyfin server via API
    - Supports genre filtering (punk, classic rock, etc.)
    - Supports keyword search (artist, album, track names)
    - Plays random track on voice command
    - Fire-and-forget playback (non-blocking)
    - Announces what's playing
    """

    def __init__(self):
        """Initialize music player and load index (local or Jellyfin)."""
        self.index = None
        self.jellyfin_provider = None
        self.current_process: Optional[subprocess.Popen] = None
        self.playback_mode: Optional[str] = None
        self._is_playing_flag = False
        self.current_track: Dict = {}  # Track metadata (artist, song, path, etc.)
        self._audio_owner = get_audio_owner()
        self._db = MusicDatabase()
        self._music_backend = MUSIC_BACKEND

        if not MUSIC_ENABLED:
            logger.info("[ARGO] Music disabled (MUSIC_ENABLED=false)")
            return

        # ===== JELLYFIN MODE =====
        if MUSIC_SOURCE == "jellyfin":
            if not self._music_backend:
                self._music_backend = "sqlite"
            if self._music_backend != "sqlite":
                raise RuntimeError("Jellyfin requires music_backend=sqlite")
            try:
                from core.jellyfin_provider import get_jellyfin_provider
                self.jellyfin_provider = get_jellyfin_provider()
                if not music_db_exists(MUSIC_DB_PATH):
                    ingest_jellyfin_library()
                self._db.validate_schema()
                logger.info("[ARGO] Jellyfin connected")
                self._db.set_artist_sovereignty(KNOWN_ARTISTS, rank=10)
                return
            except Exception as e:
                logger.error(f"[ARGO] Jellyfin connection failed: {e}")
                self.jellyfin_provider = None
                raise RuntimeError(f"SQLite backend unavailable: {e}")
        
        # ===== LOCAL MODE =====
        if not self._music_backend:
            self._music_backend = "json"
        if self._music_backend != "json":
            raise RuntimeError("Local music requires music_backend=json")

        try:
            self.index = get_music_index()
            track_count = len(self.index.tracks) if self.index.tracks else 0
            logger.info(f"[ARGO] Music index loaded: {track_count} tracks")
        except Exception as e:
            logger.error(f"[ARGO] Error loading music index: {e}")
            self.index = None

    def play_random(self, output_sink=None) -> bool:
        """
        Play a random track from the library (local or Jellyfin).
        
        Args:
            output_sink: Optional output sink to announce track name
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED:
            if output_sink:
                output_sink.speak("Music is not enabled.")
            return False
        
        # ===== JELLYFIN MODE =====
        if self.jellyfin_provider:
            if not music_db_exists(MUSIC_DB_PATH):
                if output_sink:
                    output_sink.speak("Music library not indexed yet.")
                return False
            track = self._db.random_track()
            if not track:
                if output_sink:
                    output_sink.speak("Your music library is empty or unavailable.")
                return False

            announcement = self._build_announcement(track)
            return self._play_jellyfin_track(track, announcement, output_sink)
        
        # ===== LOCAL MODE =====
        if not self.index or not self.index.tracks:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        track = self.index.get_random_track()
        if not track:
            if output_sink:
                output_sink.speak("Your music library is empty or unavailable.")
            return False

        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to random mode
            playback_state = get_playback_state()
            playback_state.set_random_mode(track)
        return result

    def play_by_genre(self, genre: str, output_sink=None) -> bool:
        """
        Play a random track from specified genre with adjacent fallback.
        
        Behavior:
        1. Normalize genre (apply aliases)
        2. Try primary genre
        3. If not found, try adjacent genres (in priority order)
        4. No error speaking - caller handles that
        
        Args:
            genre: Genre name (canonical or alias)
            output_sink: Optional output sink to announce track (only on success)
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED:
            return False

        if self.jellyfin_provider:
            if not music_db_exists(MUSIC_DB_PATH):
                if output_sink:
                    output_sink.speak("Music library not indexed yet.")
                return False
            genre_normalized = normalize_genre(genre)
            tracks = self._db.query_tracks(genre=genre_normalized, limit=200, intent=f"play {genre}")
            used_genre = genre_normalized

            if not tracks:
                for adjacent in self._get_adjacent_genres(genre_normalized):
                    adjacent_normalized = normalize_genre(adjacent)
                    tracks = self._db.query_tracks(genre=adjacent_normalized, limit=200, intent=f"play {genre}")
                    if tracks:
                        used_genre = adjacent_normalized
                        logger.info(
                            f"[ARGO] Genre '{genre_normalized}' not found, using adjacent: '{used_genre}'"
                        )
                        break

            if not tracks:
                logger.warning(f"[ARGO] No tracks found for genre '{genre}' or adjacent genres")
                return False

            track = tracks[0]
            announcement = self._build_announcement(track)
            result = self._play_jellyfin_track(track, announcement, output_sink)
            if result:
                playback_state = get_playback_state()
                playback_state.set_genre_mode(used_genre, track)
            return result

        if not self.index:
            return False

        # Normalize genre (apply aliases)
        genre_normalized = normalize_genre(genre)
        
        # Try primary genre
        tracks = self.index.filter_by_genre(genre_normalized)
        used_genre = genre_normalized
        
        # Try adjacent genres if primary not found
        if not tracks:
            for adjacent in self._get_adjacent_genres(genre_normalized):
                adjacent_normalized = normalize_genre(adjacent)
                tracks = self.index.filter_by_genre(adjacent_normalized)
                if tracks:
                    used_genre = adjacent_normalized
                    logger.info(f"[ARGO] Genre '{genre_normalized}' not found, using adjacent: '{used_genre}'")
                    break
        
        # No tracks found even with adjacent fallback
        if not tracks:
            logger.warning(f"[ARGO] No tracks found for genre '{genre}' or adjacent genres")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to genre mode (use normalized genre)
            playback_state = get_playback_state()
            playback_state.set_genre_mode(used_genre, track)
        return result

    def play_by_artist(self, artist: str, output_sink=None) -> bool:
        """
        Play a random track by specified artist.
        
        Args:
            artist: Artist name
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        artist_cleaned = normalize_artist_query(artist)
        if not artist_cleaned:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        if self.jellyfin_provider:
            if not music_db_exists(MUSIC_DB_PATH):
                if output_sink:
                    output_sink.speak("Music library not indexed yet.")
                return False
            tracks = self._db.query_tracks(artist=artist_cleaned, limit=200, intent=f"play {artist_cleaned}")
            if not tracks:
                tracks = self._db.query_tracks_artist_like(artist_cleaned, limit=200, intent=f"play {artist_cleaned}")
            if not tracks:
                if output_sink:
                    output_sink.speak(f"No music found for '{artist_cleaned}'.")
                return False

            track = tracks[0]
            announcement = self._build_announcement(track)
            result = self._play_jellyfin_track(track, announcement, output_sink)
            if result:
                playback_state = get_playback_state()
                playback_state.set_artist_mode(artist_cleaned, track)
            return result

        if not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        tracks = self.index.filter_by_artist(artist_cleaned)
        if not tracks:
            artist_lower = artist_cleaned.lower()
            tracks = [
                t for t in self.index.tracks
                if t.get("artist") and artist_lower in t.get("artist", "").lower()
            ]
            if tracks:
                logger.info(f"[ARGO] Music artist LIKE match: {artist_cleaned} ({len(tracks)} tracks)")
        if not tracks:
            if output_sink:
                output_sink.speak(f"No tracks by {artist_cleaned} found.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to artist mode
            playback_state = get_playback_state()
            playback_state.set_artist_mode(artist_cleaned, track)
        return result

    def play_by_song(self, song: str, output_sink=None) -> bool:
        """
        Play a specific song by name.
        
        Args:
            song: Song name
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        if self.jellyfin_provider:
            if not music_db_exists(MUSIC_DB_PATH):
                if output_sink:
                    output_sink.speak("Music library not indexed yet.")
                return False
            tracks = self._db.query_tracks(title=song, limit=50, intent=f"play {song}")
            if not tracks:
                tracks = self._db.query_tracks_soft_title(song, limit=200, intent=f"play {song}")
            if not tracks:
                if output_sink:
                    output_sink.speak(f"Song {song} not found.")
                return False

            track = tracks[0]
            announcement = self._build_announcement(track)
            result = self._play_jellyfin_track(track, announcement, output_sink)
            if result:
                playback_state = get_playback_state()
                if track.get("artist"):
                    playback_state.set_artist_mode(track.get("artist"), track)
            return result

        if not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        tracks = self.index.filter_by_song(song)
        if not tracks:
            normalized = normalize_title_for_match(song)
            if normalized:
                tracks = [
                    t for t in self.index.tracks
                    if normalize_title_for_match(t.get("song", "")) == normalized
                ]
                if tracks:
                    logger.info(f"[ARGO] Music song soft match: {song} ({len(tracks)} tracks)")
        if not tracks:
            if output_sink:
                output_sink.speak(f"Song {song} not found.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to artist mode (song play is artist-oriented)
            playback_state = get_playback_state()
            if track.get("artist"):
                playback_state.set_artist_mode(track.get("artist"), track)
        return result

    def play_by_keyword(self, keyword: str, output_sink=None) -> bool:
        """
        Play a random track matching keyword search (fallback after artist/song/genre).
        
        Supports both local index and Jellyfin.
        
        For Jellyfin: Uses hybrid extraction approach:
        1. Check for artist sovereignty (KNOWN_ARTISTS) - bypass LLM if match
        2. Try LLM-based extraction (handles natural language like "play loud rock from the 70s")
        3. Fallback to regex-based extraction (fast for structured patterns like "metal from 1984")
        4. Use advanced server-side filtering with extracted parameters
        5. Final fallback to simple keyword search
        
        Args:
            keyword: Search term (partial keyword match)
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False otherwise
        """
        if not MUSIC_ENABLED:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False
        
        # ===== JELLYFIN MODE (SQLite lookup) =====
        if self.jellyfin_provider:
            if not music_db_exists(MUSIC_DB_PATH):
                if output_sink:
                    output_sink.speak("Music library not indexed yet.")
                return False
            fields = self._extract_query_fields(keyword)
            tracks = self._db.query_tracks(
                title=fields.get("song"),
                artist=fields.get("artist"),
                genre=fields.get("genre"),
                year_start=fields.get("year_start"),
                year_end=fields.get("year_end"),
                limit=200,
                intent=f"play {keyword}",
            )

            if not tracks:
                logger.info(f"music_unresolved_phrase = \"{keyword}\"")
                if output_sink:
                    output_sink.speak(f"No music found for '{keyword}'.")
                return False

            track = tracks[0]
            announcement = self._build_announcement(track)
            return self._play_jellyfin_track(track, announcement, output_sink)
        
        # ===== LOCAL MODE =====
        if not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        resolution_tracks = self.index.filter_by_keyword(keyword)
        if not resolution_tracks:
            logger.info(f"music_unresolved_phrase = \"{keyword}\"")
            if output_sink:
                output_sink.speak(f"No music found for '{keyword}'.")
            return False

        track = random.choice(resolution_tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to random mode (keyword play is exploratory)
            playback_state = get_playback_state()
            playback_state.set_random_mode(track)
        return result

    def _interpret_music_intent(self, keyword: str) -> Optional[Dict]:
        """
        LLM metadata parser (interpret only). Returns artist/song/album/era.
        """
        try:
            import requests

            ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
            prompt = (
                "You are a music metadata parser. Convert the user's yell into a JSON search object.\n"
                "User: 'play that heroes song by bowie'\n"
                "Output: {\"artist\": \"David Bowie\", \"song\": \"Heroes\", \"album\": null, \"era\": null}\n"
                "User: 'play old metallica'\n"
                "Output: {\"artist\": \"Metallica\", \"song\": null, \"album\": null, \"era\": \"early\"}\n"
                f"User: '{keyword}'\n"
                "Output (JSON only):"
            )

            response = requests.post(
                f"{ollama_endpoint}/api/generate",
                json={
                    "model": os.getenv("OLLAMA_MODEL", "argo:latest"),
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.1,
                    "top_p": 0.5,
                    "top_k": 40,
                    "num_predict": 120,
                },
                timeout=LLM_EXTRACT_TIMEOUT_SECONDS,
            )

            if response.status_code != 200:
                return None

            result_json = response.json()
            response_text = result_json.get("response", "").strip()
            if not response_text:
                return None

            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = response_text[start:end]
                extracted = json.loads(json_str)
                return extracted
        except Exception as e:
            logger.debug(f"[LLM] Intent extraction error: {e}")
            return None

    def _extract_metadata_with_llm(self, keyword: str) -> Optional[Dict]:
        """
        Use LLM to extract music metadata from natural language.
        
        IMPORTANT: Extract ONLY what the user explicitly mentioned.
        DO NOT hallucinate or guess artist/song names.
        
        This handles more complex, conversational requests like:
        - "Play something loud from the 70s"
        - "Play early Alice Cooper"
        - "Give me some chill reggae"
        - "Play heavy metal from 1984"
        
        The LLM extracts: artist, song, genre, year (or null if not mentioned)
        
        Args:
            keyword: Voice command from user
            
        Returns:
            Dictionary with extracted fields: artist, song, genre, year
            or None if extraction fails or returns empty
        """
        try:
            import requests
            
            # Get Ollama endpoint
            ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
            
            # Create metadata extraction prompt
            # CRITICAL: Prevent common hallucinations
            extraction_prompt = f"""Extract ONLY explicitly mentioned music metadata.

RULES:
1. artist: Only if user said an artist name (e.g., "Elton John", "Guns and Roses")
2. song: Only if user said a song name (e.g., "Bohemian Rhapsody")
3. genre: Only if user said a genre (rock, metal, jazz, pop, etc)
4. year: Only if user said a year or decade (1984, 80s, 1970s)

CRITICAL RULE: If user ONLY says an artist name, set everything else to null!
- "play Elton John" → {{"artist": "Elton John", "song": null, "genre": null, "year": null}}
- "play Guns and Roses" → {{"artist": "Guns and Roses", "song": null, "genre": null, "year": null}}

DO NOT guess the song, year, or genre!
DO NOT invent metadata that wasn't mentioned!

GOOD EXAMPLES:
1. "play Elton John" → {{"artist": "Elton John", "song": null, "genre": null, "year": null}}
2. "play rock from 1980" → {{"artist": null, "song": null, "genre": "Rock", "year": 1980}}
3. "play Bohemian Rhapsody" → {{"artist": null, "song": "Bohemian Rhapsody", "genre": null, "year": null}}
4. "play something from the 70s" → {{"artist": null, "song": null, "genre": null, "year": 1970}}

BAD EXAMPLES (NEVER):
- "play Elton John" → {{"artist": "Elton John", "song": "Tiny Dancer", ...}} ✗ HALLUCINATED!
- "play Elton John" → {{"artist": "Elton John", "year": 1970, ...}} ✗ HALLUCINATED!
- "play rock" → {{"genre": "Rock", "artist": "Led Zeppelin", ...}} ✗ HALLUCINATED!

Request: "{keyword}"
Response (JSON ONLY):"""
            
            # Call Ollama's generate endpoint directly with fast settings
            response = requests.post(
                f"{ollama_endpoint}/api/generate",
                json={
                    "model": os.getenv("OLLAMA_MODEL", "argo:latest"),
                    "prompt": extraction_prompt,
                    "stream": False,
                    "temperature": 0.1,  # Low temp for consistent extraction
                    "top_p": 0.5,        # Reduce variety
                    "top_k": 40,         # Limit token choices
                    "num_predict": 100,  # Keep response short
                },
                timeout=LLM_EXTRACT_TIMEOUT_SECONDS
            )
            
            if response.status_code != 200:
                logger.debug(f"[LLM] Extraction failed (status {response.status_code})")
                return None
            
            result_json = response.json()
            response_text = result_json.get("response", "").strip()
            
            if not response_text:
                logger.debug(f"[LLM] Empty response from model")
                return None
            
            # Parse JSON from response
            # LLM might include explanatory text, so extract JSON object
            try:
                # Try to find JSON object in response
                start = response_text.find('{')
                end = response_text.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = response_text[start:end]
                    
                    # Remove any duplicate closing braces
                    while json_str.count('}') > json_str.count('{'):
                        json_str = json_str[:-2] + '}'
                    
                    extracted = json.loads(json_str)
                    
                    # Clean up year field (convert "1970s" to 1970, "early 80s" to 1980, etc.)
                    year_raw = extracted.get("year")
                    if year_raw:
                        year_clean = self._normalize_year_from_llm(year_raw)
                        extracted["year"] = year_clean
                    
                    logger.debug(f"[LLM] Extraction successful: {extracted}")
                    return extracted
            except json.JSONDecodeError as je:
                logger.debug(f"[LLM] Failed to parse JSON from: {response_text} (error: {je})")
                return None
        
        except requests.exceptions.Timeout:
            logger.debug(f"[LLM] Extraction timed out")
            return None
        except Exception as e:
            logger.debug(f"[LLM] Extraction error: {e}")
            return None
    
    def _normalize_year_from_llm(self, year_str: str) -> Optional[int]:
        """
        Normalize year strings from LLM into integers.
        
        Handles:
        - "1984" → 1984
        - "1970s" → 1970
        - "70s" → 1970
        - "early 80s" → 1980
        - "late 1980s" → 1980
        - "early" → None (too vague)
        """
        import re
        
        if not year_str:
            return None
        
        # Safe conversion: year_str might be int from LLM (e.g., {"year": 1990})
        year_str = str(year_str).lower().strip()
        
        # Extract 4-digit year
        four_digit = re.search(r'(19|20)\d{2}', year_str)
        if four_digit:
            return int(four_digit.group())
        
        # Extract 2-digit decade (e.g., "70s", "80s")
        two_digit = re.search(r'(\d{2})s?', year_str)
        if two_digit:
            year_int = int(two_digit.group(1))
            # Convert 2-digit to 4-digit (70 → 1970, 20 → 2020)
            return 1900 + year_int if year_int > 50 else 2000 + year_int
        
        return None

    def _parse_music_keyword(self, keyword: str) -> Dict:
        """
        Parse keyword to extract structured parameters (year, genre, artist).
        
        Supports patterns like:
        - "metal from 1984" → {genre: "Metal", year: 1984}
        - "alice cooper" → {artist: "alice cooper", query: "alice cooper"}
        - "punk rock" → {genre: "Punk Rock"}
        - "classic rock from 1980" → {genre: "Rock", year: 1980}
        - "heavy metal" → {genre: "Metal"}
        
        Args:
            keyword: Search term from user
            
        Returns:
            Dictionary with extracted parameters: year, genre, artist, query
        """
        import re
        
        result = {
            "year": None,
            "genre": None,
            "artist": None,
            "query": keyword  # Default to full keyword as query
        }
        
        keyword_lower = keyword.lower()
        keyword_clean = keyword_lower
        
        # Pattern 1: Extract year (4 digits like 1980, 2000)
        year_match = re.search(r'\b(19|20)\d{2}\b', keyword_clean)
        if year_match:
            result["year"] = int(year_match.group())
            # Remove year from keyword for further processing
            keyword_clean = re.sub(r'\b(19|20)\d{2}\b', '', keyword_clean).strip()
        
        # Pattern 2: Extract "from YYYY" or "from the YYYY" or "from 80s"
        from_match = re.search(r'from\s+(?:the\s+)?(?:early|late|mid\s+)?(\d{2,4}s?)', keyword_clean)
        if from_match:
            year_text = from_match.group(1)
            year_digit_match = re.search(r'(\d{2,4})', year_text)
            if year_digit_match:
                year_str = year_digit_match.group(1)
                if len(year_str) == 2:
                    # Convert "80s" → 1980, "84" → 1984
                    result["year"] = 1900 + int(year_str) if int(year_str) > 50 else 2000 + int(year_str)
                else:
                    result["year"] = int(year_str)
            keyword_clean = re.sub(r'from\s+(?:the\s+)?(?:early|late|mid\s+)?(?:\d{2,4}s?)', '', keyword_clean).strip()
        
        # Map keywords to canonical Jellyfin genres (check longer strings first)
        genre_keywords = [
            # Longer compound genres first (to avoid partial matches)
            ("classic rock", "Rock"),
            ("hard rock", "Rock"),
            ("punk rock", "Punk Rock"),
            ("alternative rock", "Alternative Rock"),
            ("heavy metal", "Metal"),
            ("black metal", "Metal"),
            ("rhythm and blues", "R&B"),
            ("hip hop", "Hip-Hop"),
            
            # Single-word genres
            ("metal", "Metal"),
            ("rock", "Rock"),
            ("punk", "Punk"),
            ("pop", "Pop"),
            ("soul", "Soul"),
            ("r&b", "R&B"),
            ("rnb", "R&B"),
            ("jazz", "Jazz"),
            ("blues", "Blues"),
            ("country", "Country"),
            ("folk", "Folk"),
            ("americana", "Americana"),
            ("electronic", "Electronic"),
            ("house", "House"),
            ("techno", "Techno"),
            ("edm", "Electronic"),
            ("rap", "Rap"),
            ("hiphop", "Hip-Hop"),
            ("indie", "Indie"),
            ("alternative", "Alternative"),
            ("glam", "Glam Rock"),
            ("new wave", "New Wave"),
        ]
        
        # Check if keyword contains a recognized genre (longer matches first)
        for genre_key, genre_value in genre_keywords:
            if genre_key in keyword_clean:
                result["genre"] = genre_value
                # Remove genre from keyword for artist extraction
                keyword_clean = keyword_clean.replace(genre_key, "").strip()
                break
        
        # Remove common filler words and cleanup
        # NOTE: Do NOT include "and" - many band names use it (Guns and Roses, Hootie and the Blowfish)
        filler_words = ["play", "some", "music", "song", "songs", "from", "the"]
        words = keyword_clean.split()
        words = [w for w in words if w not in filler_words and len(w) > 0]
        keyword_clean = " ".join(words).strip()
        
        # If we have a remaining keyword, treat as artist or query
        if keyword_clean:
            result["artist"] = keyword_clean
            result["query"] = keyword_clean
        
        logger.debug(f"[ARGO] Parsed keyword '{keyword}' → year={result['year']}, genre={result['genre']}, artist={result['artist']}")
        
        return result

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

    def _acquire_music_audio(self) -> bool:
        try:
            self._audio_owner.acquire("MUSIC")
            return True
        except Exception as e:
            logger.warning(f"[ARGO] Music blocked: {e}")
            return False

    def _release_music_audio(self) -> None:
        try:
            self._audio_owner.release("MUSIC")
        except Exception:
            pass

    def preflight(self) -> Optional[Dict]:
        if self._music_backend == "sqlite" and not music_db_exists(MUSIC_DB_PATH):
            return {"status": "blocked", "reason": "music_not_indexed"}
        return None

    def _extract_year_range_from_text(self, text: str) -> tuple[Optional[int], Optional[int]]:
        import re

        text_lower = text.lower()
        decade_match = re.search(r"\b(\d{2})s\b", text_lower)
        four_decade_match = re.search(r"\b(19|20)\d{2}s\b", text_lower)
        year_match = re.search(r"\b(19|20)\d{2}\b", text_lower)

        if four_decade_match:
            year = int(four_decade_match.group()[:4])
            return year, year + 9
        if decade_match:
            decade = int(decade_match.group(1))
            year = 1900 + decade if decade >= 50 else 2000 + decade
            return year, year + 9
        if year_match:
            year = int(year_match.group())
            return year, year
        return None, None

    def _extract_jellyfin_id_from_path(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        if path.startswith("jellyfin://"):
            return path.split("jellyfin://", 1)[1]
        return None

    def _get_adjacent_genres(self, genre: str) -> List[str]:
        genre_normalized = normalize_genre(genre)
        try:
            return self._db.get_adjacent_genres(genre_normalized)
        except Exception:
            return []

    def _extract_query_fields(self, keyword: str) -> Dict:
        keyword_lower = keyword.lower().strip()

        if keyword_lower in KNOWN_ARTISTS:
            return {
                "artist": keyword,
                "song": None,
                "genre": None,
                "year_start": None,
                "year_end": None,
            }

        extracted = self._extract_metadata_with_llm(keyword)
        if not extracted:
            extracted = self._parse_music_keyword(keyword)

        artist = extracted.get("artist") if extracted else None
        song = extracted.get("song") if extracted else None
        genre = extracted.get("genre") if extracted else None
        year = extracted.get("year") if extracted else None

        if genre:
            genre = normalize_genre(str(genre))

        year_start, year_end = self._extract_year_range_from_text(keyword)
        if year is not None and year_start is None:
            year_start = int(year)
            year_end = int(year)

        return {
            "artist": artist,
            "song": song,
            "genre": genre,
            "year_start": year_start,
            "year_end": year_end,
        }

    def play(self, track_path: str, track_name: str, output_sink=None, track_data: Dict = None) -> bool:
        """
        Play a specific track.
        
        Args:
            track_path: Absolute path to audio file
            track_name: Human-readable track name (for announcement)
            output_sink: Optional output sink to announce track
            track_data: Optional full track metadata dictionary
            
        Returns:
            True if playback started, False otherwise
        """
        if not os.path.exists(track_path):
            logger.error(f"[ARGO] Track not found: {track_path}")
            return False

        try:
            if not self._acquire_music_audio():
                return False
            # Announce what's playing
            if output_sink:
                output_sink.speak(f"Playing: {track_name}")

            # Store current track metadata
            self.current_track = track_data or {
                "path": track_path,
                "name": track_name
            }

            # Start playback in background thread (fire-and-forget)
            thread = threading.Thread(
                target=self._play_background,
                args=(track_path,),
                daemon=True
            )
            thread.start()

            logger.info(f"[ARGO] Playing music: {track_path}")
            self._is_playing_flag = True
            self.playback_mode = "music"
            return True

        except Exception as e:
            logger.error(f"[ARGO] Error starting playback: {e}")
            self._release_music_audio()
            return False

    def play_next(self, output_sink=None) -> bool:
        """
        Play next track in current playback mode.
        
        Uses playback_state to determine what to play next:
        - If mode="artist": Play another track by same artist
        - If mode="genre": Play another track in same genre
        - If mode="random": Play another random track
        - If no mode set: Do nothing (return False)
        
        Args:
            output_sink: Optional output sink to announce track
            
        Returns:
            True if playback started, False if no mode or error
        """
        playback_state = get_playback_state()
        
        if not playback_state.mode:
            logger.warning("[ARGO] play_next() called but no playback mode set")
            if output_sink:
                output_sink.speak("No music is playing.")
            return False
        
        # Determine what to play next based on current mode
        if playback_state.mode == "artist":
            artist = playback_state.artist
            logger.info(f"[ARGO] Next: Playing another track by {artist}")
            return self.play_by_artist(artist, output_sink)
        
        elif playback_state.mode == "genre":
            genre = playback_state.genre
            logger.info(f"[ARGO] Next: Playing another track in {genre}")
            return self.play_by_genre(genre, output_sink)
        
        else:  # mode == "random"
            logger.info("[ARGO] Next: Playing random track")
            return self.play_random(output_sink)

    def _play_jellyfin_track(self, track: Dict, announcement: str, output_sink=None) -> bool:
        """
        Play a track from Jellyfin via streaming.
        
        Args:
            track: Track dictionary from Jellyfin
            announcement: What to say before playing
            output_sink: Optional output sink for announcement
            
        Returns:
            True if playback started, False otherwise
        """
        try:
            jellyfin_id = track.get("jellyfin_id") or track.get("jellyfin_item_id")
            if not jellyfin_id:
                jellyfin_id = self._extract_jellyfin_id_from_path(track.get("path"))
            if not jellyfin_id:
                return False

            if not self._acquire_music_audio():
                return False
            
            # Get streaming URL from Jellyfin
            stream_url = self.jellyfin_provider.get_play_url(jellyfin_id)
            
            # Announce what's playing
            if output_sink and announcement:
                output_sink.speak(announcement)
            
            logger.info(f"[ARGO] Playing from Jellyfin: {track.get('artist')} - {track.get('song')}")
            logger.info(f"[ARGO] Stream URL: {stream_url}")
            
            # Update playback state
            playback_state = get_playback_state()
            playback_state.set_artist_mode(track.get("artist", "Unknown"), track)
            
            # Update current track
            self.current_track = track
            self._is_playing_flag = True
            self.playback_mode = "music"
            
            # Direct streaming with ffplay (no download, no temp file, instant start)
            import shutil

            def _monitor_process(proc: subprocess.Popen) -> None:
                try:
                    proc.wait()
                except Exception:
                    pass
                finally:
                    self._is_playing_flag = False
                    self.playback_mode = None
                    self.current_process = None
                    self._release_music_audio()
            
            try:
                ffplay_path = shutil.which("ffplay")
                if not ffplay_path:
                    logger.debug("[ARGO] ffplay not found, trying fallback players...")
                    raise FileNotFoundError("ffplay not found")
                
                logger.debug(f"[ARGO] Starting ffplay streaming from {stream_url[:80]}...")
                
                # Launch ffplay with streaming flags for instant playback
                self.current_process = subprocess.Popen(
                    [
                        ffplay_path,
                        "-nodisp",           # Don't display video window
                        "-noborder",         # No window border (save resources)
                        "-autoexit",         # Exit when done
                        "-probesize", "32",  # Fast stream probing
                        "-analyzeduration", "0",  # Don't analyze duration
                        "-infbuf",           # CRITICAL: Infinite buffer for network stability
                        stream_url
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"[ARGO] ffplay process started (PID: {self.current_process.pid})")
                threading.Thread(target=_monitor_process, args=(self.current_process,), daemon=True).start()
                return True
            
            except Exception as e:
                logger.debug(f"[ARGO] ffplay streaming failed: {e}")
            
            # Fallback: Try mpv
            mpv_path = shutil.which("mpv")
            if mpv_path:
                logger.debug("[ARGO] Using mpv for streaming")
                self.current_process = subprocess.Popen(
                    [mpv_path, "--no-video", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"[ARGO] mpv process started (PID: {self.current_process.pid})")
                threading.Thread(target=_monitor_process, args=(self.current_process,), daemon=True).start()
                return True
            
            # Try mpv
            mpv_path = shutil.which("mpv")
            if mpv_path:
                logger.debug("[ARGO] Using mpv for streaming")
                self.current_process = subprocess.Popen(
                    [mpv_path, "--no-video", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"[ARGO] mpv process started (PID: {self.current_process.pid})")
                threading.Thread(target=_monitor_process, args=(self.current_process,), daemon=True).start()
                return True
            
            # Try VLC
            vlc_path = shutil.which("vlc")
            if vlc_path:
                logger.debug("[ARGO] Using VLC for streaming")
                self.current_process = subprocess.Popen(
                    [vlc_path, "--play-and-exit", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                logger.info(f"[ARGO] vlc process started (PID: {self.current_process.pid})")
                threading.Thread(target=_monitor_process, args=(self.current_process,), daemon=True).start()
                return True
            
            logger.error("[ARGO] No audio player found. Install ffmpeg, mpv, or VLC.")
            self._release_music_audio()
            return False
                
        except Exception as e:
            logger.error(f"[ARGO] Jellyfin playback error: {e}")
            self._is_playing_flag = False
            self.playback_mode = None
            self.current_process = None
            self._release_music_audio()
            return False

    def _play_background(self, track_path: str) -> None:
        """Play audio in background thread."""
        try:
            with Watchdog("AUDIO", AUDIO_WATCHDOG_SECONDS) as wd:
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
                    import shutil
                    
                    ffplay_path = shutil.which("ffplay")
                    if ffplay_path:
                        logger.info(f"[ARGO] Playing via ffplay: {ffplay_path}")
                        self.current_process = subprocess.Popen(
                            [ffplay_path, "-nodisp", "-autoexit", track_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self.playback_mode = "music"
                        logger.info(f"[ARGO] ffplay process started (PID: {self.current_process.pid})")
                        try:
                            self.current_process.wait(timeout=AUDIO_PLAYBACK_TIMEOUT_SECONDS)
                        finally:
                            self.current_process = None
                            self.playback_mode = None
                        logger.info(f"[ARGO] Playback completed via ffplay")
                        return
                except Exception as e:
                    logger.debug(f"[ARGO] ffplay not available: {e}")
                
                # If all methods failed
                logger.error(f"[ARGO] No audio playback method available (install pygame or ffmpeg)")
            
            if wd.triggered:
                logger.warning("[WATCHDOG] AUDIO exceeded watchdog threshold")
                
        except Exception as e:
            logger.error(f"[ARGO] Playback error: {type(e).__name__}: {e}")
        finally:
            self._is_playing_flag = False
            self.playback_mode = None
            self._release_music_audio()
            logger.info("[ARGO] Music playback stopped")

    def is_playing(self) -> bool:
        return self.current_process is not None and self.current_process.poll() is None

    def stop(self) -> None:
        """Stop current playback immediately (idempotent). No graceful fade, just STOP."""
        # Always reset playback state, regardless of is_playing flag
        playback_state = get_playback_state()
        playback_state.reset()
        
        if not self.is_playing():
            return

        try:
            if self.current_process and self.current_process.poll() is None:
                logger.info("[ARGO] Stopping music playback")
                self.current_process.terminate()
                try:
                    self.current_process.wait(timeout=1)
                except Exception:
                    self.current_process.kill()
                self.current_process = None
                self.playback_mode = None
                logger.info("[ARGO] ffplay terminated")

            self._is_playing_flag = False
            self.current_track = {}
            self._release_music_audio()

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
