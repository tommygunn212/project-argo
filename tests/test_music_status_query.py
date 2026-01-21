"""
Test suite for MUSIC_STATUS query feature ("what's playing")
Validates read-only status queries without side effects
"""

import pytest
from core.playback_state import PlaybackState, get_playback_state
from core.music_status import query_music_status


class TestMusicStatusQuery:
    """Test the query_music_status() function behavior"""
    
    def setup_method(self):
        """Reset playback state before each test"""
        state = get_playback_state()
        state.reset()
    
    def test_nothing_playing_returns_correct_response(self):
        """Test response when no track is playing"""
        state = get_playback_state()
        state.current_track = None
        
        status = query_music_status()
        assert status == "Nothing is playing."
    
    def test_song_and_artist_returns_full_format(self):
        """Test response with both song and artist"""
        state = get_playback_state()
        state.current_track = {
            "song": "Blitzkrieg Bop",
            "artist": "Ramones",
            "path": "/music/punk/ramones.mp3"
        }
        
        status = query_music_status()
        assert status == "You're listening to Blitzkrieg Bop by Ramones."
    
    def test_song_only_returns_song_format(self):
        """Test response with only song name"""
        state = get_playback_state()
        state.current_track = {
            "song": "Blitzkrieg Bop",
            "path": "/music/punk/song.mp3"
        }
        
        status = query_music_status()
        assert status == "You're listening to Blitzkrieg Bop."
    
    def test_artist_only_returns_artist_format(self):
        """Test response with only artist name"""
        state = get_playback_state()
        state.current_track = {
            "artist": "Ramones",
            "path": "/music/punk/song.mp3"
        }
        
        status = query_music_status()
        assert status == "You're listening to Ramones."
    
    def test_fallback_when_no_song_or_artist(self):
        """Test fallback response when track has neither song nor artist"""
        state = get_playback_state()
        state.current_track = {
            "path": "/music/unknown.mp3"
        }
        
        status = query_music_status()
        assert status == "Music is playing."
    
    def test_query_does_not_mutate_state(self):
        """Test that querying status does not modify playback state"""
        state = get_playback_state()
        state.set_genre_mode("punk", {
            "song": "Blitzkrieg Bop",
            "artist": "Ramones",
            "path": "/music/punk/song.mp3"
        })
        
        # Record initial state
        initial_mode = state.mode
        initial_genre = state.genre
        initial_track = state.current_track
        initial_artist_mode = state.artist
        
        # Query status
        status = query_music_status()
        
        # Verify state unchanged
        assert state.mode == initial_mode
        assert state.genre == initial_genre
        assert state.current_track == initial_track
        assert state.artist == initial_artist_mode
        
        # Verify response is correct
        assert status == "You're listening to Blitzkrieg Bop by Ramones."
    
    def test_query_after_artist_mode(self):
        """Test status query when in artist mode"""
        state = get_playback_state()
        state.set_artist_mode("David Bowie", {
            "song": "Space Oddity",
            "artist": "David Bowie",
            "path": "/music/bowie/space.mp3"
        })
        
        status = query_music_status()
        assert status == "You're listening to Space Oddity by David Bowie."
        # Verify mode unchanged
        assert state.mode == "artist"
        assert state.artist == "David Bowie"
    
    def test_query_after_random_mode(self):
        """Test status query when in random mode"""
        state = get_playback_state()
        state.set_random_mode({
            "song": "Random Song",
            "artist": "Random Artist",
            "path": "/music/random.mp3"
        })
        
        status = query_music_status()
        assert status == "You're listening to Random Song by Random Artist."
        # Verify mode unchanged
        assert state.mode == "random"


