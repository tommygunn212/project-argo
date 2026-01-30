#!/usr/bin/env python3
"""
End-to-end test: Voice command → parsed keyword → Jellyfin advanced search → music playback
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
from core.intent_parser import RuleBasedIntentParser, IntentType

def test_voice_to_music_flow():
    """Test complete voice command → music search flow."""
    
    print("Testing Voice Command -> Music Search Flow\n")
    print("="*60)
    
    # Initialize components
    parser = RuleBasedIntentParser()
    music_player = MusicPlayer(provider=MockJellyfinProvider())
    
    if not music_player.jellyfin_provider:
        print("✗ Jellyfin provider not initialized")
        return
    
    # Test scenarios matching real voice commands
    test_cases = [
        ("play metal from 1984", "Advanced: Genre + Year"),
        ("play alice cooper", "Artist search"),
        ("play punk rock", "Compound genre"),
        ("play rock from 1980", "Genre + year"),
        ("play some heavy metal", "Genre with filler words"),
    ]
    
    for voice_command, description in test_cases:
        print(f"\n{'='*60}")
        print(f"Voice Command: '{voice_command}'")
        print(f"Type: {description}")
        print(f"-"*60)
        
        # Step 1: Parse intent
        try:
            intent = parser.parse(voice_command)
            print(f"[1] Intent: {intent.intent_type.value} (confidence={intent.confidence})")
        except Exception as e:
            print(f"✗ Failed to parse intent: {e}")
            continue
        
        # Step 2: Extract keyword
        if intent.keyword:
            print(f"[2] Keyword: '{intent.keyword}'")
        else:
            print(f"[2] Keyword: (None - will play random)")
            continue
        
        # Step 3: Parse keyword for structure
        parsed = music_player._parse_music_keyword(intent.keyword)
        print(f"[3] Parsed Structure:")
        print(f"     - Year: {parsed['year']}")
        print(f"     - Genre: {parsed['genre']}")
        print(f"     - Artist: {parsed['artist']}")
        print(f"     - Query: {parsed['query']}")
        
        # Step 4: Advanced search (simulate)
        print(f"[4] Jellyfin Advanced Search (via play_by_keyword):")
        if parsed.get("year") or parsed.get("genre") or parsed.get("artist"):
            # Use the actual music_player method that's integrated
            tracks = music_player.jellyfin_provider.advanced_search(
                query_text=None,  # Key: Don't use query_text when we have specific filters
                year=parsed.get("year"),
                genre=parsed.get("genre"),
                artist=parsed.get("artist")
            )
            print(f"     Found {len(tracks)} matching tracks")
            if tracks:
                # Show first 3 results
                for i, track in enumerate(tracks[:3], 1):
                    print(f"       {i}. {track['artist']} - {track['song']}")
        else:
            print(f"     (No filters - would use keyword fallback)")
    
    print(f"\n{'='*60}")
    print("✓ End-to-end voice flow test complete!")
    print(f"{'='*60}")

if __name__ == "__main__":
    test_voice_to_music_flow()
