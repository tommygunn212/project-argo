#!/usr/bin/env python3
"""Test Jellyfin music playback."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from core.jellyfin_provider import get_jellyfin_provider
import time

print("\n" + "="*80)
print("JELLYFIN PLAYBACK TEST")
print("="*80 + "\n")

jellyfin = get_jellyfin_provider()
player = MusicPlayer()

# Search for Elton John
print("Searching for Elton John...")
tracks = jellyfin.advanced_search(artist="Elton John")

if not tracks:
    print("❌ No Elton John tracks found")
    sys.exit(1)

print(f"✓ Found {len(tracks)} Elton John tracks")
track = tracks[0]
print(f"✓ Selected: {track['artist']} - {track['song']}")

# Get stream URL
stream_url = jellyfin.get_play_url(track["jellyfin_id"])
print(f"✓ Stream URL: {stream_url[:80]}...")

# Test playback
print("\nAttempting playback...")
try:
    result = player._play_jellyfin_track(track, f"Playing {track['song']}", None)
    if result:
        print("✓ Playback started successfully!")
        print("✓ Listen for audio in background...")
        time.sleep(5)
        print("✓ Test complete")
    else:
        print("❌ Playback failed")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