class TestMusicStatusIntegration:
    """Test status queries in realistic scenarios"""
    
    def setup_method(self):
        """Reset playback state before each test"""
        state = get_playback_state()
        state.reset()
    
    def test_multiple_queries_return_same_result(self):
        """Test that repeated queries return identical results"""
        state = get_playback_state()
        state.set_genre_mode("punk", {
            "song": "Blitzkrieg Bop",
            "artist": "Ramones",
            "path": "/music/punk/song.mp3"
        })
        
        # Query multiple times
        status1 = query_music_status()
        status2 = query_music_status()
        status3 = query_music_status()
        
        # All should be identical
        assert status1 == status2 == status3
        assert status1 == "You're listening to Blitzkrieg Bop by Ramones."
    
    def test_query_respects_special_characters_in_names(self):
        """Test that status handles special characters in song/artist names"""
        state = get_playback_state()
        state.current_track = {
            "song": "Song's Got a Dash-mark",
            "artist": "Artist & Band (Remix)",
            "path": "/music/special.mp3"
        }
        
        status = query_music_status()
        assert status == "You're listening to Song's Got a Dash-mark by Artist & Band (Remix)."
    
    def test_status_before_and_after_reset(self):
        """Test status transitions from playing to nothing"""
        state = get_playback_state()
        
        # Initially nothing
        assert query_music_status() == "Nothing is playing."
        
        # Set a track
        state.set_genre_mode("punk", {
            "song": "Blitzkrieg Bop",
            "artist": "Ramones",
            "path": "/music/punk/song.mp3"
        })
        assert query_music_status() == "You're listening to Blitzkrieg Bop by Ramones."
        
        # Reset to nothing
        state.reset()
        assert query_music_status() == "Nothing is playing."
    
    def test_query_with_empty_string_fields(self):
        """Test handling of empty string values in track dict"""
        state = get_playback_state()
        state.current_track = {
            "song": "Valid Song",
            "artist": "",  # Empty artist
            "path": "/music/song.mp3"
        }
        
        # Should treat empty string as missing
        status = query_music_status()
        assert status == "You're listening to Valid Song."


# Test for integration with IntentParser
class TestMusicStatusIntentParsing:
    """Verify that intent parser correctly identifies MUSIC_STATUS intents"""
    
    def test_intent_parser_recognizes_whats_playing_phrase(self):
        """Test that parser recognizes 'what's playing' as MUSIC_STATUS"""
        from core.intent_parser import RuleBasedIntentParser
        parser = RuleBasedIntentParser()
        
        intent = parser.parse("what's playing")
        assert intent.intent_type.name == "MUSIC_STATUS"
        assert intent.confidence == 1.0
    
    def test_intent_parser_recognizes_what_is_playing(self):
        """Test that parser recognizes 'what is playing' as MUSIC_STATUS"""
        from core.intent_parser import RuleBasedIntentParser
        parser = RuleBasedIntentParser()
        
        intent = parser.parse("what is playing")
        assert intent.intent_type.name == "MUSIC_STATUS"
        assert intent.confidence == 1.0
    
    def test_intent_parser_recognizes_what_song_is_this(self):
        """Test that parser recognizes 'what song is this' as MUSIC_STATUS"""
        from core.intent_parser import RuleBasedIntentParser
        parser = RuleBasedIntentParser()
        
        intent = parser.parse("what song is this")
        assert intent.intent_type.name == "MUSIC_STATUS"
        assert intent.confidence == 1.0
    
    def test_intent_parser_recognizes_what_am_i_listening_to(self):
        """Test that parser recognizes 'what am i listening to' as MUSIC_STATUS"""
        from core.intent_parser import RuleBasedIntentParser
        parser = RuleBasedIntentParser()
        
        intent = parser.parse("what am i listening to")
        assert intent.intent_type.name == "MUSIC_STATUS"
        assert intent.confidence == 1.0


class TestMusicStatusResponseFormats:
    """Comprehensive validation of all possible response formats"""
    
    def setup_method(self):
        """Reset playback state before each test"""
        state = get_playback_state()
        state.reset()
    
    def test_response_format_includes_you_are_listening(self):
        """Test that responses start with 'You're listening to' when track exists"""
        state = get_playback_state()
        state.current_track = {
            "song": "Test Song",
            "artist": "Test Artist",
            "path": "/test.mp3"
        }
        
        status = query_music_status()
        assert status.startswith("You're listening to")
    
    def test_response_format_punctuation(self):
        """Test that all responses end with proper punctuation"""
        state = get_playback_state()
        
        # Test: Nothing playing
        state.current_track = None
        assert query_music_status().endswith(".")
        
        # Test: Song and artist
        state.current_track = {"song": "A", "artist": "B", "path": "/x.mp3"}
        assert query_music_status().endswith(".")
        
        # Test: Song only
        state.current_track = {"song": "A", "path": "/x.mp3"}
        assert query_music_status().endswith(".")
        
        # Test: Artist only
        state.current_track = {"artist": "B", "path": "/x.mp3"}
        assert query_music_status().endswith(".")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
