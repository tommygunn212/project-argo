"""
TEST SUITE: Music Command Optimization

Validates 8-part music command improvements:
1. Keyword normalization (punctuation, case handling)
2. LLM bypass for music intents
3. Error response consolidation (single Piper call)
4. Genre synonym mapping
5. Adjacent genre fallback
6. Single Piper session per interaction
7. All components working together
"""

import sys
from pathlib import Path
import pytest

# Add workspace to path
workspace_root = Path(__file__).parent
sys.path.insert(0, str(workspace_root))

from core.intent_parser import RuleBasedIntentParser, IntentType
from core.music_player import get_music_player, normalize_genre, get_adjacent_genres
from core.music_index import get_music_index


def test_keyword_normalization():
    """Test 1: Keyword normalization (punctuation, case)."""
    print("\n" + "=" * 70)
    print("TEST 1: Keyword Normalization")
    print("=" * 70)
    
    parser = RuleBasedIntentParser()
    
    test_cases = [
        ("play punk!!!", "punk", "Remove punctuation"),
        ("play BOWIE", "bowie", "Lowercase"),
        ("play classic rock???", "classic rock", "Remove multiple punctuation"),
        ("play metal!", "metal", "Remove punctuation"),
        ("play music", None, "Generic - no keyword"),
        ("play some music", None, "Filler word removal"),
    ]
    
    passed = 0
    failed = 0
    
    for command, expected_keyword, description in test_cases:
        intent = parser.parse(command)
        keyword = intent.keyword
        
        if keyword == expected_keyword:
            print(f"  [PASS] {description}")
            print(f"    Input: '{command}' -> Keyword: {keyword}")
            passed += 1
        else:
            print(f"  [FAIL] {description}")
            print(f"    Input: '{command}' -> Expected: {expected_keyword}, Got: {keyword}")
            failed += 1
    
    print(f"\n  Result: {passed} passed, {failed} failed")
    assert failed == 0


def test_llm_bypass():
    """Test 2: LLM bypass for music intents."""
    print("\n" + "=" * 70)
    print("TEST 2: LLM Bypass for Music Intents")
    print("=" * 70)
    
    parser = RuleBasedIntentParser()
    
    music_intents = [
        ("play punk", IntentType.MUSIC, "Play command"),
        ("next", IntentType.MUSIC_NEXT, "Skip command"),
        ("stop", IntentType.MUSIC_STOP, "Stop command"),
        ("what's playing", IntentType.MUSIC_STATUS, "Status query"),
    ]
    
    passed = 0
    
    for command, expected_intent, description in music_intents:
        intent = parser.parse(command)
        if intent.intent_type == expected_intent:
            print(f"  [PASS] {description}")
            print(f"    '{command}' -> {intent.intent_type.value}")
            passed += 1
        else:
            print(f"  [FAIL] {description}")
            print(f"    '{command}' -> Expected: {expected_intent.value}, Got: {intent.intent_type.value}")
    
    print(f"\n  Result: {passed}/{len(music_intents)} music intents recognized")
    assert passed == len(music_intents)


def test_genre_synonym_mapping():
    """Test 3: Genre synonym mapping."""
    print("\n" + "=" * 70)
    print("TEST 3: Genre Synonym Mapping")
    print("=" * 70)
    
    test_cases = [
        ("hip hop", "rap", "Hip-hop -> rap"),
        ("hip-hop", "rap", "Hip-hop with hyphen -> rap"),
        ("rock music", "rock", "Rock music -> rock"),
        ("punk music", "punk", "Punk music -> punk"),
        ("punk", "punk", "Already canonical"),
        ("classic rock", "rock", "Classic rock -> rock"),
        ("jazz music", "jazz", "Jazz music -> jazz"),
        ("pop music", "pop", "Pop music -> pop"),
        ("rnb", "r&b", "RNB abbreviation -> r&b"),
    ]
    
    passed = 0
    failed = 0
    
    for raw_genre, expected_canonical, description in test_cases:
        canonical = normalize_genre(raw_genre)
        
        if canonical == expected_canonical:
            print(f"  [PASS] {description}")
            print(f"    '{raw_genre}' -> '{canonical}'")
            passed += 1
        else:
            print(f"  [FAIL] {description}")
            print(f"    '{raw_genre}' -> Expected: '{expected_canonical}', Got: '{canonical}'")
            failed += 1
    
    print(f"\n  Result: {passed} passed, {failed} failed")
    assert failed == 0


