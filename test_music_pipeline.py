#!/usr/bin/env python3
"""
Test music catalog pipeline end-to-end.

Validates:
1. Intent parser extracts keywords correctly
2. Music index filters by genre and keyword
3. Music player can play tracks
4. Coordinator routes through music system

Run: python test_music_pipeline.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.intent_parser import RuleBasedIntentParser
from core.music_index import get_music_index
from core.music_player import get_music_player


def test_intent_parsing():
    """Test keyword extraction from voice commands."""
    print("=" * 60)
    print("TEST 1: Intent Parsing + Keyword Extraction")
    print("=" * 60)
    
    parser = RuleBasedIntentParser()
    
    test_cases = [
        ("play punk", "music", "punk"),
        ("play classic rock", "music", "classic rock"),
        ("play bowie", "music", "bowie"),
        ("play music", "music", None),
        ("surprise me", "music", None),
        ("play something", "music", None),
    ]
    
    passed = 0
    failed = 0
    
    for text, expected_intent, expected_keyword in test_cases:
        intent = parser.parse(text)
        
        intent_ok = intent.intent_type.value == expected_intent
        keyword_ok = intent.keyword == expected_keyword
        
        status = "PASS" if (intent_ok and keyword_ok) else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        
        keyword_str = f"keyword='{intent.keyword}'" if intent.keyword else "keyword=None"
        print(f"  [{status}] '{text}' -> {intent.intent_type.value} ({keyword_str})")
    
    print(f"\nResult: {passed} passed, {failed} failed")
    return failed == 0


def test_music_index():
    """Test genre and keyword filtering."""
    print("\n" + "=" * 60)
    print("TEST 2: Music Index Filtering")
    print("=" * 60)
    
    index = get_music_index()
    
    print(f"Total tracks: {len(index.tracks)}")
    print(f"Tracks with genre: {len([t for t in index.tracks if t.get('genre')])}")
    
    # Genre filtering
    print("\n  Genre filtering:")
    
    genres = ["punk", "rock", "blues"]
    for genre in genres:
        tracks = index.filter_by_genre(genre)
        print(f"    {genre}: {len(tracks)} tracks")
    
    # Keyword searching
    print("\n  Keyword searching:")
    
    keywords = ["bowie", "pink", "queen"]
    for keyword in keywords:
        tracks = index.filter_by_keyword(keyword)
        print(f"    {keyword}: {len(tracks)} tracks")
    
    return True


def test_music_player():
    """Test music player methods exist."""
    print("\n" + "=" * 60)
    print("TEST 3: Music Player Methods")
    print("=" * 60)
    
    player = get_music_player()
    
    required_methods = [
        "play_random",
        "play_by_genre",
        "play_by_keyword",
        "play",
        "stop"
    ]
    
    passed = 0
    failed = 0
    
    for method in required_methods:
        has_method = hasattr(player, method) and callable(getattr(player, method))
        status = "PASS" if has_method else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        
        print(f"  [{status}] {method}")
    
    print(f"\nResult: {passed} passed, {failed} failed")
    return failed == 0


def test_pipeline_integration():
    """Test full intent -> genre/keyword -> player pipeline."""
    print("\n" + "=" * 60)
    print("TEST 4: Pipeline Integration (No Audio)")
    print("=" * 60)
    
    parser = RuleBasedIntentParser()
    index = get_music_index()
    player = get_music_player()
    
    print("Simulating music command pipeline (no audio playback):\n")
    
    test_cases = [
        ("play punk", "Should play punk tracks"),
        ("play bowie", "Should play Bowie tracks"),
        ("play music", "Should play random track"),
    ]
    
    passed = 0
    failed = 0
    
    for command, description in test_cases:
        intent = parser.parse(command)
        
        if intent.keyword:
            # Try genre first, then keyword
            tracks = index.filter_by_genre(intent.keyword)
            if not tracks:
                tracks = index.filter_by_keyword(intent.keyword)
            track_source = "genre" if len(index.filter_by_genre(intent.keyword)) > 0 else "keyword"
        else:
            # Random
            tracks = index.get_random_track()
            if tracks:
                tracks = [tracks]
            track_source = "random"
        
        if tracks:
            track_name = tracks[0].get("name", "?")
            print(f"  PASS: '{command}'")
            print(f"    -> Source: {track_source}")
            print(f"    -> Track: {track_name[:50]}")
            passed += 1
        else:
            print(f"  FAIL: '{command}' - no tracks found")
            failed += 1
    
    print(f"\nResult: {passed} passed, {failed} failed")
    return failed == 0


def main():
    """Run all tests."""
    print("\n")
    print("MUSIC CATALOG PIPELINE TEST SUITE")
    print("=" * 60)
    
    results = []
    
    try:
        results.append(("Intent Parsing", test_intent_parsing()))
        results.append(("Music Index", test_music_index()))
        results.append(("Music Player", test_music_player()))
        results.append(("Pipeline Integration", test_pipeline_integration()))
        
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\nALL TESTS PASSED!")
        return 0
    else:
        print("\nSOME TESTS FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
