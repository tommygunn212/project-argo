#!/usr/bin/env python3
"""Verify cascading fallback handles bad LLM extraction."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import pytest
from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider


player = MusicPlayer(provider=MockJellyfinProvider())

# Skip test if Jellyfin is not available
if not player.jellyfin_provider:
    pytest.skip("Jellyfin provider not available. Skipping cascading fallback robustness test.", allow_module_level=True)

print("\n" + "="*80)
print("CASCADING FALLBACK ROBUSTNESS TEST")
print("="*80 + "\n")

# Simulate what LLM extracted (with hallucination) vs what regex can fallback to
test_cases = [
    {
        "keyword": "guns and roses",
        "llm_extraction": {"song": "Guns and Roses", "artist": None, "genre": None, "year": None},
        "regex_extraction": {"artist": "guns and roses", "genre": None, "year": None},
    },
    {
        "keyword": "elton john",
        "llm_extraction": {"artist": "Elton John", "song": None, "genre": None, "year": None},
        "regex_extraction": {"artist": "elton john", "genre": None, "year": None},
    },
]

for test in test_cases:
    keyword = test["keyword"]
    llm = test["llm_extraction"]
    regex = test["regex_extraction"]
    
    print(f"Keyword: '{keyword}'")
    print(f"LLM extracted: {llm}")
    print(f"Regex would extract: {regex}")
    
    # Test cascading search
    print("Testing cascading fallback...")
    
    # Attempt 1: LLM result
    print(f"  Attempt 1 (LLM): Search for song='{llm.get('song')}', artist='{llm.get('artist')}'")
    tracks_llm = player.jellyfin_provider.advanced_search(
        song=llm.get('song'),
        artist=llm.get('artist'),
        genre=llm.get('genre'),
        year=llm.get('year')
    )
    print(f"    → Found {len(tracks_llm)} tracks (LLM)")
    
    # Attempt 2 (fallback): Regex result  
    if not tracks_llm:
        print(f"  Attempt 2 (Regex): Search for artist='{regex.get('artist')}'")
        tracks_regex = player.jellyfin_provider.advanced_search(
            artist=regex.get('artist'),
            genre=regex.get('genre'),
            year=regex.get('year')
        )
        print(f"    → Found {len(tracks_regex)} tracks (Regex)")
        
        if tracks_regex:
            print(f"  ✓ Cascading fallback SUCCEEDED!")
    else:
        print(f"  ✓ LLM result worked directly!")
    
    print()
