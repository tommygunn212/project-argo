#!/usr/bin/env python3
"""
Comprehensive test: Hybrid LLM + Regex extraction with Jellyfin search.
Shows the smarter, more flexible music search in action.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider
from core.intent_parser import RuleBasedIntentParser

def test_hybrid_extraction():
    """Test hybrid LLM + regex extraction with actual Jellyfin search."""
    
    print("HYBRID EXTRACTION TEST: Natural Language -> Jellyfin Search\n")
    print("="*80)
    
    parser = RuleBasedIntentParser()
    player = MusicPlayer(provider=MockJellyfinProvider())
    
    # Test cases mixing structured and natural language patterns
    test_cases = [
        ("play something loud from the 70s", "Conversational + year"),
        ("give me some chill reggae", "Mood + genre"),
        ("play early alice cooper", "Temporal modifier + artist"),
        ("metal from 1984", "Genre + year (structured)"),
        ("play classic rock from 1980", "Genre + year (structured)"),
    ]
    
    for voice_cmd, description in test_cases:
        print(f"\nVoice Command: '{voice_cmd}'")
        print(f"Type: {description}")
        print("-" * 80)
        
        # Parse intent
        intent = parser.parse(voice_cmd)
        if intent.keyword:
            print(f"[1] Intent parsed: music, keyword='{intent.keyword}'")
        else:
            print(f"[1] Intent parsed: music (no keyword)")
            continue
        
        # Try LLM extraction first
        print(f"[2] Attempting LLM extraction...")
        llm_result = player._extract_metadata_with_llm(intent.keyword)
        
        if llm_result and (llm_result.get("genre") or llm_result.get("year") or llm_result.get("artist")):
            print(f"     SUCCESS - LLM extracted:")
            print(f"       Genre: {llm_result.get('genre')}")
            print(f"       Year: {llm_result.get('year')}")
            print(f"       Artist: {llm_result.get('artist')}")
            extracted = llm_result
        else:
            print(f"     LLM returned no metadata, using regex fallback...")
            regex_result = player._parse_music_keyword(intent.keyword)
            print(f"     Regex extracted:")
            print(f"       Genre: {regex_result.get('genre')}")
            print(f"       Year: {regex_result.get('year')}")
            print(f"       Artist: {regex_result.get('artist')}")
            extracted = regex_result
        
        # Perform Jellyfin search
        print(f"[3] Jellyfin advanced search...")
        tracks = player.jellyfin_provider.advanced_search(
            query_text=None,
            year=extracted.get("year"),
            genre=extracted.get("genre"),
            artist=extracted.get("artist")
        )
        
        print(f"     FOUND: {len(tracks)} matching tracks")
        if tracks:
            for i, track in enumerate(tracks[:2], 1):
                print(f"       {i}. {track['artist']} - {track['song']}")
    
    print(f"\n{'='*80}")
    print("Hybrid extraction test complete!")

if __name__ == "__main__":
    test_hybrid_extraction()
