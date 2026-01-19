"""
Session Memory Tests

Test suite for SessionMemory functionality:
- Memory fills correctly
- Memory evicts oldest when full
- New session starts empty
- Memory persists across memory append calls
- All layers work together
"""

import sys
from pathlib import Path

# Add core to path
sys.path.insert(0, str(Path(__file__).parent))

from core.session_memory import SessionMemory


def test_memory_creation():
    """Test: Memory initializes empty."""
    memory = SessionMemory(capacity=3)
    
    assert memory.is_empty(), "New memory should be empty"
    assert memory.get_recent_count() == 0, "Count should be 0"
    assert not memory.is_full(), "Should not be full"
    assert len(memory.get_all_interactions()) == 0, "Interactions should be empty"
    
    print("✅ test_memory_creation passed")


def test_memory_append_single():
    """Test: Append single interaction."""
    memory = SessionMemory(capacity=3)
    
    memory.append(
        user_utterance="Hello",
        parsed_intent="GREETING",
        generated_response="Hi there!"
    )
    
    assert not memory.is_empty(), "Memory should not be empty"
    assert memory.get_recent_count() == 1, "Count should be 1"
    assert not memory.is_full(), "Should not be full with capacity 3"
    
    interactions = memory.get_all_interactions()
    assert len(interactions) == 1, "Should have 1 interaction"
    assert interactions[0].user_utterance == "Hello"
    assert interactions[0].parsed_intent == "GREETING"
    assert interactions[0].generated_response == "Hi there!"
    
    print("✅ test_memory_append_single passed")


def test_memory_append_multiple():
    """Test: Append multiple interactions."""
    memory = SessionMemory(capacity=3)
    
    # Add 2 interactions
    memory.append("How are you?", "QUESTION", "I'm doing well, thank you!")
    memory.append("What time is it?", "QUESTION", "It's 3 PM")
    
    assert memory.get_recent_count() == 2, "Count should be 2"
    assert not memory.is_full(), "Should not be full"
    
    utterances = memory.get_recent_utterances()
    assert len(utterances) == 2, "Should have 2 utterances"
    assert utterances[0] == "What time is it?", "First recent should be newest"
    assert utterances[1] == "How are you?", "Second recent should be older"
    
    intents = memory.get_recent_intents()
    assert len(intents) == 2, "Should have 2 intents"
    assert intents[0] == "QUESTION", "Both are questions"
    
    print("✅ test_memory_append_multiple passed")


def test_memory_fill_to_capacity():
    """Test: Memory fills to capacity."""
    memory = SessionMemory(capacity=3)
    
    memory.append("Turn 1", "GREETING", "Hello!")
    memory.append("Turn 2", "QUESTION", "Hi")
    memory.append("Turn 3", "QUESTION", "OK")
    
    assert memory.get_recent_count() == 3, "Should have 3 interactions"
    assert memory.is_full(), "Should be full at capacity"
    
    print("✅ test_memory_fill_to_capacity passed")


def test_memory_eviction():
    """Test: Memory evicts oldest when full."""
    memory = SessionMemory(capacity=3)
    
    # Fill to capacity
    memory.append("Turn 1", "GREETING", "Hello!")
    memory.append("Turn 2", "QUESTION", "Hi")
    memory.append("Turn 3", "QUESTION", "OK")
    
    assert memory.get_recent_count() == 3, "Should have 3"
    assert memory.is_full(), "Should be full"
    
    # Add 4th interaction (should evict Turn 1)
    memory.append("Turn 4", "COMMAND", "Stop")
    
    assert memory.get_recent_count() == 3, "Should still have 3 (eviction)"
    assert memory.is_full(), "Should still be full"
    
    interactions = memory.get_all_interactions()
    assert interactions[0].user_utterance == "Turn 2", "Turn 1 should be evicted"
    assert interactions[1].user_utterance == "Turn 3", "Turn 3 should remain"
    assert interactions[2].user_utterance == "Turn 4", "Turn 4 should be newest"
    
    print("✅ test_memory_eviction passed")


def test_memory_recent_utterances_order():
    """Test: Recent utterances returned in reverse chronological order."""
    memory = SessionMemory(capacity=3)
    
    memory.append("First", "GREETING", "Hello")
    memory.append("Second", "QUESTION", "Hi")
    memory.append("Third", "COMMAND", "OK")
    
    utterances = memory.get_recent_utterances()
    assert utterances[0] == "Third", "Most recent should be first"
    assert utterances[1] == "Second", "Middle should be second"
    assert utterances[2] == "First", "Oldest should be last"
    
    # Get last 2
    recent_2 = memory.get_recent_utterances(n=2)
    assert len(recent_2) == 2, "Should get 2"
    assert recent_2[0] == "Third", "Most recent"
    assert recent_2[1] == "Second", "Second most recent"
    
    print("✅ test_memory_recent_utterances_order passed")


def test_memory_recent_responses_order():
    """Test: Recent responses returned in reverse chronological order."""
    memory = SessionMemory(capacity=3)
    
    memory.append("Q1", "QUESTION", "Response 1")
    memory.append("Q2", "QUESTION", "Response 2")
    memory.append("Q3", "QUESTION", "Response 3")
    
    responses = memory.get_recent_responses()
    assert responses[0] == "Response 3", "Most recent first"
    assert responses[1] == "Response 2", "Second most recent"
    assert responses[2] == "Response 1", "Oldest last"
    
    print("✅ test_memory_recent_responses_order passed")


