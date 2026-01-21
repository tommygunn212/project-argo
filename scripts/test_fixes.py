#!/usr/bin/env python3
"""Test fixes for the critical bugs that were causing failures."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer

def test_fixes():
    """Test the two critical fixes."""
    
    print("\n" + "="*80)
    print("CRITICAL BUG FIXES TEST")
    print("="*80 + "\n")
    
    player = MusicPlayer()
    
    # TEST 1: Year as integer from LLM
    print("TEST 1: Safe handling of integer year values")
    print("-" * 80)
    print("Issue: LLM might return {\"year\": 1990} (int) instead of {\"year\": \"1990\"} (str)")
    print("Old code crashed with: 'int' object has no attribute 'lower'")
    
    try:
        # This should NOT crash with .lower() error
        result = player._normalize_year_from_llm(1990)  # Pass integer directly
        print(f"✓ Successfully normalized integer year 1990 → {result}")
        assert result == 1990, f"Expected 1990, got {result}"
    except TypeError as e:
        print(f"✗ FAILED: {e}")
        return False
    
    # Also test string versions
    result = player._normalize_year_from_llm("1990")
    assert result == 1990, f"Expected 1990, got {result}"
    print(f"✓ String year '1990' → {result}")
    
    result = player._normalize_year_from_llm("80s")
    assert result == 1980, f"Expected 1980, got {result}"
    print(f"✓ Decade string '80s' → {result}")
    
    result = player._normalize_year_from_llm("early 80s")
    assert result == 1980, f"Expected 1980, got {result}"
    print(f"✓ Decade phrase 'early 80s' → {result}")
    
    print()
    
    # TEST 2: Band names with "and"
    print("TEST 2: Preserve 'and' in band names")
    print("-" * 80)
    print("Issue: Regex parser was stripping 'and' from 'Guns and Roses' → 'guns roses'")
    print("Result: Jellyfin couldn't find the band (strict name matching)")
    
    # Test the regex parser directly
    test_cases = [
        ("guns and roses", "Guns and Roses"),
        ("hootie and the blowfish", "Hootie and the Blowfish"),
        ("play alice cooper", "Alice Cooper"),
        ("play some pink floyd", "Pink Floyd"),
    ]
    
    for keyword, expected_artist in test_cases:
        result = player._parse_music_keyword(keyword)
        extracted_artist = result.get("artist")
        
        # Normalize for comparison (case-insensitive)
        extracted_lower = extracted_artist.lower() if extracted_artist else ""
        expected_lower = expected_artist.lower()
        
        if "and" in expected_lower and "and" in extracted_lower:
            print(f"✓ '{keyword}' → artist='{extracted_artist}' (preserved 'and')")
        elif extracted_lower == expected_lower:
            print(f"✓ '{keyword}' → artist='{extracted_artist}'")
        else:
            print(f"✗ '{keyword}' → got '{extracted_artist}', expected '{expected_artist}'")
            return False
    
    print()
    
    # TEST 3: End-to-end - Can we find Guns and Roses in Jellyfin?
    print("TEST 3: End-to-end - Search for Guns and Roses in Jellyfin")
    print("-" * 80)
    
    keyword = "play guns and roses"
    extracted = player._parse_music_keyword(keyword)
    print(f"Keyword: '{keyword}'")
    print(f"Extracted: artist='{extracted.get('artist')}'")
    
    # Search Jellyfin
    tracks = player.jellyfin_provider.advanced_search(
        artist=extracted.get("artist")
    )
    
    print(f"Jellyfin search found: {len(tracks)} tracks")
    if len(tracks) > 0:
        print(f"✓ SUCCESS: Found Guns and Roses tracks!")
        for i, track in enumerate(tracks[:2], 1):
            print(f"   {i}. {track['artist']} - {track['song']}")
    else:
        print(f"✗ FAILED: No tracks found (would be stripped to 'guns roses')")
        return False
    
    print("\n" + "="*80)
    print("✅ ALL FIXES VERIFIED")
    print("="*80 + "\n")
    return True

if __name__ == "__main__":
    success = test_fixes()
    sys.exit(0 if success else 1)
