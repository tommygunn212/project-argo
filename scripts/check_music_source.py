#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add argo root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer

print("=" * 70)
print("MUSIC PLAYER SOURCE CHECK")
print("=" * 70)

player = MusicPlayer()
print(f"Music source: {os.getenv('MUSIC_SOURCE')}")
print(f"Using Jellyfin: {player.jellyfin_provider is not None}")

if player.jellyfin_provider:
    print(f"Jellyfin tracks loaded: {len(player.jellyfin_provider.tracks)}")
    
    # Try loading manually
    print("\n[*] Attempting to load Jellyfin library...")
    tracks = player.jellyfin_provider.load_music_library()
    print(f"Loaded: {len(tracks)} tracks")
    
    if tracks:
        print("\nSample tracks:")
        for i, t in enumerate(tracks[:3]):
            print(f"  {i+1}. {t.get('artist')} - {t.get('song')}")
        print("\n[OK] Jellyfin integration working!")
    else:
        print("[WARNING] Library is empty")
else:
    print(f"Using local index: {player.index is not None}")
    if player.index:
        print(f"Local tracks: {len(player.index.tracks)}")