def test_memory_context_summary():
    """Test: Context summary is human-readable."""
    memory = SessionMemory(capacity=3)
    
    # Empty memory should return empty summary
    assert memory.get_context_summary() == "", "Empty memory should have empty summary"
    
    # Add interactions
    memory.append("Hello", "GREETING", "Hi!")
    summary = memory.get_context_summary()
    assert "Turn 1:" in summary, "Should contain turn marker"
    assert "Hello" in summary, "Should contain utterance"
    assert "GREETING" in summary, "Should contain intent"
    assert "Hi!" in summary, "Should contain response"
    
    # Add more interactions
    memory.append("What time?", "QUESTION", "3 PM")
    summary = memory.get_context_summary()
    assert "Turn 2:" in summary, "Should have turn 2"
    assert "Turn 1:" in summary, "Should still have turn 1"
    
    print("✅ test_memory_context_summary passed")


def test_memory_clear():
    """Test: Memory can be cleared."""
    memory = SessionMemory(capacity=3)
    
    memory.append("Test", "GREETING", "Hello")
    assert memory.get_recent_count() == 1, "Should have 1 interaction"
    
    memory.clear()
    assert memory.is_empty(), "Should be empty after clear"
    assert memory.get_recent_count() == 0, "Count should be 0"
    assert len(memory.get_all_interactions()) == 0, "All interactions cleared"
    
    print("✅ test_memory_clear passed")


def test_memory_stats():
    """Test: Memory stats are correct."""
    memory = SessionMemory(capacity=3)
    
    stats = memory.get_stats()
    assert stats["capacity"] == 3, "Capacity should be 3"
    assert stats["count"] == 0, "Count should be 0"
    assert stats["empty"] is True, "Should be empty"
    assert stats["full"] is False, "Should not be full"
    
    memory.append("Test", "GREETING", "Hello")
    stats = memory.get_stats()
    assert stats["count"] == 1, "Count should be 1"
    assert stats["empty"] is False, "Should not be empty"
    
    memory.append("Test2", "GREETING", "Hello2")
    memory.append("Test3", "GREETING", "Hello3")
    stats = memory.get_stats()
    assert stats["full"] is True, "Should be full"
    
    print("✅ test_memory_stats passed")


def test_memory_capacity_validation():
    """Test: Memory validates capacity."""
    try:
        memory = SessionMemory(capacity=0)
        assert False, "Should raise ValueError for capacity 0"
    except ValueError:
        pass
    
    try:
        memory = SessionMemory(capacity=-1)
        assert False, "Should raise ValueError for negative capacity"
    except ValueError:
        pass
    
    # Valid capacities
    memory1 = SessionMemory(capacity=1)
    assert memory1.capacity == 1
    
    memory10 = SessionMemory(capacity=10)
    assert memory10.capacity == 10
    
    print("✅ test_memory_capacity_validation passed")


def test_memory_multiple_sessions():
    """Test: Each session memory is independent."""
    memory1 = SessionMemory(capacity=3)
    memory2 = SessionMemory(capacity=3)
    
    memory1.append("Session 1", "GREETING", "Hello")
    memory2.append("Session 2", "GREETING", "Hi")
    
    assert memory1.get_recent_count() == 1, "Memory1 should have 1"
    assert memory2.get_recent_count() == 1, "Memory2 should have 1"
    
    assert memory1.get_recent_utterances()[0] == "Session 1"
    assert memory2.get_recent_utterances()[0] == "Session 2"
    
    memory1.clear()
    assert memory1.is_empty(), "Memory1 cleared"
    assert memory2.get_recent_count() == 1, "Memory2 unaffected"
    
    print("✅ test_memory_multiple_sessions passed")


def test_memory_get_n_limit():
    """Test: get_recent_* with n parameter."""
    memory = SessionMemory(capacity=5)
    
    memory.append("U1", "GREETING", "R1")
    memory.append("U2", "QUESTION", "R2")
    memory.append("U3", "COMMAND", "R3")
    memory.append("U4", "GREETING", "R4")
    
    # Get all 4
    all_4 = memory.get_recent_utterances()
    assert len(all_4) == 4
    
    # Get last 2
    last_2 = memory.get_recent_utterances(n=2)
    assert len(last_2) == 2
    assert last_2[0] == "U4", "Most recent"
    assert last_2[1] == "U3", "Second most recent"
    
    # Get last 1
    last_1 = memory.get_recent_utterances(n=1)
    assert len(last_1) == 1
    assert last_1[0] == "U4"
    
    # Get more than available
    more_than_exists = memory.get_recent_utterances(n=100)
    assert len(more_than_exists) == 4, "Should cap at available"
    
    print("✅ test_memory_get_n_limit passed")


def test_memory_interactions_contain_timestamp():
    """Test: Interactions have timestamps."""
    memory = SessionMemory(capacity=3)
    
    memory.append("Test", "GREETING", "Hello")
    interactions = memory.get_all_interactions()
    
    assert len(interactions) == 1
    interaction = interactions[0]
    
    assert hasattr(interaction, "timestamp"), "Should have timestamp"
    assert interaction.timestamp is not None, "Timestamp should not be None"
    assert interaction.user_utterance == "Test"
    assert interaction.parsed_intent == "GREETING"
    assert interaction.generated_response == "Hello"
    
    print("✅ test_memory_interactions_contain_timestamp passed")


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("SESSION MEMORY TEST SUITE")
    print("="*60 + "\n")
    
    tests = [
        test_memory_creation,
        test_memory_append_single,
        test_memory_append_multiple,
        test_memory_fill_to_capacity,
        test_memory_eviction,
        test_memory_recent_utterances_order,
        test_memory_recent_responses_order,
        test_memory_context_summary,
        test_memory_clear,
        test_memory_stats,
        test_memory_capacity_validation,
        test_memory_multiple_sessions,
        test_memory_get_n_limit,
        test_memory_interactions_contain_timestamp,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} error: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
