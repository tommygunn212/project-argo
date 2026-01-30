#!/usr/bin/env python3
"""
Compare regex vs LLM-based metadata extraction.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider

def test_extraction_comparison():
    """Compare regex and LLM extraction methods."""
    
    print("Comparing Regex vs LLM-based Metadata Extraction\n")
    print("="*80)
    
    player = MusicPlayer(provider=MockJellyfinProvider())
    
    # Test cases: structured patterns and natural language patterns
    test_cases = [
        # Structured (regex should handle well)
        ("metal from 1984", "Structured pattern"),
        ("rock from 1980", "Structured pattern"),
        ("alice cooper", "Artist name"),
        
        # Natural language (LLM should excel)
        ("play something loud from the 70s", "Natural language with mood"),
        ("give me some early alice cooper", "Natural with temporal modifier"),
        ("chill reggae from the 80s", "Mood + genre + year"),
        ("play that hard rock stuff from the 1970s", "Conversational"),
    ]
    
    for keyword, description in test_cases:
        print(f"\nKeyword: '{keyword}'")
        print(f"Type: {description}")
        print("-" * 80)
        
        # Regex approach
        print("[REGEX EXTRACTION]")
        regex_result = player._parse_music_keyword(keyword)
        print(f"  Artist: {regex_result.get('artist')}")
        print(f"  Genre: {regex_result.get('genre')}")
        print(f"  Year: {regex_result.get('year')}")
        
        # LLM approach
        print("[LLM EXTRACTION]")
        llm_result = player._extract_metadata_with_llm(keyword)
        if llm_result:
            print(f"  Artist: {llm_result.get('artist')}")
            print(f"  Genre: {llm_result.get('genre')}")
            print(f"  Year: {llm_result.get('year')}")
            print(f"  Song: {llm_result.get('song')}")
        else:
            print("  (No result - LLM extraction failed or timed out)")
    
    print(f"\n{'='*80}")
    print("Comparison complete!")
    print(f"{'='*80}")

if __name__ == "__main__":
    test_extraction_comparison()
