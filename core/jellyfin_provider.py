"""
Jellyfin Music Provider

Fetches music library from Jellyfin media server instead of scanning local files.
Uses Jellyfin's REST API to query music, artists, albums, and playlists.

Advantages over local scanning:
- Real-time access (no index rebuild needed)
- Metadata already standardized (Jellyfin maintains it)
- Can access from multiple machines
- Automatic library updates

Configuration (set in .env):
  JELLYFIN_URL=http://localhost:8096
  JELLYFIN_API_KEY=your_api_key
  JELLYFIN_USER_ID=your_user_id
"""

import os
import requests
import logging
import hashlib
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================================
# JELLYFIN CONFIGURATION
# ============================================================================

JELLYFIN_URL = os.getenv("JELLYFIN_URL", "http://localhost:8096").rstrip("/")
JELLYFIN_API_KEY = os.getenv("JELLYFIN_API_KEY", "")
JELLYFIN_USER_ID = os.getenv("JELLYFIN_USER_ID", "")

# Music library parent types in Jellyfin
MUSIC_LIBRARY_TYPES = {"MusicArtist", "MusicAlbum", "Audio"}


# ============================================================================
# JELLYFIN MUSIC PROVIDER
# ============================================================================

class JellyfinMusicProvider:
    """Fetch music from Jellyfin server via REST API."""

    def __init__(self):
        """Initialize Jellyfin provider."""
        self.url = JELLYFIN_URL
        self.api_key = JELLYFIN_API_KEY
        self.user_id = JELLYFIN_USER_ID
        self.tracks: List[Dict] = []
        self.session = requests.Session()
        
        # Validate credentials
        if not all([self.url, self.api_key, self.user_id]):
            msg = "[JELLYFIN] Missing credentials. Set JELLYFIN_URL, JELLYFIN_API_KEY, JELLYFIN_USER_ID in .env"
            logger.error(msg)
            raise ValueError(msg)
    
    def _api_call(self, endpoint: str, params: dict = None) -> Optional[Dict]:
        """Make authenticated API call to Jellyfin."""
        if params is None:
            params = {}
        
        url = f"{self.url}{endpoint}"
        
        # Add auth header (Jellyfin requires this)
        headers = {
            "X-MediaBrowser-Token": self.api_key,
            "Accept": "application/json"
        }
        
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"[JELLYFIN] API error: {e}")
            return None
    
    def load_music_library(self) -> List[Dict]:
        """
        Fetch all music tracks from Jellyfin library.
        
        Stores tracks in self.tracks for later searches.
        
        Returns:
            List of track dictionaries
        """
        logger.info(f"[JELLYFIN] Connecting to {self.url}...")
        
        # Query all audio items (songs)
        params = {
            "userId": self.user_id,
            "includeItemTypes": "Audio",
            "recursive": "true",
            "fields": "PrimaryImageAspectRatio,SortName,BasicSyncInfo",
            "limit": 10000,  # Pagination: max items per request
            "startIndex": 0
        }
        
        result = self._api_call("/Items", params)
        
        if not result:
            logger.error("[JELLYFIN] Failed to fetch library")
            return []
        
        items = result.get("Items", [])
        logger.info(f"[JELLYFIN] Found {len(items)} audio items")
        
        # Convert to track records
        tracks = []
        for item in items:
            track = self._build_track_record(item)
            if track:
                tracks.append(track)
        
        # Store for later use
        self.tracks = tracks
        
        logger.info(f"[JELLYFIN] Indexed {len(tracks)} valid tracks")
        return tracks
    
    def _build_track_record(self, item: Dict) -> Optional[Dict]:
        """
        Convert Jellyfin item to track record.
        
        Args:
            item: Jellyfin audio item JSON
            
        Returns:
            Track dictionary or None
        """
        try:
            # Required fields
            item_id = item.get("Id")
            name = item.get("Name")
            artist_name = item.get("Artists", [None])[0] if item.get("Artists") else None
            album = item.get("Album")
            year = item.get("ProductionYear")
            
            if not (item_id and name):
                return None
            
            # Extract metadata
            artist = artist_name or "Unknown Artist"
            song = name
            genre = (item.get("Genres", [None])[0] or "").lower() if item.get("Genres") else None
            
            # Build tokens for search
            tokens = self._tokenize(song, artist, album, genre)
            
            # Generate stable ID
            track_id = hashlib.md5(item_id.encode()).hexdigest()[:16]
            
            return {
                "id": track_id,
                "jellyfin_id": item_id,  # Store original Jellyfin ID
                "path": f"jellyfin://{item_id}",  # Virtual path for Jellyfin
                "filename": f"{song}.mp3",  # Virtual filename
                "name": song.lower(),
                "artist": artist,
                "song": song,
                "album": album,
                "year": year,
                "tokens": tokens,
                "genre": genre,
                "ext": ".mp3"  # All assumed to be audio
            }
        
        except Exception as e:
            logger.debug(f"[JELLYFIN] Error building track record: {e}")
            return None
    
    def _tokenize(self, song: str, artist: str, album: Optional[str], genre: Optional[str]) -> List[str]:
        """Generate search tokens from metadata."""
        tokens = set()
        
        # Split fields into words
        if song:
            tokens.update(song.lower().split())
        if artist:
            tokens.update(artist.lower().split())
        if album:
            tokens.update(album.lower().split())
        if genre:
            tokens.update(genre.lower().split())
        
        # Remove common filler words
        filler = {"the", "a", "an", "and", "or", "of", "in", "on"}
        tokens = {t for t in tokens if t not in filler and len(t) > 2}
        
        return sorted(list(tokens))
    
    def search_by_artist(self, artist: str) -> List[Dict]:
        """Search for tracks by artist name."""
        return [t for t in self.tracks if t.get("artist", "").lower() == artist.lower()]
    
    def search_by_song(self, song: str) -> List[Dict]:
        """Search for tracks by song name."""
        return [t for t in self.tracks if t.get("song", "").lower() == song.lower()]
    
    def search_by_keyword(self, keyword: str) -> List[Dict]:
        """Search for tracks by keyword (token match)."""
        keyword_lower = keyword.lower()
        return [t for t in self.tracks if keyword_lower in t.get("tokens", [])]
    
    def advanced_search(self, query_text: str = None, year: int = None, genre: str = None, 
                       artist: str = None) -> List[Dict]:
        """
        Advanced search using Jellyfin server-side filters.
        
        This queries the Jellyfin API with specific filters instead of searching
        the local track cache. Much faster for complex queries.
        
        Args:
            query_text: Search term (artist name, song name, etc.)
            year: Production year (e.g., 1984)
            genre: Genre filter (e.g., "Metal", "Punk")
            artist: Exact or partial artist name match
            
        Returns:
            List of matching tracks from server
            
        Examples:
            - advanced_search(artist="Alice Cooper")
            - advanced_search(year=1984, genre="Metal")
            - advanced_search(query_text="Broken Train", genre="Rock")
        """
        params = {
            "userId": self.user_id,
            "includeItemTypes": "Audio",
            "recursive": "true",
            "fields": "PrimaryImageAspectRatio,SortName,Genres,ProductionYear",
            "limit": 500,  # Return more results for advanced queries
        }
        
        # Add search term if provided
        if query_text:
            params["searchTerm"] = query_text
        
        # Add year filter if provided
        if year:
            params["Years"] = str(year)
        
        # Add genre filter if provided (Jellyfin uses exact match for genres)
        if genre:
            params["Genres"] = genre
        
        # Add artist filter if provided (searches artist name)
        if artist:
            params["Artists"] = artist
        
        logger.info(f"[JELLYFIN] Advanced search: query={query_text}, year={year}, genre={genre}, artist={artist}")
        
        result = self._api_call("/Items", params)
        
        if not result:
            logger.warning(f"[JELLYFIN] Advanced search returned no results")
            return []
        
        items = result.get("Items", [])
        logger.info(f"[JELLYFIN] Advanced search found {len(items)} items")
        
        # Convert to track records
        tracks = []
        for item in items:
            track = self._build_track_record(item)
            if track:
                tracks.append(track)
        
        return tracks
    
    def get_play_url(self, jellyfin_id: str) -> str:
        """Get streaming URL for a track (force MP3 format for compatibility)."""
        # Force transcode to MP3 for universal player compatibility
        # Container=mp3 ensures Jellyfin transcodes to MP3 regardless of source format
        return f"{self.url}/Audio/{jellyfin_id}/stream.mp3?X-MediaBrowser-Token={self.api_key}&Container=mp3"


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_jellyfin_provider: Optional[JellyfinMusicProvider] = None


def get_jellyfin_provider() -> JellyfinMusicProvider:
    """Get or create Jellyfin provider instance."""
    global _jellyfin_provider
    
    if _jellyfin_provider is None:
        _jellyfin_provider = JellyfinMusicProvider()
    
    return _jellyfin_provider
