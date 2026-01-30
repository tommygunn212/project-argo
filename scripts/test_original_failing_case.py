#!/usr/bin/env python3
"""Test the exact voice command from user logs that was failing with hallucination."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider

def test_original_failing_case():
    """
    Original failing case from user logs:
    - User said: "Can you play rock music from the 80s?"
    - OLD LLM extracted: artist="Guns N' Roses", song="Sweet Child O' Mine"
    - Result: 0 Jellyfin matches (wrong artist) → random fallback ✗
    
    NEW expected behavior:
    - LLM extracts: genre="Rock", year=1980
    - Jellyfin search returns: ~10 Rock tracks from 1980s ✓
    """
    
    print("ORIGINAL FAILING CASE TEST")
    print("="*80)
    print("\nOriginal Problem:")
    print("  Voice: 'Can you play rock music from the 80s?'")
    print("  OLD LLM: artist='Guns N' Roses', song='Sweet Child O' Mine'")
    print("  Result: 0 Jellyfin matches → Random fallback ✗")
    print("\nTesting with IMPROVED prompt...")
    print("="*80 + "\n")
    
    player = MusicPlayer(provider=MockJellyfinProvider())
    keyword = "rock music from the 80s"
    
    print(f"Keyword: '{keyword}'")
    
    # Extract metadata
    extracted = player._extract_metadata_with_llm(keyword)
    print(f"\nLLM Extraction:")
    
    if extracted and (extracted.get("artist") or extracted.get("genre") or extracted.get("year")):
        print(f"  ✓ Artist: {extracted.get('artist', 'None')}")
        print(f"  ✓ Genre: {extracted.get('genre', 'None')}")
        print(f"  ✓ Year: {extracted.get('year', 'None')}")
        print(f"  ✓ Song: {extracted.get('song', 'None')}")
    else:
        print("  [No explicit extraction - using regex fallback]")
        extracted = player._parse_music_keyword(keyword)
        print(f"  ✓ Artist: {extracted.get('artist', 'None')}")
        print(f"  ✓ Genre: {extracted.get('genre', 'None')}")
        print(f"  ✓ Year: {extracted.get('year', 'None')}")
        print(f"  ✓ Song: {extracted.get('song', 'None')}")
    
    # Check for hallucination
    print(f"\nHallucination Check:")
    artist = extracted.get("artist", "")
    if artist and ("Guns" in artist or "Roses" in artist):
        print(f"  ✗ FAIL: Artist is '{artist}' (hallucinated!)")
    assert not (artist and ("Guns" in artist or "Roses" in artist))
    print(f"  ✓ PASS: No Guns N' Roses hallucination")
    
    song = extracted.get("song", "")
    if song and any(x in song.lower() for x in ["sweet", "child", "mine"]):
        print(f"  ✗ FAIL: Song is '{song}' (hallucinated!)")
    assert not (song and any(x in song.lower() for x in ["sweet", "child", "mine"]))
    print(f"  ✓ PASS: No 'Sweet Child O' Mine' hallucination")
    
    # Search Jellyfin
    print(f"\nJellyfin Search:")
    tracks = player.jellyfin_provider.advanced_search(
        genre=extracted.get("genre"),
        year=extracted.get("year")
    )
    
    print(f"  Found: {len(tracks)} tracks")
    
    if len(tracks) == 0:
        print(f"  ✗ FAIL: 0 matches (would trigger random fallback)")
    assert len(tracks) > 0
    print(f"  ✓ PASS: Found matches (no random fallback needed)")
    for i, track in enumerate(tracks[:3], 1):
        print(f"      {i}. {track['artist']} - {track['song']}")
    
    print(f"\n" + "="*80)
    print("RESULT: ✅ FIXED - Hallucination prevented, proper tracks found")
    return None

if __name__ == "__main__":
    test_original_failing_case()
