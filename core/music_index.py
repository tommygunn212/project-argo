"""
MUSIC INDEX AUTHORITATIVE v1.1.0 (Hardened)

Persistent JSON catalog of local music library.

Responsibilities:
- Scan directory recursively
- Extract genre from folder names (using GENRE_ALIASES)
- Extract metadata using ID3 tags (PRIMARY)
- Fallback to Folder/Filename heuristics (SECONDARY)
- Tokenize for keyword search
- Save/load JSON for fast startup
- Filter by genre or keyword
- NO audio decoding
- NO ffmpeg dependency

Hardening Features:
- Validates ID3 tags (strips whitespace, checks for "Unknown", "Track 01")
- Centralized normalization in _clean_tag
- Graceful degradation if tags missing
- Zero network I/O

Data plumbing only.

Startup behavior:
- IF MUSIC_ENABLED=true:
  - Check MUSIC_DIR exists (fail fast if not)
  - Load existing index OR build new one
  - Save to MUSIC_INDEX_FILE
  - Log exactly one message: "loaded" or "created"
- IF MUSIC_ENABLED=false:
  - Skip all initialization
  - Return empty index
"""

import os
import json
import logging
import hashlib
import re
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# Try to import mutagen for ID3 support
try:
    from mutagen.easyid3 import EasyID3
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

logger = logging.getLogger(__name__)

# ============================================================================
# GENRE ALIASES (CANONICAL - DO NOT MODIFY)
# ============================================================================

GENRE_ALIASES = {
    # Rock family
    "rock": "rock",
    "classic rock": "classic rock",
    "classic_rock": "classic rock",
    "hard rock": "hard rock",
    "arena rock": "arena rock",

    # Punk family
    "punk": "punk",
    "punk rock": "punk",
    "rock punk": "punk",
    "post punk": "post-punk",

    # Glam
    "glam": "glam rock",
    "glam rock": "glam rock",

    # Metal
    "metal": "metal",
    "heavy metal": "metal",
    "thrash": "metal",

    # Alt / Indie
    "alternative": "alternative",
    "alt": "alternative",
    "indie": "indie",
    "grunge": "grunge",
    "experimental": "experimental",

    # Electronic
    "electronic": "electronic",
    "electronica": "electronic",
    "ambient": "ambient",
    "techno": "electronic",
    "house": "electronic",

    # Other genres
    "jazz": "jazz",
    "blues": "blues",
    "classical": "classical",
    "folk": "folk",
    "country": "country",
    "disco": "disco",
    "dance": "dance",
    "latin": "latin",
    "ethnic": "ethnic",
    "reggae": "reggae",
    "comedy": "comedy",
    "kids": "kids",
    "soundtrack": "soundtrack"
}

SUPPORTED_FORMATS = {".mp3", ".wav", ".flac", ".m4a"}
FILLER_WORDS = {"the", "a", "an", "some", "track", "music"}
INVALID_TAG_VALUES = {"unknown", "unknown artist", "unknown album", "track", "title"}


# ============================================================================
# MUSIC INDEX CLASS
# ============================================================================

