"""
MUSIC PLAYER MODULE

Music playback for ARGO supporting both local files and Jellyfin media server.

Uses either music_index.py (local) or jellyfin_provider.py (server).

Features:
- Persistent JSON catalog (fast startup for local)
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
- MUSIC_INDEX_FILE (env): Path to JSON catalog (local only)

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

import os
import logging
import random
import threading
import json
from pathlib import Path
from typing import Optional, List, Dict

# Import music index for catalog and filtering
from core.music_index import get_music_index
from core.playback_state import get_playback_state

# ============================================================================
# LOGGER
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

MUSIC_ENABLED = os.getenv("MUSIC_ENABLED", "false").lower() == "true"
"""Enable/disable music playback entirely."""

MUSIC_SOURCE = os.getenv("MUSIC_SOURCE", "local").lower()
"""Music source: 'local' or 'jellyfin'"""

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".m4a"}
"""Supported audio file extensions."""


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

GENRE_ADJACENCY = {
    # Punk adjacency: rock-related genres
    "punk": ["rock", "new wave", "alternative"],
    
    # Rock adjacency
    "rock": ["punk", "metal", "classic rock"],
    
    # Metal adjacency
    "metal": ["rock", "punk", "alternative"],
    
    # Pop adjacency
    "pop": ["soul", "r&b", "indie"],
    
    # Rap adjacency
    "rap": ["soul", "r&b", "funk"],
    
    # Jazz adjacency
    "jazz": ["soul", "blues", "funk"],
    
    # Soul adjacency
    "soul": ["r&b", "jazz", "funk"],
    
    # Blues adjacency
    "blues": ["jazz", "soul", "folk"],
    
    # Country adjacency
    "country": ["folk", "americana", "bluegrass"],
    
    # Folk adjacency
    "folk": ["country", "blues", "singer-songwriter"],
    
    # Electronic adjacency
    "electronic": ["house", "techno", "ambient"],
    
    # House adjacency
    "house": ["electronic", "techno", "funk"],
    
    # Indie adjacency
    "indie": ["alternative", "pop", "rock"],
    
    # Alternative adjacency
    "alternative": ["indie", "rock", "punk"],
}
"""Adjacent genres for fallback (ordered by proximity)."""

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

def get_adjacent_genres(genre: str) -> List[str]:
    """
    Get adjacent genres for fallback when primary genre has no tracks.
    
    Args:
        genre: Genre name
        
    Returns:
        List of adjacent genres (ordered by proximity)
    """
    genre_normalized = normalize_genre(genre)
    return GENRE_ADJACENCY.get(genre_normalized, [])


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
        self.current_process: Optional[object] = None
        self.is_playing = False
        self.current_track: Dict = {}  # Track metadata (artist, song, path, etc.)

        if not MUSIC_ENABLED:
            logger.info("[ARGO] Music disabled (MUSIC_ENABLED=false)")
            return

        # ===== JELLYFIN MODE =====
        if MUSIC_SOURCE == "jellyfin":
            try:
                from core.jellyfin_provider import get_jellyfin_provider
                self.jellyfin_provider = get_jellyfin_provider()
                # Pre-load library for searches
                tracks = self.jellyfin_provider.load_music_library()
                logger.info(f"[ARGO] Jellyfin connected: {len(tracks)} tracks")
                return
            except Exception as e:
                logger.error(f"[ARGO] Jellyfin connection failed: {e}")
                self.jellyfin_provider = None
                return
        
        # ===== LOCAL MODE =====
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
            if not self.jellyfin_provider.tracks:
                if output_sink:
                    output_sink.speak("No music available in Jellyfin.")
                return False
            
            import random
            track = random.choice(self.jellyfin_provider.tracks)
            announcement = self._build_announcement(track)
            
            # For Jellyfin, we stream instead of playing local files
            result = self._play_jellyfin_track(track, announcement, output_sink)
            return result
        
        # ===== LOCAL MODE =====
        if not self.index or not self.index.tracks:
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
        if not MUSIC_ENABLED or not self.index:
            return False

        # Normalize genre (apply aliases)
        genre_normalized = normalize_genre(genre)
        
        # Try primary genre
        tracks = self.index.filter_by_genre(genre_normalized)
        used_genre = genre_normalized
        
        # Try adjacent genres if primary not found
        if not tracks:
            for adjacent in get_adjacent_genres(genre_normalized):
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
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to artist mode
            playback_state = get_playback_state()
            playback_state.set_artist_mode(artist, track)
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
        1. Try LLM-based extraction (handles natural language like "play loud rock from the 70s")
        2. Fallback to regex-based extraction (fast for structured patterns like "metal from 1984")
        3. Use advanced server-side filtering with extracted parameters
        4. Final fallback to simple keyword search
        
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
        
        # ===== JELLYFIN MODE =====
        if self.jellyfin_provider:
            # Try to extract structured parameters from keyword using hybrid approach
            parsed = None
            
            # Step 1: Try LLM-based extraction for natural language (might be slower but more flexible)
            logger.info(f"[ARGO] Attempting LLM extraction for: '{keyword}'")
            llm_extracted = self._extract_metadata_with_llm(keyword)
            if llm_extracted and (llm_extracted.get("year") or llm_extracted.get("genre") or llm_extracted.get("artist") or llm_extracted.get("song")):
                logger.info(f"[ARGO] LLM extraction succeeded: {llm_extracted}")
                parsed = llm_extracted
            
            # Step 2: Fallback to regex-based extraction if LLM didn't provide useful data
            if not parsed or not (parsed.get("year") or parsed.get("genre") or parsed.get("artist") or parsed.get("song")):
                logger.info(f"[ARGO] Using regex extraction (LLM didn't extract metadata)")
                parsed = self._parse_music_keyword(keyword)
            
            # CASCADING FALLBACK SEARCH: Optimistic but forgiving
            # LLM might hallucinate year/genre/song, so try multiple strategies
            
            tracks = []
            
            # Attempt 1: Strict search with all extracted parameters
            if parsed.get("artist") or parsed.get("genre") or parsed.get("year"):
                logger.info(f"[ARGO] Search Attempt 1 (Strict): artist={parsed.get('artist')}, genre={parsed.get('genre')}, year={parsed.get('year')}")
                tracks = self.jellyfin_provider.advanced_search(
                    query_text=None,
                    year=parsed.get("year"),
                    genre=parsed.get("genre"),
                    artist=parsed.get("artist")
                )
                if tracks:
                    logger.info(f"[ARGO] Strict search succeeded: {len(tracks)} tracks found")
            
            # Attempt 2: Search by Song Name if extracted (song-specific search)
            if not tracks and parsed.get("song"):
                logger.info(f"[ARGO] Search Attempt 2 (Song): song='{parsed.get('song')}'")
                tracks = self.jellyfin_provider.advanced_search(
                    query_text=parsed.get("song"),
                    year=None,
                    genre=None,
                    artist=None
                )
                if tracks:
                    logger.info(f"[ARGO] Song search succeeded: {len(tracks)} tracks found")
            
            # Attempt 3: Drop Year/Genre (common LLM hallucinations) - keep Artist and Song
            if not tracks and (parsed.get("year") or parsed.get("genre")):
                logger.info(f"[ARGO] Search Attempt 3 (Relaxed): Dropping Year/Genre, keeping artist={parsed.get('artist')}")
                tracks = self.jellyfin_provider.advanced_search(
                    query_text=None,
                    year=None,  # Drop unreliable year
                    genre=None,  # Drop unreliable genre
                    artist=parsed.get("artist")
                )
                if tracks:
                    logger.info(f"[ARGO] Relaxed search succeeded: {len(tracks)} tracks found")
            
            # Attempt 4: Search by Artist ONLY (user's core intent if they mentioned an artist)
            if not tracks and parsed.get("artist"):
                logger.info(f"[ARGO] Search Attempt 4 (Artist Only): artist={parsed.get('artist')}")
                tracks = self.jellyfin_provider.advanced_search(
                    query_text=None,
                    artist=parsed.get("artist")
                )
                if tracks:
                    logger.info(f"[ARGO] Artist-only search succeeded: {len(tracks)} tracks found")
            
            # Attempt 5: Simple keyword search (fallback to keyword matching)
            if not tracks:
                logger.info(f"[ARGO] Search Attempt 5 (Keyword): keyword='{keyword}'")
                tracks = self.jellyfin_provider.search_by_keyword(keyword)
                if tracks:
                    logger.info(f"[ARGO] Keyword search succeeded: {len(tracks)} tracks found")
            
            # Final fallback: No music found
            if not tracks:
                logger.info(f"[ARGO] All search attempts failed for '{keyword}'")
                if output_sink:
                    output_sink.speak(f"No music found for '{keyword}' in Jellyfin.")
                return False
            
            import random
            track = random.choice(tracks)
            announcement = self._build_announcement(track)
            return self._play_jellyfin_track(track, announcement, output_sink)
        
        # ===== LOCAL MODE =====
        if not self.index:
            if output_sink:
                output_sink.speak("I couldn't find any music.")
            return False

        # Generic keyword search (token-based)
        tracks = self.index.filter_by_keyword(keyword)
        if not tracks:
            if output_sink:
                output_sink.speak(f"No music found for '{keyword}'.")
            return False

        track = random.choice(tracks)
        track_path = track.get("path", "")
        announcement = self._build_announcement(track)
        
        result = self.play(track_path, announcement, output_sink, track_data=track)
        if result:
            # Set playback state to random mode (keyword play is exploratory)
            playback_state = get_playback_state()
            playback_state.set_random_mode(track)
        return result

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
                timeout=3
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
            self.is_playing = True
            return True

        except Exception as e:
            logger.error(f"[ARGO] Error starting playback: {e}")
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
            jellyfin_id = track.get("jellyfin_id")
            if not jellyfin_id:
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
            self.is_playing = True
            
            # Play via URL streaming
            try:
                # Use pydub which knows where ffmpeg is installed
                from pydub import AudioSegment
                from pydub.playback import play
                from pydub.utils import which as pydub_which
                import requests
                import tempfile
                import threading
                
                logger.debug("[ARGO] Downloading stream for pydub playback...")
                
                # Check if ffmpeg is available (pydub needs it)
                if not pydub_which("ffmpeg"):
                    logger.debug("[ARGO] ffmpeg not found for pydub, trying fallback...")
                    raise ImportError("ffmpeg not found")
                
                # Download stream to temp MP3 file
                response = requests.get(stream_url, stream=True, timeout=30)
                if response.status_code != 200:
                    logger.error(f"[ARGO] Failed to download stream: {response.status_code}")
                    return False
                
                # Save to temp file explicitly as MP3
                bytes_written = 0
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                    tmp_path = tmp.name
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            tmp.write(chunk)
                            bytes_written += len(chunk)
                
                logger.debug(f"[ARGO] Downloaded {bytes_written} bytes to {tmp_path}")
                
                # Play async in background
                def play_stream():
                    try:
                        logger.debug("[ARGO] Loading audio with pydub...")
                        audio = AudioSegment.from_mp3(tmp_path)
                        logger.debug(f"[ARGO] Playing {len(audio)}ms of audio")
                        play(audio)
                        logger.debug("[ARGO] Playback complete")
                    except Exception as e:
                        logger.debug(f"[ARGO] pydub playback error: {e}")
                    finally:
                        try:
                            import os
                            os.unlink(tmp_path)
                            logger.debug(f"[ARGO] Cleaned up temp file")
                        except:
                            pass
                
                play_thread = threading.Thread(target=play_stream, daemon=True)
                play_thread.start()
                logger.info("[ARGO] Playback thread started")
                return True
                
            except Exception as e:
                logger.debug(f"[ARGO] pydub streaming failed: {e}")
            
            # Fallback: Try external players
            import subprocess
            import shutil
            
            # Try ffplay first
            ffplay_path = shutil.which("ffplay")
            if ffplay_path:
                logger.debug("[ARGO] Using ffplay for streaming")
                subprocess.Popen(
                    [ffplay_path, "-nodisp", "-autoexit", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
            
            # Try mpv
            mpv_path = shutil.which("mpv")
            if mpv_path:
                logger.debug("[ARGO] Using mpv for streaming")
                subprocess.Popen(
                    [mpv_path, "--no-video", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
            
            # Try VLC
            vlc_path = shutil.which("vlc")
            if vlc_path:
                logger.debug("[ARGO] Using VLC for streaming")
                subprocess.Popen(
                    [vlc_path, "--play-and-exit", stream_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                return True
            
            logger.error("[ARGO] No audio player found. Install ffmpeg, mpv, or VLC.")
            return False
                
        except Exception as e:
            logger.error(f"[ARGO] Jellyfin playback error: {e}")
            self.is_playing = False
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
        # Always reset playback state, regardless of is_playing flag
        playback_state = get_playback_state()
        playback_state.reset()
        
        if not self.is_playing:
            return

        try:
            if self.current_process:
                # For simpleaudio
                if hasattr(self.current_process, "stop"):
                    self.current_process.stop()
                # For ffplay, process will be killed by parent
            self.is_playing = False
            self.current_track = {}
            
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
