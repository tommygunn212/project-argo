#!/usr/bin/env python3
"""
Test advanced music search with year/genre/artist filtering.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_player import MusicPlayer

def test_keyword_parsing():
    """Test keyword parsing for year, genre, and artist extraction."""
    
    player = MusicPlayer()
    
    test_cases = [
        # (keyword, expected_year, expected_genre, expected_artist)
        ("metal from 1984", 1984, "Metal", None),
        ("alice cooper", None, None, "alice cooper"),
        ("punk rock", None, "Punk Rock", None),
        ("classic rock from 1980", 1980, "Rock", None),
        ("heavy metal", None, "Metal", None),
        ("play some punk from 1977", 1977, "Punk", None),
        ("alice cooper from 1972", 1972, None, "alice cooper"),
        ("rock", None, "Rock", None),
        ("1984", 1984, None, None),
        ("led zeppelin", None, None, "led zeppelin"),
        ("blues from the 60s", 1960, "Blues", None),
    ]
    
    print("Testing keyword parsing...\n")
    
    for keyword, exp_year, exp_genre, exp_artist in test_cases:
        parsed = player._parse_music_keyword(keyword)
        
        year_match = parsed["year"] == exp_year
        genre_match = parsed["genre"] == exp_genre
        artist_match = parsed["artist"] == exp_artist
        
        status = "✓" if (year_match and genre_match and artist_match) else "✗"
        
        print(f"{status} Keyword: '{keyword}'")
        print(f"  Year: {parsed['year']} (expected {exp_year})")
        print(f"  Genre: {parsed['genre']} (expected {exp_genre})")
        print(f"  Artist: {parsed['artist']} (expected {exp_artist})")
        
        if not (year_match and genre_match and artist_match):
            print(f"  Full parse result: {parsed}")
        print()

if __name__ == "__main__":
    test_keyword_parsing()