class MusicIndex:
    """Persistent JSON catalog of local music library."""

    def __init__(self, music_dir: str, index_file: str):
        """
        Initialize music index.
        
        Args:
            music_dir: Path to music directory (e.g., I:\My Music)
            index_file: Path to JSON index file (e.g., data/music_index.json)
            
        Raises:
            ValueError: If MUSIC_ENABLED=true but music_dir doesn't exist
        """
        self.music_dir = music_dir
        self.index_file = index_file
        self.tracks: List[Dict] = []
        self.no_music_available = False
        
        # Validate music directory exists if music is enabled
        music_enabled = os.getenv("MUSIC_ENABLED", "false").lower() == "true"
        if music_enabled and not os.path.exists(self.music_dir):
            msg = f"[ARGO] MUSIC_ENABLED=true but MUSIC_DIR not found: {self.music_dir}"
            logger.error(msg)
            raise ValueError(msg)

    def is_empty(self) -> bool:
        """Return True if the index contains no tracks."""
        return not bool(self.tracks)
        
    def load_or_create(self) -> Dict:
        """
        Load existing index or create new one.
        
        Returns:
            Index dictionary with metadata and tracks
        """
        # Try to load existing index
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    index = json.load(f)
                logger.info(f"[ARGO] Music index loaded: {len(index.get('tracks', []))} tracks")
                self.tracks = index.get("tracks", [])
                self.no_music_available = not bool(self.tracks)
                return index
            except Exception as e:
                logger.warning(f"[ARGO] Failed to load index: {e}. Rescanning...")
        
        # Create new index
        logger.info(f"[ARGO] Scanning music directory: {self.music_dir}")
        self.tracks = self._scan_directory()
        self.no_music_available = not bool(self.tracks)
        
        # Build index document
        index = {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "music_dir": self.music_dir,
            "track_count": len(self.tracks),
            "tracks": self.tracks
        }
        
        # Save to JSON
        try:
            os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2)
            logger.info(f"[ARGO] Music index created: {len(self.tracks)} tracks")
        except Exception as e:
            logger.warning(f"[ARGO] Failed to save index: {e}")
        
        return index
    
    def _scan_directory(self) -> List[Dict]:
        """
        Recursively scan music directory.
        
        Returns:
            List of track dictionaries
        """
        tracks = []
        
        if not os.path.exists(self.music_dir):
            logger.warning(f"[ARGO] Music directory not found: {self.music_dir}")
            return tracks
        
        try:
            for root, dirs, files in os.walk(self.music_dir):
                for filename in files:
                    # Check format
                    if not any(filename.lower().endswith(fmt) for fmt in SUPPORTED_FORMATS):
                        continue
                    
                    full_path = os.path.join(root, filename)
                    
                    # Build track record
                    track = self._build_track_record(full_path)
                    if track:
                        tracks.append(track)
        
        except Exception as e:
            logger.error(f"[ARGO] Scan error: {e}")
        
        return tracks
    
    def _clean_tag(self, value: str) -> Optional[str]:
        """Normalize and validate a metadata tag."""
        if not value:
            return None
        
        # Strip whitespace
        cleaned = value.strip()
        if not cleaned:
            return None
            
        lower = cleaned.lower()
        
        # Check against generic placeholders
        if lower in INVALID_TAG_VALUES:
            return None
            
        # Check for "Track XX" pattern
        if re.match(r'^track\s*\d+$', lower):
            return None
            
        return cleaned

    def _build_track_record(self, full_path: str) -> Optional[Dict]:
        """
        Build a single track record using hardened ID3 strategy.
        
        Strategy:
        1. ID3 Tags (Primary Truth)
        2. Folder/Filename (Fallback)
        
        Args:
            full_path: Absolute path to audio file
            
        Returns:
            Track dictionary or None if error
        """
        try:
            path_obj = Path(full_path)
            filename = path_obj.name
            ext = path_obj.suffix.lower()
            name = path_obj.stem.lower()
            
            # Initialize Metadata
            artist = None
            song = None
            genre = None

            # 1. Try ID3 Tags (Primary)
            # We trust Mutagen if available and format is supported
            if HAS_MUTAGEN and ext == ".mp3":
                try:
                    audio = EasyID3(full_path)
                    
                    # Extract and Validate Artist
                    if audio.get('artist'):
                        # Take first artist, clean it
                        artist = self._clean_tag(audio['artist'][0])
                            
                    # Extract and Validate Title
                    if audio.get('title'):
                        # Take title, clean it
                        song = self._clean_tag(audio['title'][0])
                            
                except Exception:
                    # Tag reading failed (corrupt header, missing tags, etc.)
                    # Silently proceed to fallback strategies
                    pass
            
            # 2. Fallbacks (If ID3 missing or invalid)
            
            # Genre: Always prefer folder hierarchy (User's folders are curated "Rock", "Pop", etc.)
            # ID3 genres are notoriously messy ("Rock/Pop", "Indie-Rock", "My Faves")
            genre = self._extract_genre(full_path)
            
            # Artist: Fallback to folder assumption
            if not artist:
                artist = self._extract_artist(full_path)
            
            # Song: Fallback to filename cleaning
            if not song:
                song = self._extract_song(full_path)
            
            # 3. Tokenize (Using final confirmed values)
            # This ensures search matches the actual metadata we settled on
            tokens = self._tokenize(full_path, genre, artist, song)
            
            # 4. Generate stable ID
            track_id = hashlib.md5(full_path.lower().encode()).hexdigest()[:16]
            
            return {
                "id": track_id,
                "path": full_path,
                "filename": filename,
                "name": name,
                "artist": artist,
                "song": song,
                "tokens": tokens,
                "genre": genre,
                "ext": ext
            }
        
        except Exception as e:
            logger.debug(f"[ARGO] Error building track record for {full_path}: {e}")
            return None
    
    def _extract_genre(self, full_path: str) -> Optional[str]:
        """
        Extract genre from folder names using GENRE_ALIASES.
        
        Args:
            full_path: Absolute path to audio file
            
        Returns:
            Canonical genre or None
        """
        try:
            # Get relative path from music_dir
            rel_path = os.path.relpath(full_path, self.music_dir)
            folder_names = rel_path.split(os.sep)[:-1]  # Exclude filename
            
            # Check each folder name against aliases
            for folder_name in folder_names:
                normalized = folder_name.lower().replace("_", " ").strip()
                
                # Remove punctuation
                normalized = re.sub(r'[^\w\s-]', '', normalized)
                
                # Check if matches alias
                if normalized in GENRE_ALIASES:
                    return GENRE_ALIASES[normalized]
            
            # No match found
            return None
        
        except Exception as e:
            logger.debug(f"[ARGO] Genre extraction error: {e}")
            return None
    
    def _extract_artist(self, full_path: str) -> Optional[str]:
        """
        Extract artist from folder hierarchy.
        
        Heuristic: Usually the direct parent folder (or last folder before tracks).
        
        Examples:
          I:\Music\Punk\Sex Pistols\song.mp3 -> "Sex Pistols"
          I:\Music\Classic Rock\Pink Floyd\The Wall\song.mp3 -> "Pink Floyd"
          I:\Music\Rock\song.mp3 -> None (no artist folder)
        
        Args:
            full_path: Absolute path to audio file
            
        Returns:
            Artist name or None
        """
        try:
            # Get relative path from music_dir
            rel_path = os.path.relpath(full_path, self.music_dir)
            folders = rel_path.split(os.sep)[:-1]  # Exclude filename
            
            if len(folders) < 2:
                # Not enough depth (e.g., Music\song.mp3)
                return None
            
            # Assume the last folder (before filename) is artist
            # Skip if it looks like an album folder (check for common album keywords)
            potential_artist = folders[-1]
            
            # If it's a known album/collection folder, skip it
            album_indicators = {"album", "albums", "compilations", "singles", "live", "remaster", "remix"}
            if potential_artist.lower() in album_indicators:
                # Try parent folder instead
                if len(folders) >= 2:
                    potential_artist = folders[-2]
            
            # Return artist (cleaned up)
            artist_clean = potential_artist.strip()
            if artist_clean and artist_clean.lower() not in album_indicators:
                return artist_clean
            
            return None
        
        except Exception as e:
            logger.debug(f"[ARGO] Artist extraction error: {e}")
            return None
    
    def _extract_song(self, full_path: str) -> Optional[str]:
        """
        Extract song name from filename.
        
        Removes track numbers, extension, common separators.
        
        Examples:
          "01 - Never Mind The Bollocks.mp3" -> "Never Mind The Bollocks"
          "01. In The Flesh.mp3" -> "In The Flesh"
          "Track 1 - Song Name.mp3" -> "Song Name"
          "song_name.mp3" -> "song_name"
        
        Args:
            full_path: Absolute path to audio file
            
        Returns:
            Song name or None
        """
        try:
            path_obj = Path(full_path)
            filename = path_obj.stem  # Filename without extension
            
            # Remove leading track numbers and common separators
            # Pattern: digits followed by separator (-, ., space)
            cleaned = re.sub(r'^[\d\s]+[-._\s]+', '', filename, flags=re.IGNORECASE)
            
            # Remove trailing stuff like "(remix)", "[live]", "(remaster)"
            # Don't do this - user might search for it
            
            # Normalize whitespace
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            
            if cleaned and len(cleaned) > 1:
                return cleaned
            
            return None
        
        except Exception as e:
            logger.debug(f"[ARGO] Song extraction error: {e}")
            return None
    
    def _tokenize(self, full_path: str, genre: Optional[str], artist: Optional[str] = None, song: Optional[str] = None) -> List[str]:
        """
        Tokenize for keyword search.
        
        Args:
            full_path: Absolute path to audio file
            genre: Genre (if extracted)
            artist: Artist name (if extracted)
            song: Song name (if extracted)
            
        Returns:
            List of search tokens
        """
        tokens = set()
        
        try:
            # Filename (without extension)
            path_obj = Path(full_path)
            name = path_obj.stem.lower()
            tokens.update(name.split())
            
            # Artist (high weight - added separately)
            if artist:
                artist_lower = artist.lower()
                tokens.update(artist_lower.split())
            
            # Song (high weight - added separately)
            if song:
                song_lower = song.lower()
                tokens.update(song_lower.split())
            
            # Folder names
            rel_path = os.path.relpath(full_path, self.music_dir)
            folder_names = rel_path.split(os.sep)[:-1]
            
            for folder in folder_names:
                folder_lower = folder.lower()
                tokens.update(folder_lower.split())
            
            # Genre
            if genre:
                tokens.update(genre.lower().split())
            
            # Remove punctuation and filler words
            cleaned_tokens = []
            for token in tokens:
                # Remove punctuation
                cleaned = re.sub(r'[^\w-]', '', token)
                if cleaned and cleaned not in FILLER_WORDS:
                    cleaned_tokens.append(cleaned)
            
            return sorted(list(set(cleaned_tokens)))
        
        except Exception as e:
            logger.debug(f"[ARGO] Tokenization error: {e}")
            return []
    
    def filter_by_genre(self, genre: str) -> List[Dict]:
        """
        Filter tracks by genre (canonical).
        
        Args:
            genre: Canonical genre name
            
        Returns:
            List of matching tracks
        """
        genre_lower = genre.lower()
        matches = [
            t for t in self.tracks 
            if t.get("genre") and t.get("genre", "").lower() == genre_lower
        ]
        
        if matches:
            logger.info(f"[ARGO] Music genre match: {genre} ({len(matches)} tracks)")
        
        return matches
    
    def filter_by_artist(self, artist: str) -> List[Dict]:
        """
        Filter tracks by artist name.
        
        Args:
            artist: Artist name (case-insensitive)
            
        Returns:
            List of matching tracks
        """
        artist_lower = artist.lower()
        matches = [
            t for t in self.tracks
            if t.get("artist") and t.get("artist", "").lower() == artist_lower
        ]
        
        if matches:
            logger.info(f"[ARGO] Music artist match: {artist} ({len(matches)} tracks)")
        
        return matches
    
    def filter_by_song(self, song: str) -> List[Dict]:
        """
        Filter tracks by song name.
        
        Args:
            song: Song name (case-insensitive)
            
        Returns:
            List of matching tracks
        """
        song_lower = song.lower()
        matches = [
            t for t in self.tracks
            if t.get("song") and t.get("song", "").lower() == song_lower
        ]
        
        if matches:
            logger.info(f"[ARGO] Music song match: {song} ({len(matches)} tracks)")
        
        return matches
    
    def filter_by_keyword(self, keyword: str) -> List[Dict]:
        """
        Filter tracks by keyword search (tokens).
        
        Args:
            keyword: Search keyword
            
        Returns:
            List of matching tracks
        """
        keyword_lower = keyword.lower()
        matches = [t for t in self.tracks if keyword_lower in t.get("tokens", [])]
        
        if matches:
            logger.info(f"[ARGO] Music keyword match: {keyword} ({len(matches)} tracks)")
        
        return matches
    
    def get_random_track(self) -> Optional[Dict]:
        """
        Get random track from entire library.
        
        Returns:
            Random track or None if library empty
        """
        if not self.tracks:
            return None
        
        import random
        return random.choice(self.tracks)
    
    def search(self, query: str) -> List[Dict]:
        """
        Search by genre or keyword.
        
        Priority:
        1. Try canonical genre match
        2. Try keyword match
        3. Return empty list
        
        Args:
            query: Genre name or keyword
            
        Returns:
            List of matching tracks
        """
        # Try genre first
        genre_matches = self.filter_by_genre(query)
        if genre_matches:
            return genre_matches
        
        # Try keyword
        keyword_matches = self.filter_by_keyword(query)
        if keyword_matches:
            return keyword_matches
        
        # No matches
        return []


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_index_instance: Optional[MusicIndex] = None