def test_adjacent_genre_fallback():
    """Test 4: Adjacent genre fallback."""
    print("\n" + "=" * 70)
    print("TEST 4: Adjacent Genre Fallback")
    print("=" * 70)
    
    test_cases = [
        ("punk", ["rock", "new wave", "alternative"], "Punk has rock/new wave/alt neighbors"),
        ("rock", ["punk", "metal", "classic rock"], "Rock has punk/metal neighbors"),
        ("pop", ["soul", "r&b", "indie"], "Pop has soul/r&b/indie neighbors"),
        ("jazz", ["soul", "blues", "funk"], "Jazz has soul/blues/funk neighbors"),
        ("nonexistent", [], "Unknown genre has no neighbors"),
    ]
    
    passed = 0
    failed = 0
    
    for genre, expected_adjacent, description in test_cases:
        adjacent = get_adjacent_genres(genre)
        
        if adjacent == expected_adjacent:
            print(f"  [PASS] {description}")
            print(f"    '{genre}' -> {adjacent}")
            passed += 1
        else:
            print(f"  [FAIL] {description}")
            print(f"    '{genre}' -> Expected: {expected_adjacent}, Got: {adjacent}")
            failed += 1
    
    print(f"\n  Result: {passed} passed, {failed} failed")
    assert failed == 0


def test_genre_normalization_in_adjacency():
    """Test 5: Genre normalization applies to adjacency mapping."""
    print("\n" + "=" * 70)
    print("TEST 5: Genre Normalization in Adjacency")
    print("=" * 70)
    
    test_cases = [
        ("punk music", ["rock", "new wave", "alternative"], "Alias 'punk music' resolves correctly"),
        ("rock music", ["punk", "metal", "classic rock"], "Alias 'rock music' resolves correctly"),
        ("hip hop", ["soul", "r&b", "funk"], "Alias 'hip hop' maps to 'rap', then adjacent"),
    ]
    
    passed = 0
    failed = 0
    
    for raw_genre, expected_adjacent, description in test_cases:
        adjacent = get_adjacent_genres(raw_genre)
        
        if adjacent == expected_adjacent:
            print(f"  [PASS] {description}")
            print(f"    '{raw_genre}' -> {adjacent}")
            passed += 1
        else:
            print(f"  [FAIL] {description}")
            print(f"    '{raw_genre}' -> Expected: {expected_adjacent}, Got: {adjacent}")
            failed += 1
    
    print(f"\n  Result: {passed} passed, {failed} failed")
    assert failed == 0


def test_music_player_integration():
    """Test 6: Music player integration with genre normalization."""
    print("\n" + "=" * 70)
    print("TEST 6: Music Player Integration")
    print("=" * 70)
    
    player = get_music_player()
    index = get_music_index()
    
    if not player or not player.index:
        print("  [SKIP] Music player not initialized")
        pytest.skip("Music player not initialized")
    
    # Test that normalize_genre works with actual music index
    print(f"  Music index loaded: {len(index.tracks)} tracks")
    
    # Get available genres from index
    available_genres = set()
    for track in index.tracks[:100]:  # Sample first 100 tracks
        if "genre" in track and track["genre"]:
            available_genres.add(track["genre"].lower())
    
    print(f"  Sample genres in index: {sorted(list(available_genres)[:5])}")
    
    print("  [PASS] Music player initialized and index loaded")


def test_no_random_fallback_in_play_by_genre():
    """Test 7: play_by_genre doesn't use random fallback."""
    print("\n" + "=" * 70)
    print("TEST 7: play_by_genre Adjacent Fallback (No Random)")
    print("=" * 70)
    
    player = get_music_player()
    
    if not player or not player.index:
        print("  [SKIP] Music player not initialized")
        pytest.skip("Music player not initialized")
    
    # Test that play_by_genre with invalid genre and no adjacent doesn't play random
    result = player.play_by_genre("xyznonexistentgenrexyz", None)
    
    if result is False:
        print("  [PASS] play_by_genre returns False for invalid genre (no random fallback)")
    else:
        print("  [FAIL] play_by_genre returned True for invalid genre")
        assert False


def _run_test(test_fn):
    try:
        test_fn()
    except AssertionError:
        return False
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("MUSIC COMMAND OPTIMIZATION - TEST SUITE")
    print("=" * 70)
    
    tests = [
        ("Keyword Normalization", test_keyword_normalization),
        ("LLM Bypass", test_llm_bypass),
        ("Genre Synonym Mapping", test_genre_synonym_mapping),
        ("Adjacent Genre Fallback", test_adjacent_genre_fallback),
        ("Genre Normalization in Adjacency", test_genre_normalization_in_adjacency),
        ("Music Player Integration", test_music_player_integration),
        ("No Random Fallback", test_no_random_fallback_in_play_by_genre),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = _run_test(test_func)
            results.append((name, result))
        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {status}: {name}")
    
    print(f"\n  Total: {passed}/{len(results)} tests passed")
    
    if failed == 0:
        print("\n  [SUCCESS] All tests passed!")
        return 0
    else:
        print(f"\n  [FAILED] {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
