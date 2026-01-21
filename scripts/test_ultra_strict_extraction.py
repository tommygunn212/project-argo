#!/usr/bin/env python3
"""Test the ultra-strict LLM extraction prompt."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer

player = MusicPlayer()

test_cases = [
    ("elton john", "Should extract: artist only"),
    ("elton john tiny dancer", "Should extract: artist + song"),
    ("rock from 1980", "Should extract: genre + year"),
    ("something from the 70s", "Should extract: year only"),
    ("play some metal", "Should extract: genre only"),
    ("gods and roses", "Should extract: artist (not song)"),
]

print("\n" + "="*80)
print("ULTRA-STRICT LLM EXTRACTION TEST")
print("="*80 + "\n")

for keyword, description in test_cases:
    print(f"Keyword: '{keyword}'")
    print(f"Expected: {description}")
    
    result = player._extract_metadata_with_llm(keyword)
    
    if result:
        print(f"Extracted:")
        print(f"  - artist: {result.get('artist')}")
        print(f"  - song: {result.get('song')}")
        print(f"  - genre: {result.get('genre')}")
        print(f"  - year: {result.get('year')}")
    else:
        print(f"Extracted: (None - no explicit metadata)")
    
    print()
