#!/usr/bin/env python3
"""Test that LLM extraction doesn't hallucinate artist/song names."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer

def test_no_hallucination():
    """Ensure LLM extraction doesn't guess artist/song names."""
    
    player = MusicPlayer()
    
    print("Testing LLM Extraction - NO HALLUCINATION\n")
    print("="*80)
    
    tests = [
        # (request, expected_artist, expected_song, expected_genre, expected_year)
        ("play rock from the 80s", None, None, "Rock", 1980),
        ("play alice cooper", "Alice Cooper", None, None, None),
        ("give me some metal", None, None, "Metal", None),
        ("play early pink floyd", "Pink Floyd", None, None, None),
        ("something loud from 1970", None, None, "Rock", 1970),  # Or maybe None for genre
    ]
    
    for request, exp_artist, exp_song, exp_genre, exp_year in tests:
        print(f"\nRequest: '{request}'")
        result = player._extract_metadata_with_llm(request)
        
        if result:
            artist = result.get("artist")
            song = result.get("song")
            genre = result.get("genre")
            year = result.get("year")
            
            print(f"  Extracted:")
            print(f"    Artist: {artist} {'✓' if artist == exp_artist else '✗'}")
            print(f"    Song: {song} {'✓' if song == exp_song else '✗'}")
            print(f"    Genre: {genre} {'✓' if genre == exp_genre else '✗'}")
            print(f"    Year: {year} {'✓' if year == exp_year else '✗'}")
            
            # Check for hallucination
            if song and not any(word.lower() in request.lower() for word in (song.split())):
                print(f"  ⚠️  WARNING: Song may be hallucinated!")
            if artist and artist.lower() not in request.lower():
                # Only warn if artist name is not in the request at all
                if "artist" not in result or result["artist"] is not None:
                    words_in_request = request.lower().split()
                    if not any(name_part.lower() in request.lower() for name_part in artist.split()):
                        print(f"  ⚠️  WARNING: Artist may be hallucinated!")
        else:
            print(f"  (No extraction)")
    
    print(f"\n{'='*80}")
    print("✓ No hallucination test complete")

if __name__ == "__main__":
    test_no_hallucination()
