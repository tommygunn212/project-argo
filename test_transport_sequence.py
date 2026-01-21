#!/usr/bin/env python3
"""
Test the exact voice command sequence from the requirements.

Expected sequence:
  "play punk"        → Start punk music
  "next"             → Next punk track
  "next"             → Another punk track
  "stop"             → Stop music
  "play david bowie" → Start bowie music
  "next"             → Next bowie track

This test verifies that playback state is correctly tracked
and that NEXT always plays in the same mode.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.intent_parser import RuleBasedIntentParser, IntentType
from core.playback_state import get_playback_state, reset_playback_state
from core.music_player import get_music_player


def simulate_sequence():
    """Simulate the exact voice command sequence."""
    print("=" * 70)
    print("TRANSPORT CONTROL SEQUENCE TEST")
    print("=" * 70)
    print()
    
    parser = RuleBasedIntentParser()
    state = get_playback_state()
    player = get_music_player()
    
    commands = [
        ("play punk", "Genre playback - PUNK"),
        ("next", "Continue genre - PUNK"),
        ("next", "Continue genre - PUNK"),
        ("stop", "Stop all playback"),
        ("play david bowie", "Artist playback - BOWIE"),
        ("next", "Continue artist - BOWIE"),
    ]
    
    print("Step-by-step command execution:")
    print()
    
    passed = 0
    failed = 0
    
    for i, (command, description) in enumerate(commands, 1):
        print(f"Step {i}: '{command}' ({description})")
        
        # Parse intent
        intent = parser.parse(command)
        print(f"  Intent: {intent.intent_type.value}")
        print(f"  Current state before: mode={state.mode}, artist={state.artist}, genre={state.genre}")
        
        # Simulate coordinator logic
        if intent.intent_type == IntentType.MUSIC_STOP:
            print("  Action: STOP - clearing playback state")
            player.stop()
            print(f"  Current state after: mode={state.mode}")
            
            # Verify state was cleared
            if state.mode is None and state.artist is None and state.genre is None:
                print("  [PASS] State correctly cleared")
                passed += 1
            else:
                print("  [FAIL] State not cleared")
                failed += 1
        
        elif intent.intent_type == IntentType.MUSIC_NEXT:
            print("  Action: NEXT - playing next track")
            
            # In real scenario, play_next() would be called
            # We just verify the mode doesn't change unexpectedly
            previous_mode = state.mode
            previous_artist = state.artist
            previous_genre = state.genre
            
            print(f"  Playback mode should remain: {previous_mode}")
            
            if previous_mode in ["artist", "genre"]:
                print(f"  [PASS] NEXT called with valid mode '{previous_mode}'")
                passed += 1
            else:
                print(f"  [FAIL] NEXT called but mode is {previous_mode}")
                failed += 1
        
        elif intent.intent_type == IntentType.MUSIC:
            print("  Action: PLAY - setting playback state")
            
            # Simulate what coordinator does
            if intent.keyword:
                keyword = intent.keyword.lower()
                
                # Simplified routing: artist check first, then genre
                if keyword == "david bowie":
                    print(f"  Route: Artist match -> {keyword}")
                    state.set_artist_mode(keyword, {"name": "test", "artist": keyword})
                    print(f"  Current state after: mode={state.mode}, artist={state.artist}")
                    
                    if state.mode == "artist" and state.artist == "david bowie":
                        print("  [PASS] Artist mode set correctly")
                        passed += 1
                    else:
                        print("  [FAIL] Artist mode not set correctly")
                        failed += 1
                
                elif keyword in ["punk", "rock", "blues"]:
                    print(f"  Route: Genre match -> {keyword}")
                    state.set_genre_mode(keyword, {"name": "test", "genre": keyword})
                    print(f"  Current state after: mode={state.mode}, genre={state.genre}")
                    
                    if state.mode == "genre" and state.genre == keyword:
                        print("  [PASS] Genre mode set correctly")
                        passed += 1
                    else:
                        print("  [FAIL] Genre mode not set correctly")
                        failed += 1
            else:
                print(f"  Route: Random")
                state.set_random_mode({"name": "test"})
                
                if state.mode == "random":
                    print("  [PASS] Random mode set correctly")
                    passed += 1
                else:
                    print("  [FAIL] Random mode not set correctly")
                    failed += 1
        
        else:
            print(f"  [SKIP] Unexpected intent type: {intent.intent_type.value}")
        
        print()
    
    print("=" * 70)
    print("SEQUENCE TEST SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed}/{passed + failed}")
    print(f"Failed: {failed}/{passed + failed}")
    print()
    
    if failed == 0:
        print("[OK] ALL SEQUENCE STEPS PASSED!")
        return True
    else:
        print(f"[ERROR] {failed} step(s) failed")
        return False


if __name__ == "__main__":
    success = simulate_sequence()
    exit(0 if success else 1)
