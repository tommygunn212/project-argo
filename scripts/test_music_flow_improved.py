#!/usr/bin/env python3
"""Test full music search flow with improved LLM extraction (no hallucination)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider
from core.intent_parser import RuleBasedIntentParser

def test_music_search_flow():
    """Test complete flow: voice -> intent -> extraction -> Jellyfin search."""
    
    print("Music Search Flow Test (No Hallucination)\n")
    print("="*80)
    
    parser = RuleBasedIntentParser()
    player = MusicPlayer(provider=MockJellyfinProvider())
    
    test_cases = [
        ("can you play rock music from the 80s", "Structured genre + year"),
        ("play alice cooper", "Artist name only"),
        ("play some punk rock", "Compound genre"),
    ]
    
    for voice_cmd, description in test_cases:
        print(f"\nVoice: '{voice_cmd}'")
        print(f"Type: {description}")
        print("-" * 80)
        
        intent = parser.parse(voice_cmd)
        if not intent.keyword:
            print("No music keyword detected")
            continue
        
        print(f"[1] Keyword: '{intent.keyword}'")
        
        # Try LLM extraction
        llm_result = player._extract_metadata_with_llm(intent.keyword)
        
        if llm_result and (llm_result.get("artist") or llm_result.get("genre") or llm_result.get("year")):
            print(f"[2] LLM Extraction: SUCCESS")
            print(f"     Genre: {llm_result.get('genre')}")
            print(f"     Year: {llm_result.get('year')}")
            print(f"     Artist: {llm_result.get('artist')}")
            extracted = llm_result
            method = "LLM"
        else:
            print(f"[2] LLM Extraction: No metadata extracted")
            regex_result = player._parse_music_keyword(intent.keyword)
            print(f"[2] Regex Fallback: SUCCESS")
            print(f"     Genre: {regex_result.get('genre')}")
            print(f"     Year: {regex_result.get('year')}")
            print(f"     Artist: {regex_result.get('artist')}")
            extracted = regex_result
            method = "REGEX"
        
        # Search Jellyfin
        print(f"[3] Jellyfin Search ({method})...")
        tracks = player.jellyfin_provider.advanced_search(
            year=extracted.get("year"),
            genre=extracted.get("genre"),
            artist=extracted.get("artist")
        )
        
        print(f"     FOUND: {len(tracks)} tracks")
        if tracks:
            for i, track in enumerate(tracks[:2], 1):
                print(f"       {i}. {track['artist']} - {track['song']}")

if __name__ == "__main__":
    test_music_search_flow()
