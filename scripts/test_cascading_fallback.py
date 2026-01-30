#!/usr/bin/env python3
"""
Test the cascading fallback search logic.

Scenario: LLM hallucinated "Sweet Child O' Mine" from 1985
The system should:
1. Try artist + song + year + genre → 0 results
2. Try artist + song (drop year/genre) → maybe results
3. Try artist only → guaranteed results if any exist
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider

def test_cascading_fallback():
    """Test cascading fallback with Guns and Roses example."""
    
    print("\n" + "="*80)
    print("CASCADING FALLBACK SEARCH TEST")
    print("="*80 + "\n")
    
    player = MusicPlayer(provider=MockJellyfinProvider())
    
    # Simulate what the LLM might hallucinate
    print("Scenario: User says 'Play Guns and Roses'")
    print("LLM hallucinated: artist='Guns and Roses', song='Sweet Child O Mine', year=1985, genre='Rock'")
    print("(Note: Song wasn't released until 1987)\n")
    
    # Simulate the extraction result
    llm_extracted = {
        "artist": "Guns and Roses",
        "song": "Sweet Child O Mine",
        "year": 1985,
        "genre": "Rock"
    }
    
    print("-" * 80)
    print("ATTEMPT 1: Strict search (artist + song + year + genre)")
    print("-" * 80)
    
    tracks = player.jellyfin_provider.advanced_search(
        artist=llm_extracted["artist"],
        genre=llm_extracted["genre"],
        year=llm_extracted["year"]
    )
    print(f"Result: {len(tracks)} tracks found")
    if not tracks:
        print("[FAILED] (as expected - year 1985 is wrong)\n")
    else:
        print(f"[OK] Found {len(tracks)} tracks")
        for i, track in enumerate(tracks[:2], 1):
            print(f"   {i}. {track['artist']} - {track['song']}")
        print()
    
    print("-" * 80)
    print("ATTEMPT 2: Relaxed search (drop year/genre, keep artist)")
    print("-" * 80)
    
    tracks = player.jellyfin_provider.advanced_search(
        artist=llm_extracted["artist"],
        genre=None,  # Drop unreliable genre
        year=None    # Drop unreliable year
    )
    print(f"Result: {len(tracks)} tracks found")
    if tracks:
        print(f"[OK] SUCCESS! Found {len(tracks)} Guns and Roses tracks:")
        for i, track in enumerate(tracks[:3], 1):
            print(f"   {i}. {track['artist']} - {track['song']} ({track.get('year', 'N/A')})")
        print()
        return
    else:
        print("[!] Not found in relaxed mode either\n")
    
    print("-" * 80)
    print("ATTEMPT 3: Artist-only search")
    print("-" * 80)
    
    tracks = player.jellyfin_provider.advanced_search(
        artist=llm_extracted["artist"]
    )
    print(f"Result: {len(tracks)} tracks found")
    if tracks:
        print(f"[OK] SUCCESS! Found {len(tracks)} Guns and Roses tracks:")
        for i, track in enumerate(tracks[:3], 1):
            print(f"   {i}. {track['artist']} - {track['song']} ({track.get('year', 'N/A')})")
        print()
        return
    else:
        print("[FAIL] Not found\n")
    
    print("-" * 80)
    print("ATTEMPT 4: Keyword search fallback")
    print("-" * 80)
    
    tracks = player.jellyfin_provider.search_by_keyword("guns and roses")
    print(f"Result: {len(tracks)} tracks found")
    if tracks:
        print(f"[OK] Found {len(tracks)} tracks:")
        for i, track in enumerate(tracks[:3], 1):
            print(f"   {i}. {track['artist']} - {track['song']}")
        print()
        return
    else:
        print("[FAIL] Not found\n")
    
    print("="*80)
    print("[OK] CASCADING FALLBACK LOGIC TEST COMPLETE")
    print("="*80 + "\n")
    return

if __name__ == "__main__":
    test_cascading_fallback()
