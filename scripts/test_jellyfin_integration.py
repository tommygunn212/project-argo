#!/usr/bin/env python3
"""
Quick Jellyfin Connection Test

Verifies that ARGO can connect to Jellyfin and fetch music.
"""

import sys
from pathlib import Path

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

def main():
    print("=" * 70)
    print("JELLYFIN CONNECTION TEST")
    print("=" * 70)
    
    try:
        print("\n[*] Importing Jellyfin provider...")
        from core.jellyfin_provider import get_jellyfin_provider
        
        print("[*] Connecting to Jellyfin...")
        provider = get_jellyfin_provider()
        
        print("[*] Fetching music library...")
        tracks = provider.load_music_library()
        
        if not tracks:
            print("\n[WARNING] No tracks found in Jellyfin library")
            return 1
        
        print(f"\n[OK] Successfully loaded {len(tracks)} tracks from Jellyfin!")
        
        # Show sample tracks
        print("\nSample tracks:")
        for track in tracks[:5]:
            print(f"  - {track['artist']} - {track['song']}")
        
        # Test search
        print("\n[*] Testing search...")
        if tracks:
            first_artist = tracks[0]['artist']
            results = provider.search_by_artist(first_artist)
            print(f"  Search '{first_artist}': {len(results)} result(s)")
        
        print("\n" + "=" * 70)
        print("[OK] JELLYFIN INTEGRATION WORKING")
        print("=" * 70)
        return 0
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
