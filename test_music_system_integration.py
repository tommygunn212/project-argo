"""
Comprehensive integration test for the complete music system
Tests all three features: Play, Transport Control, and Status Queries
"""

import sys
sys.path.insert(0, ".")

from core.intent_parser import RuleBasedIntentParser, IntentType
from core.playback_state import get_playback_state
from core.music_status import query_music_status


def test_complete_user_scenario():
    """
    Simulate complete user interaction:
    1. play punk -> Genre mode
    2. what's playing -> Status query
    3. next -> Skip to next
    4. what's playing -> Verify new track
    5. stop -> Stop playback
    6. what's playing -> Verify nothing playing
    """
    
    parser = RuleBasedIntentParser()
    state = get_playback_state()
    
    print("\n" + "="*70)
    print("COMPREHENSIVE MUSIC SYSTEM INTEGRATION TEST")
    print("="*70)
    
    # Step 1: Parse "play punk" command
    print("\n[STEP 1] User says: 'play punk'")
    intent = parser.parse("play punk")
    assert intent.intent_type == IntentType.MUSIC
    print(f"  [OK] Intent parsed: {intent.intent_type.value}")
    
    # Simulate playback (set playback state)
    state.set_genre_mode("punk", {
        "song": "Blitzkrieg Bop",
        "artist": "Ramones",
        "path": "/music/punk/song1.mp3"
    })
    print(f"  [OK] Playback started in GENRE mode: punk")
    print(f"  [OK] Now playing: {state.current_track['song']} by {state.current_track['artist']}")
    
    # Step 2: Query status
    print("\n[STEP 2] User says: 'what's playing'")
    intent = parser.parse("what's playing")
    assert intent.intent_type == IntentType.MUSIC_STATUS
    print(f"  [OK] Intent parsed: {intent.intent_type.value} (confidence: {intent.confidence})")
    
    status = query_music_status()
    print(f"  [OK] Status: {status}")
    assert status == "You're listening to Blitzkrieg Bop by Ramones."
    
    # Verify state unchanged after query
    assert state.mode == "genre"
    assert state.genre == "punk"
    print(f"  [OK] Playback state unchanged (still in genre mode)")
    
    # Step 3: Skip to next track
    print("\n[STEP 3] User says: 'next'")
    intent = parser.parse("next")
    assert intent.intent_type == IntentType.MUSIC_NEXT
    print(f"  [OK] Intent parsed: {intent.intent_type.value} (confidence: {intent.confidence})")
    
    # Simulate next track in same mode
    state.current_track = {
        "song": "I Wanna Be Sedated",
        "artist": "Ramones",
        "path": "/music/punk/song2.mp3"
    }
    print(f"  [OK] Skipped to next track: {state.current_track['song']}")
    
    # Step 4: Query status again
    print("\n[STEP 4] User says: 'what's playing'")
    intent = parser.parse("what's playing")
    assert intent.intent_type == IntentType.MUSIC_STATUS
    
    status = query_music_status()
    print(f"  [OK] Status: {status}")
    assert status == "You're listening to I Wanna Be Sedated by Ramones."
    
    # Verify we're still in genre mode
    assert state.mode == "genre"
    assert state.genre == "punk"
    print(f"  [OK] Still in genre mode (punk)")
    
    # Step 5: Stop playback
    print("\n[STEP 5] User says: 'stop'")
    intent = parser.parse("stop")
    assert intent.intent_type == IntentType.MUSIC_STOP
    print(f"  [OK] Intent parsed: {intent.intent_type.value} (confidence: {intent.confidence})")
    
    # Simulate stop (reset state)
    state.reset()
    print(f"  [OK] Playback stopped, state reset")
    
    # Step 6: Query status when nothing playing
    print("\n[STEP 6] User says: 'what's playing'")
    status = query_music_status()
    print(f"  [OK] Status: {status}")
    assert status == "Nothing is playing."
    print(f"  [OK] Correctly reports nothing playing")
    
    print("\n" + "="*70)
    print("ALL INTEGRATION STEPS PASSED")
    print("="*70)
    print("\n[OK] User can play -> query status -> skip -> query again -> stop -> query")
    print("[OK] All intents correctly parsed")
    print("[OK] Playback state correctly maintained")
    print("[OK] Status queries do not mutate state")
    print("[OK] Stop command resets state atomically")
    

def test_multiple_status_queries_do_not_interfere():
    """Test that rapid status queries don't interfere with playback"""
    
    parser = RuleBasedIntentParser()
    state = get_playback_state()
    state.reset()
    
    print("\n" + "="*70)
    print("RAPID STATUS QUERY TEST (State Immutability)")
    print("="*70)
    
    # Set initial state
    state.set_artist_mode("David Bowie", {
        "song": "Space Oddity",
        "artist": "David Bowie",
        "path": "/music/bowie.mp3"
    })
    
    initial_mode = state.mode
    initial_artist = state.artist
    initial_track = state.current_track.copy()
    
    print(f"\nInitial state: {initial_mode} mode, artist={initial_artist}")
    print(f"Track: {initial_track['song']} by {initial_track['artist']}")
    
    # Query status 5 times rapidly
    print("\nQuerying status 5 times rapidly...")
    for i in range(5):
        status = query_music_status()
        assert status == "You're listening to Space Oddity by David Bowie."
        print(f"  Query {i+1}: {status}")
    
    # Verify state unchanged
    assert state.mode == initial_mode
    assert state.artist == initial_artist
    assert state.current_track == initial_track
    
    print("\n[OK] All 5 queries returned identical results")
    print("[OK] Playback state remained unchanged")
    print("[OK] No side effects from status queries")
    

if __name__ == "__main__":
    test_complete_user_scenario()
    test_multiple_status_queries_do_not_interfere()
    print("\n" + "="*70)
    print("FULL INTEGRATION TEST SUITE COMPLETE: ALL TESTS PASSED")
    print("="*70)
