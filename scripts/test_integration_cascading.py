#!/usr/bin/env python3
"""
Integration test: Full voice command → LLM extraction → Cascading search → Playback
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

def test_integration():
    """Test full flow: voice → intent → extraction → cascading search."""
    
    print("\n" + "="*80)
    print("INTEGRATION TEST: Voice Command → Cascading Search")
    print("="*80 + "\n")
    
    parser = RuleBasedIntentParser()
    player = MusicPlayer(provider=MockJellyfinProvider())
    
    test_cases = [
        ("can you play guns and roses", "Band with 'and' in name"),
        ("play some rock from the 80s", "Genre + decade"),
        ("play alice cooper", "Solo artist"),
    ]
    
    for voice_cmd, description in test_cases:
        print(f"Voice Command: '{voice_cmd}'")
        print(f"Type: {description}")
        print("-" * 80)
        
        intent = parser.parse(voice_cmd)
        if not intent.keyword:
            print("No music keyword detected\n")
            continue
        
        keyword = intent.keyword
        print(f"[1] Extracted keyword: '{keyword}'")
        
        # Get LLM extraction (might hallucinate!)
        llm_extracted = player._extract_metadata_with_llm(keyword)
        
        if llm_extracted and (llm_extracted.get("artist") or llm_extracted.get("genre") or llm_extracted.get("year")):
            print(f"[2] LLM extracted: {llm_extracted}")
            parsed = llm_extracted
            method = "LLM"
        else:
            print(f"[2] LLM extraction empty, using regex")
            regex_result = player._parse_music_keyword(keyword)
            print(f"     Regex result: {regex_result}")
            parsed = regex_result
            method = "REGEX"
        
        # Now show the cascading search attempts
        print(f"\n[3] Cascading Search Attempts (parsed={method}):")
        
        tracks = []
        
        # Attempt 1
        print(f"    Attempt 1 (Strict): artist={parsed.get('artist')}, genre={parsed.get('genre')}, year={parsed.get('year')}")
        tracks = player.jellyfin_provider.advanced_search(
            artist=parsed.get("artist"),
            genre=parsed.get("genre"),
            year=parsed.get("year")
        )
        print(f"    Result: {len(tracks)} tracks")
        if tracks:
            print(f"    ✓ Playing: {tracks[0]['artist']} - {tracks[0]['song']}\n")
            continue
        
        # Attempt 2
        if parsed.get("year") or parsed.get("genre"):
            print(f"    Attempt 2 (Relaxed): artist={parsed.get('artist')} only (dropped year/genre)")
            tracks = player.jellyfin_provider.advanced_search(
                artist=parsed.get("artist")
            )
            print(f"    Result: {len(tracks)} tracks")
            if tracks:
                print(f"    ✓ Playing: {tracks[0]['artist']} - {tracks[0]['song']}\n")
                continue
        
        # Attempt 3
        if not tracks:
            print(f"    Attempt 3 (Keyword): keyword='{keyword}'")
            tracks = player.jellyfin_provider.search_by_keyword(keyword)
            print(f"    Result: {len(tracks)} tracks")
            if tracks:
                print(f"    ✓ Playing: {tracks[0]['artist']} - {tracks[0]['song']}\n")
                continue
        
        # No tracks found
        if not tracks:
            print(f"    ❌ No tracks found\n")
    
    print("="*80)
    print("✅ INTEGRATION TEST COMPLETE")
    print("="*80 + "\n")
    return

if __name__ == "__main__":
    test_integration()
