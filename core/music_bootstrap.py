"""
MUSIC SYSTEM BOOTSTRAP

Runs at application startup to:
1. Verify music configuration (env vars)
2. Ensure music directory exists
3. Create or load music index
4. Validate index content
5. Fail fast with clear errors if configuration is invalid

This ensures zero manual setup for the music system.
"""

import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def bootstrap_music_system() -> bool:
    """
    Bootstrap the music system at application startup.
    
    Supports two modes:
    1. Local: Scans MUSIC_DIR for audio files (requires index file)
    2. Jellyfin: Connects to Jellyfin server via API (no index file needed)
    
    Returns:
        True if bootstrap successful, False if music disabled or fatal errors
        
    Raises:
        RuntimeError: If configuration is invalid (fail fast)
    """
    
    music_enabled = os.getenv("MUSIC_ENABLED", "false").lower() == "true"
    
    if not music_enabled:
        logger.info("[MUSIC BOOTSTRAP] Music disabled (MUSIC_ENABLED=false)")
        return False
    
    logger.info("[MUSIC BOOTSTRAP] Starting music system bootstrap...")
    
    music_source = os.getenv("MUSIC_SOURCE", "local").lower()
    
    # ========== JELLYFIN MODE ==========
    if music_source == "jellyfin":
        logger.info("[MUSIC BOOTSTRAP] Using Jellyfin media server")
        
        # Validate Jellyfin credentials
        jellyfin_url = os.getenv("JELLYFIN_URL")
        jellyfin_key = os.getenv("JELLYFIN_API_KEY")
        jellyfin_user = os.getenv("JELLYFIN_USER_ID")
        
        if not all([jellyfin_url, jellyfin_key, jellyfin_user]):
            raise RuntimeError(
                "[MUSIC BOOTSTRAP] FATAL: Jellyfin credentials missing. "
                "Set JELLYFIN_URL, JELLYFIN_API_KEY, and JELLYFIN_USER_ID in .env"
            )
        
        logger.info(f"[MUSIC BOOTSTRAP] Jellyfin server: {jellyfin_url}")
        
        try:
            from core.jellyfin_provider import get_jellyfin_provider
            provider = get_jellyfin_provider()
            tracks = provider.load_music_library()
            logger.info(f"[MUSIC BOOTSTRAP] Loaded {len(tracks)} tracks from Jellyfin")
            return True
        except Exception as e:
            raise RuntimeError(f"[MUSIC BOOTSTRAP] FATAL: Jellyfin connection failed: {e}")
    
    # ========== LOCAL MODE ==========
    else:
        logger.info("[MUSIC BOOTSTRAP] Using local file scanning")
        
        # Step 1: Check MUSIC_DIR
        music_dir = os.getenv("MUSIC_DIR")
        if not music_dir:
            raise RuntimeError(
                "[MUSIC BOOTSTRAP] FATAL: MUSIC_DIR not set in .env. "
                "Set MUSIC_DIR=/path/to/music to enable music playback."
            )
        
        if not os.path.isdir(music_dir):
            raise RuntimeError(
                f"[MUSIC BOOTSTRAP] FATAL: MUSIC_DIR does not exist: {music_dir}. "
                "Create the directory or update MUSIC_DIR in .env"
            )
        
        logger.info(f"[MUSIC BOOTSTRAP] Music directory: {music_dir}")
        
        # Step 2: Check MUSIC_INDEX_FILE
        index_file = os.getenv("MUSIC_INDEX_FILE", "data/music_index.json")
        index_path = Path(index_file)
        
        # Ensure parent directory exists
        index_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[MUSIC BOOTSTRAP] Music index file: {index_path}")
        
        # Step 3: Check if index exists and is valid
        if index_path.exists():
            try:
                with open(index_path, "r") as f:
                    index_data = json.load(f)
                
                # Basic schema validation
                if not isinstance(index_data, dict) or "tracks" not in index_data:
                    raise ValueError("Invalid index schema: missing 'tracks' key")
                
                if not isinstance(index_data["tracks"], list):
                    raise ValueError("Invalid index schema: 'tracks' must be a list")
                
                track_count = len(index_data["tracks"])
                logger.info(f"[MUSIC BOOTSTRAP] Loaded index: {track_count} tracks")
                
                # Validate track schema
                for i, track in enumerate(index_data["tracks"]):
                    if not isinstance(track, dict):
                        raise ValueError(f"Track {i}: not a dictionary")
                    
                    # Required fields
                    if "path" not in track:
                        raise ValueError(f"Track {i}: missing 'path' field")
                    
                    if "name" not in track:
                        raise ValueError(f"Track {i}: missing 'name' field")
                    
                    # Check path exists
                    if not os.path.exists(track["path"]):
                        logger.warning(f"[MUSIC BOOTSTRAP] Track {i}: file not found: {track['path']}")
                
                logger.info("[MUSIC BOOTSTRAP] Index validation passed")
                return True
                
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"[MUSIC BOOTSTRAP] FATAL: Invalid JSON in index file: {e}. "
                    "Delete {index_path} and restart to rebuild index."
                )
            except ValueError as e:
                raise RuntimeError(
                    f"[MUSIC BOOTSTRAP] FATAL: Invalid index schema: {e}. "
                    f"Delete {index_path} and restart to rebuild index."
                )
        
        else:
            logger.info(
                f"[MUSIC BOOTSTRAP] Index file not found: {index_path}. "
                "Run music index scan to create it."
            )
            logger.info(
                f"[MUSIC BOOTSTRAP] To scan music directory now, run: "
                f"python scan_music_directory.py"
            )
            return False


if __name__ == "__main__":
    # For manual testing
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    try:
        result = bootstrap_music_system()
        print(f"Bootstrap result: {result}")
    except RuntimeError as e:
        print(f"Bootstrap failed: {e}")
        exit(1)
