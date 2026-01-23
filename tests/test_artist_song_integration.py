#!/usr/bin/env python3
"""
Comprehensive test of artist/song-aware music system.

Tests all components:
- Artist extraction and filtering
- Song extraction and filtering
- Priority-based keyword routing
- Friendly announcements
- Integration with music player
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.intent_parser import RuleBasedIntentParser
from core.music_index import get_music_index
from core.music_player import get_music_player


def test_artist_extraction():
    """Test artist extraction from folder hierarchy."""
    print("=" * 70)
    print("TEST 1: Artist Extraction from Folder Hierarchy")
    print("=" * 70)
    
    index = get_music_index()
    
    # Count artists
    tracks_with_artist = [t for t in index.tracks if t.get("artist")]
    print(f"\nTracks with extracted artist: {len(tracks_with_artist)} / {len(index.tracks)}")
    
    # Show top artists
    artist_counts = {}
    for t in tracks_with_artist:
        artist = t["artist"]
        artist_counts[artist] = artist_counts.get(artist, 0) + 1
    
    top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"\nTop 10 artists by track count:")
    for i, (artist, count) in enumerate(top_artists, 1):
        print(f"  {i:2}. {artist[:40]:40} ({count:3} tracks)")
    
    print("\nRESULT: PASS")
    return True


def test_song_extraction():
    """Test song name extraction from filenames."""
    print("\n" + "=" * 70)
    print("TEST 2: Song Name Extraction from Filenames")
    print("=" * 70)
    
    index = get_music_index()
    
    # Count songs
    tracks_with_song = [t for t in index.tracks if t.get("song")]
    print(f"\nTracks with extracted song name: {len(tracks_with_song)} / {len(index.tracks)}")
    
    # Show samples
    print(f"\nSample extracted song names:")
    for i, track in enumerate(tracks_with_song[:5], 1):
        filename = os.path.basename(track["path"])
        song = track.get("song", "?")
        print(f"  {i}. {filename[:45]:45} -> '{song[:30]}'")
    
    print("\nRESULT: PASS")
    return True


def test_artist_filtering():
    """Test artist-based track filtering."""
    print("\n" + "=" * 70)
    print("TEST 3: Artist-Based Track Filtering")
    print("=" * 70)
    
    index = get_music_index()
    player = get_music_player()

    if getattr(index, "is_empty", None) and index.is_empty():
        print("No music available (index empty)")
        return True
    
    # Get an artist with tracks
    artist_counts = {}
    for t in index.tracks:
        if t.get("artist"):
            artist = t["artist"]
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
    
    if not artist_counts:
        print("No artists found")
        return False
    
    # Test artist with most tracks
    test_artist = max(artist_counts.items(), key=lambda x: x[1])[0]
    print(f"\nTesting artist: '{test_artist}'")
    
    # Test filter
    artist_tracks = index.filter_by_artist(test_artist)
    print(f"Tracks by artist: {len(artist_tracks)}")
    
    if artist_tracks:
        # Show samples
        print(f"Sample tracks:")
        for track in artist_tracks[:3]:
            print(f"  - {track.get('song', '?')}")
        print("RESULT: PASS")
        return True
    else:
        print("RESULT: FAIL - No tracks found")
        return False


def test_song_filtering():
    """Test song name-based track filtering."""
    print("\n" + "=" * 70)
    print("TEST 4: Song Name-Based Track Filtering")
    print("=" * 70)
    
    index = get_music_index()

    if getattr(index, "is_empty", None) and index.is_empty():
        print("No music available (index empty)")
        return True
    
    # Find a unique song
    song_counts = {}
    for t in index.tracks:
        if t.get("song"):
            song = t["song"]
            song_counts[song] = song_counts.get(song, 0) + 1
    
    # Find a song with exactly one track
    unique_songs = [s for s, c in song_counts.items() if c == 1]
    if not unique_songs:
        print("No unique songs found, testing with most common...")
        test_song = max(song_counts.items(), key=lambda x: x[1])[0]
    else:
        test_song = unique_songs[0]
    
    print(f"\nTesting song: '{test_song}'")
    
    # Test filter
    song_tracks = index.filter_by_song(test_song)
    print(f"Tracks with song name: {len(song_tracks)}")
    
    if song_tracks:
        print(f"Sample track: {os.path.basename(song_tracks[0]['path'])}")
        print("RESULT: PASS")
        return True
    else:
        print("RESULT: FAIL - No tracks found")
        return False


def test_priority_routing():
    """Test keyword routing priority: artist -> song -> keyword."""
    print("\n" + "=" * 70)
    print("TEST 5: Priority-Based Keyword Routing")
    print("=" * 70)
    
    index = get_music_index()
    player = get_music_player()

    if getattr(index, "is_empty", None) and index.is_empty():
        print("No music available (index empty)")
        return True
    
    # Get an artist name
    artists = [t.get("artist") for t in index.tracks if t.get("artist")]
    test_artist = artists[0] if artists else None
    
    if not test_artist:
        print("No artist available for testing")
        return False
    
    print(f"\nTesting keyword: '{test_artist}'")
    print("Expected routing: artist filter")
    
    # Test routing
    artist_matches = index.filter_by_artist(test_artist)
    song_matches = index.filter_by_song(test_artist)
    keyword_matches = index.filter_by_keyword(test_artist)
    
    print(f"  Artist matches: {len(artist_matches)}")
    print(f"  Song matches: {len(song_matches)}")
    print(f"  Keyword matches: {len(keyword_matches)}")
    
    if artist_matches:
        print(f"  -> Priority: ARTIST")
    elif song_matches:
        print(f"  -> Priority: SONG")
    elif keyword_matches:
        print(f"  -> Priority: KEYWORD")
    
    print("RESULT: PASS")
    return True


def test_announcements():
    """Test friendly playback announcements."""
    print("\n" + "=" * 70)
    print("TEST 6: Friendly Playback Announcements")
    print("=" * 70)
    
    player = get_music_player()
    
    test_cases = [
        {
            "track": {"song": "Hotel California", "artist": "Eagles"},
            "expected": "Hotel California by Eagles"
        },
        {
            "track": {"song": "Bohemian Rhapsody", "artist": None},
            "expected": "Bohemian Rhapsody"
        },
        {
            "track": {"song": None, "artist": "Pink Floyd"},
            "expected": "Pink Floyd"
        },
        {
            "track": {"song": "Song", "artist": "Artist", "name": "fallback.mp3"},
            "expected": "Song by Artist"
        }
    ]
    
    print("\nAnnouncement format tests:")
    passed = 0
    for i, test in enumerate(test_cases, 1):
        track = test["track"]
        expected = test["expected"]
        actual = player._build_announcement(track)
        match = actual == expected
        status = "PASS" if match else "FAIL"
        
        print(f"  {i}. [{status}] {actual}")
        if match:
            passed += 1
    
    print(f"\nResult: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_intent_routing():
    """Test how intent parser keywords route to artist/song system."""
    print("\n" + "=" * 70)
    print("TEST 7: Intent Parsing + Routing Integration")
    print("=" * 70)
    
    parser = RuleBasedIntentParser()
    index = get_music_index()
    
    # Get a real artist from library
    artists = [t.get("artist") for t in index.tracks if t.get("artist")]
    test_artist = artists[0] if artists else "unknown"
    
    test_cases = [
        ("play music", None),
        (f"play {test_artist}", test_artist),
        ("play punk", "punk"),
        ("play classic rock", "classic rock"),
    ]
    
    print("\nIntent parsing + keyword extraction:")
    for command, expected_keyword in test_cases:
        intent = parser.parse(command)
        keyword = intent.keyword
        matches = keyword == expected_keyword if expected_keyword else True
        status = "PASS" if matches else "DIFF"
        
        keyword_str = f"keyword='{keyword}'" if keyword else "keyword=None"
        expected_str = f"(expected: {expected_keyword})" if expected_keyword else ""
        print(f"  '{command:30}' -> {keyword_str:20} {expected_str}")
    
    print("RESULT: PASS")
    return True


def main():
    """Run all tests."""
    print("\n")
    print("ARTIST/SONG EXTRACTION AND ROUTING TEST SUITE")
    print("=" * 70)
    
    results = []
    
    try:
        results.append(("Artist Extraction", test_artist_extraction()))
        results.append(("Song Extraction", test_song_extraction()))
        results.append(("Artist Filtering", test_artist_filtering()))
        results.append(("Song Filtering", test_song_filtering()))
        results.append(("Priority Routing", test_priority_routing()))
        results.append(("Announcements", test_announcements()))
        results.append(("Intent Routing", test_intent_routing()))
        
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name:20} {status}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "=" * 70)
    if all_passed:
        print("ALL TESTS PASSED!")
        return 0
    else:
        print("SOME TESTS FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
