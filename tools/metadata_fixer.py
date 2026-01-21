"""
Metadata Fixer - Safe, Slow & Resumeable

Scans the music library and fixes ID3 metadata using MusicBrainz API.
Features:
- Resume system: Tracks processed files in processed_files.log
- Quarantine system: Moves non-music/corrupt files to separate folder
- Rate-limited: 1.1s delay between API calls (respects MusicBrainz limits)

Usage:
    python tools/metadata_fixer.py

Estimated time: ~4 hours for 13,000 tracks
"""

import os
import time
import shutil
import musicbrainzngs
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import HeaderNotFoundError

# === CONFIGURATION ===
LIBRARY_PATH = r"I:\My Music"
QUARANTINE_PATH = r"I:\Argo_Quarantine"
LOG_FILE = "processed_files.log"
USER_EMAIL = "tommygunnfilms@gmail.com"  # MusicBrainz API contact
SUPPORTED_EXTENSIONS = ('.mp3',)  # Tuple for proper extension check

# Initialize MusicBrainz
musicbrainzngs.set_useragent("ArgoMetadataFixer", "0.2", USER_EMAIL)


def load_processed_files():
    """Load set of already-processed file paths from log."""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    return set()


def log_processed_file(file_path):
    """Append a processed file path to the log."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(file_path + "\n")


def quarantine_file(file_path, reason):
    """Move problematic file to quarantine folder."""
    if not os.path.exists(QUARANTINE_PATH):
        os.makedirs(QUARANTINE_PATH)
    
    file_name = os.path.basename(file_path)
    dest_path = os.path.join(QUARANTINE_PATH, file_name)
    
    # Handle duplicate filenames in quarantine
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(file_name)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(QUARANTINE_PATH, f"{base}_{counter}{ext}")
            counter += 1
    
    print(f"[QUARANTINE] {reason}: {file_name}")
    try:
        shutil.move(file_path, dest_path)
        log_processed_file(file_path)  # Don't process it again if it's moved
    except Exception as e:
        print(f"Error moving to quarantine: {e}")


def fix_metadata():
    """Main metadata fixing loop with resume support."""
    processed_files = load_processed_files()
    print(f"[*] Starting scan. {len(processed_files)} files already handled.")
    print(f"[*] Library: {LIBRARY_PATH}")
    print(f"[*] Quarantine: {QUARANTINE_PATH}")
    print(f"[*] Rate limit: 1.1s per API call (~4 hours for 13k tracks)")
    print()
    
    total_scanned = 0
    total_updated = 0
    total_quarantined = 0
    total_skipped = 0
    
    for root, dirs, files in os.walk(LIBRARY_PATH):
        for file in files:
            file_path = os.path.join(root, file)
            
            # Skip if already processed in a previous run
            if file_path in processed_files:
                total_skipped += 1
                continue

            total_scanned += 1

            # 1. Quarantine non-music files
            if not file.lower().endswith(SUPPORTED_EXTENSIONS):
                quarantine_file(file_path, "Non-music file")
                total_quarantined += 1
                continue

            print(f"[*] Processing: {file}")
            
            try:
                # 2. Extract current info
                audio = EasyID3(file_path)
                search_artist = audio.get('artist', [None])[0] or root.split(os.sep)[-2]
                search_title = audio.get('title', [None])[0] or file.replace('.mp3', '')

                # 3. Rate-limited API Call (Strict 1.1s delay)
                time.sleep(1.1)
                result = musicbrainzngs.search_recordings(
                    query=search_title, 
                    artist=search_artist, 
                    limit=1
                )

                if result['recording-list']:
                    match = result['recording-list'][0]
                    audio['artist'] = match['artist-credit-phrase']
                    audio['title'] = match['title']
                    if 'release-list' in match:
                        audio['album'] = match['release-list'][0]['title']
                    
                    audio.save()
                    print(f"    [OK] Updated: {audio['artist'][0]} - {audio['title'][0]}")
                    log_processed_file(file_path)
                    total_updated += 1
                else:
                    quarantine_file(file_path, "No match found")
                    total_quarantined += 1

            except HeaderNotFoundError:
                quarantine_file(file_path, "Corrupt MP3 header")
                total_quarantined += 1
            except Exception as e:
                print(f"    [ERROR] Skipping {file}: {e}")
                # We don't log it as processed so it can be retried later

    # Summary
    print()
    print("=" * 60)
    print("[*] METADATA FIX COMPLETE")
    print("=" * 60)
    print(f"    Scanned:     {total_scanned}")
    print(f"    Updated:     {total_updated}")
    print(f"    Quarantined: {total_quarantined}")
    print(f"    Skipped:     {total_skipped} (already processed)")
    print()


if __name__ == "__main__":
    fix_metadata()
