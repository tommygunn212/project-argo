#!/usr/bin/env python3
"""Test LLM-based metadata extraction."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider

def test_llm_extraction():
    player = MusicPlayer(provider=MockJellyfinProvider())
    
    tests = [
        "play something loud from the 70s",
        "play early alice cooper",
        "metal from 1984",
        "give me some chill reggae",
    ]
    
    print("LLM Metadata Extraction Tests\n")
    for test in tests:
        print(f"Query: {test}")
        result = player._extract_metadata_with_llm(test)
        if result:
            print(f"  Genre: {result.get('genre')}")
            print(f"  Year: {result.get('year')}")
            print(f"  Artist: {result.get('artist')}")
        else:
            print("  (No extraction)")
        print()

if __name__ == "__main__":
    test_llm_extraction()