def get_music_index() -> MusicIndex:
    """
    Get or create global music index instance.
    
    Handles startup bootstrap:
    - Check if MUSIC_ENABLED
    - Validate MUSIC_DIR exists
    - Load or create index
    - Continue without music on error (don't crash)
    
    Returns:
        MusicIndex instance (may be empty if music disabled or error)
    """
    global _index_instance
    
    if _index_instance is None:
        music_enabled = os.getenv("MUSIC_ENABLED", "false").lower() == "true"
        
        if not music_enabled:
            logger.info("[ARGO] Music disabled (MUSIC_ENABLED=false)")
            _index_instance = MusicIndex("", "")
            _index_instance.tracks = []
            return _index_instance
        
        music_dir = os.getenv("MUSIC_DIR", "I:\\My Music")
        index_file = os.getenv("MUSIC_INDEX_FILE", "data/music_index.json")
        
        try:
            _index_instance = MusicIndex(music_dir, index_file)
            _index_instance.load_or_create()
        except ValueError as e:
            # MUSIC_DIR doesn't exist
            logger.error(str(e))
            logger.error("[ARGO] Music will be unavailable")
            _index_instance = MusicIndex("", "")
            _index_instance.tracks = []
        except Exception as e:
            # Index build/load failed
            logger.error(f"[ARGO] Unexpected music startup error: {e}")
            logger.error("[ARGO] Music will be unavailable")
            _index_instance = MusicIndex("", "")
            _index_instance.tracks = []
    
    return _index_instance
