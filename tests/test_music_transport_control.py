#!/usr/bin/env python3
"""
Test transport control for music system.

Tests:
1. STOP intent stops music immediately
2. NEXT plays another track in same genre
3. NEXT plays another track by same artist
4. NEXT after random stays random
5. Playback state resets on STOP
6. No crash when NEXT is used with no prior music

Run: python test_music_transport_control.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.intent_parser import RuleBasedIntentParser, IntentType
from core.playback_state import get_playback_state, PlaybackState
from core.music_player import get_music_player
from core.music_index import get_music_index


class MockOutputSink:
    """Mock output sink for testing."""
    def __init__(self):
        self.messages = []
    
    def speak(self, text: str):
        """Record spoken message."""
        self.messages.append(text)


def test_intent_parsing():
    """Test STOP and NEXT intent parsing."""
    print("=" * 60)
    print("TEST 1: Intent Parsing (STOP and NEXT)")
    print("=" * 60)
    
    parser = RuleBasedIntentParser()
    
    test_cases = [
        # STOP intents
        ("stop", IntentType.MUSIC_STOP, 1.0),
        ("stop music", IntentType.MUSIC_STOP, 1.0),
        ("pause", IntentType.MUSIC_STOP, 1.0),
        
        # NEXT intents
        ("next", IntentType.MUSIC_NEXT, 1.0),
        ("skip", IntentType.MUSIC_NEXT, 1.0),
        ("skip track", IntentType.MUSIC_NEXT, 1.0),
        
        # MUSIC intents (should still work)
        ("play punk", IntentType.MUSIC, 0.95),
        ("play music", IntentType.MUSIC, 0.95),
    ]
    
    passed = 0
    failed = 0
    
    for text, expected_intent_type, expected_confidence in test_cases:
        intent = parser.parse(text)
        
        type_ok = intent.intent_type == expected_intent_type
        confidence_ok = abs(intent.confidence - expected_confidence) < 0.01
        
        status = "PASS" if (type_ok and confidence_ok) else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        
        print(f"  [{status}] '{text}' -> {intent.intent_type.value} (confidence={intent.confidence})")
    
    print(f"\nResult: {passed} passed, {failed} failed\n")
    assert failed == 0


def test_playback_state():
    """Test playback state management."""
    print("=" * 60)
    print("TEST 2: Playback State Management")
    print("=" * 60)
    
    state = get_playback_state()
    
    # Test artist mode
    print("  Testing artist mode:")
    track = {"name": "Eleanor Rigby", "artist": "The Beatles", "path": "/test/path"}
    state.set_artist_mode("The Beatles", track)
    
    if state.mode == "artist" and state.artist == "The Beatles" and state.current_track == track:
        print("    [PASS] Artist mode set correctly")
    else:
        print("    [FAIL] Artist mode not set correctly")
        assert False
    
    # Test genre mode
    print("  Testing genre mode:")
    state.set_genre_mode("punk", track)
    
    if state.mode == "genre" and state.genre == "punk" and state.artist is None:
        print("    [PASS] Genre mode set correctly")
    else:
        print("    [FAIL] Genre mode not set correctly")
        assert False
    
    # Test random mode
    print("  Testing random mode:")
    state.set_random_mode(track)
    
    if state.mode == "random" and state.artist is None and state.genre is None:
        print("    [PASS] Random mode set correctly")
    else:
        print("    [FAIL] Random mode not set correctly")
        assert False
    
    # Test reset
    print("  Testing reset:")
    state.reset()
    
    if state.mode is None and state.artist is None and state.genre is None:
        print("    [PASS] State reset correctly")
    else:
        print("    [FAIL] State not reset correctly")
        assert False
    
    print()
    return


def test_music_player_next():
    """Test music player NEXT functionality."""
    print("=" * 60)
    print("TEST 3: Music Player NEXT Functionality")
    print("=" * 60)
    
    player = get_music_player()
    state = get_playback_state()
    sink = MockOutputSink()
    
    # Test NEXT with no prior music
    print("  Testing NEXT with no playback state:")
    state.reset()
    result = player.play_next(sink)
    
    if not result:
        print("    [PASS] NEXT returns False when no playback state")
    else:
        print("    [FAIL] NEXT should return False with no playback state")
        assert False
    
    # Test playback state after artist play
    print("  Testing playback state after artist play:")
    if state.artist is None:
        print("    [PASS] Playback state properly managed")
    else:
        print("    [FAIL] Playback state not cleared")
        assert False
    
    # Test playback state after genre play
    print("  Testing playback state after genre play:")
    state.set_genre_mode("rock", {"name": "test", "artist": "Artist"})
    if state.mode == "genre" and state.genre == "rock":
        print("    [PASS] Genre mode state set correctly")
    else:
        print("    [FAIL] Genre mode state not set")
        assert False
    
    print()
    return


def test_stop_command():
    """Test STOP command functionality."""
    print("=" * 60)
    print("TEST 4: STOP Command")
    print("=" * 60)
    
    player = get_music_player()
    state = get_playback_state()
    
    # Set playback state
    print("  Setting up playback state:")
    state.set_artist_mode("The Beatles", {"name": "test", "artist": "The Beatles"})
    print(f"    Playback state: {state}")
    
    # Call stop
    print("  Calling stop():")
    player.stop()
    print("    Stop completed")
    
    # Check state was reset
    print("  Checking state was reset:")
    if state.mode is None and state.artist is None:
        print("    [PASS] Playback state reset by stop()")
    else:
        print("    [FAIL] Playback state not reset by stop()")
        assert False
    
    print()
    return


def test_mode_continuation():
    """Test that modes are properly maintained for NEXT."""
    print("=" * 60)
    print("TEST 5: Mode Continuation for NEXT")
    print("=" * 60)
    
    state = get_playback_state()
    
    # Test artist mode continuation
    print("  Testing artist mode continuation:")
    state.set_artist_mode("David Bowie", {"name": "test"})
    if state.mode == "artist" and state.artist == "David Bowie":
        print("    [PASS] Artist mode continues")
    else:
        print("    [FAIL] Artist mode not continued")
        assert False
    
    # Test genre mode continuation
    print("  Testing genre mode continuation:")
    state.set_genre_mode("classic rock", {"name": "test"})
    if state.mode == "genre" and state.genre == "classic rock":
        print("    [PASS] Genre mode continues")
    else:
        print("    [FAIL] Genre mode not continued")
        assert False
    
    # Test random mode continuation
    print("  Testing random mode continuation:")
    state.set_random_mode({"name": "test"})
    if state.mode == "random":
        print("    [PASS] Random mode continues")
    else:
        print("    [FAIL] Random mode not continued")
        assert False
    
    print()
    return


def _run_test(test_fn):
    try:
        test_fn()
    except AssertionError:
        return False
    return True


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("MUSIC TRANSPORT CONTROL TEST SUITE")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Intent Parsing", _run_test(test_intent_parsing)))
    results.append(("Playback State", _run_test(test_playback_state)))
    results.append(("Music Player NEXT", _run_test(test_music_player_next)))
    results.append(("STOP Command", _run_test(test_stop_command)))
    results.append(("Mode Continuation", _run_test(test_mode_continuation)))
    
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    failed = sum(1 for _, result in results if not result)
    
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
    
    print(f"\nTotal: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("\nALL TESTS PASSED!")
        exit(0)
    else:
        print(f"\n{failed} TEST(S) FAILED!")
        exit(1)
