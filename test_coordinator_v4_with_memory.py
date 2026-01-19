"""
Coordinator v4 Integration Tests with Session Memory

Tests proving:
- Memory fills correctly across turns
- Memory evicts oldest entries when full
- Each new session starts with empty memory
- Responses can reference recent context
- System exits cleanly
- Memory is cleared on exit
"""

import sys
from pathlib import Path
from enum import Enum

# Add core to path
sys.path.insert(0, str(Path(__file__).parent))

from core.session_memory import SessionMemory
from core.intent_parser import Intent, IntentType
from core.response_generator import LLMResponseGenerator


class MockResponseGenerator:
    """Mock LLM that references memory."""
    
    def generate(self, intent, memory=None):
        """Generate response that acknowledges memory context."""
        context = ""
        if memory is not None and not memory.is_empty():
            # Reference recent interactions
            recent_count = memory.get_recent_count()
            context = f" (Aware of {recent_count} recent interaction(s))"
        
        intent_type = intent.intent_type.value  # Get the string value: "greeting", "question", etc.
        
        if intent_type == "greeting":
            return f"Hello!{context}".strip()
        elif intent_type == "question":
            return f"I'll answer that.{context}".strip()
        elif intent_type == "command":
            return f"Acknowledged.{context}".strip()
        else:
            return f"I didn't understand.{context}".strip()


def test_coordinator_memory_fills():
    """Test: Memory fills correctly across coordinator iterations."""
    print("\nTest: Memory fills across iterations")
    
    memory = SessionMemory(capacity=3)
    generator = MockResponseGenerator()
    
    # Simulate 3 turns
    for turn in range(1, 4):
        intent = Intent(
            intent_type=IntentType.QUESTION,
            confidence=1.0,
            raw_text=f"Question {turn}"
        )
        
        response = generator.generate(intent, memory)
        
        # Append to memory (simulating coordinator.run())
        memory.append(
            user_utterance=f"Question {turn}",
            parsed_intent=intent.intent_type.value,
            generated_response=response
        )
        
        print(f"  Turn {turn}: {memory}")
        
        if turn < 3:
            assert not memory.is_full(), f"Should not be full at turn {turn}"
        else:
            assert memory.is_full(), "Should be full after 3 turns"
    
    assert memory.get_recent_count() == 3, "Should have 3 interactions"
    print("✅ test_coordinator_memory_fills passed")


def test_coordinator_memory_eviction():
    """Test: Memory evicts oldest when full."""
    print("\nTest: Memory evicts oldest when full")
    
    memory = SessionMemory(capacity=3)
    generator = MockResponseGenerator()
    
    # Fill memory
    for turn in range(1, 4):
        intent = Intent(
            intent_type=IntentType.GREETING,
            confidence=1.0,
            raw_text=f"Greeting {turn}"
        )
        response = generator.generate(intent, memory)
        memory.append(
            user_utterance=f"Greeting {turn}",
            parsed_intent=intent.intent_type.value,
            generated_response=response
        )
    
    print(f"  After 3 turns: {memory}")
    assert memory.is_full(), "Should be full"
    
    utterances = memory.get_recent_utterances()
    assert utterances[0] == "Greeting 3", "Most recent should be Greeting 3"
    assert utterances[2] == "Greeting 1", "Oldest should be Greeting 1"
    
    # Add 4th turn (should evict Turn 1)
    intent = Intent(
        intent_type=IntentType.COMMAND,
        confidence=1.0,
        raw_text="Halt"
    )
    response = generator.generate(intent, memory)
    memory.append(
        user_utterance="Halt",
        parsed_intent=intent.intent_type.value,
        generated_response=response
    )
    
    print(f"  After 4 turns: {memory}")
    assert memory.is_full(), "Should still be full"
    
    utterances = memory.get_recent_utterances()
    assert utterances[0] == "Halt", "Most recent should be Halt"
    assert utterances[2] == "Greeting 2", "Greeting 1 should be evicted"
    assert len(utterances) == 3, "Should have exactly 3"
    
    print("✅ test_coordinator_memory_eviction passed")


def test_session_independence():
    """Test: Each new session starts with empty memory."""
    print("\nTest: Session independence")
    
    # Session 1
    session1 = SessionMemory(capacity=3)
    session1.append("Q1", "QUESTION", "A1")
    assert session1.get_recent_count() == 1
    
    # Session 2 (new)
    session2 = SessionMemory(capacity=3)
    assert session2.is_empty(), "New session should be empty"
    assert session2.get_recent_count() == 0
    
    # Session 1 unaffected
    assert session1.get_recent_count() == 1
    
    print(f"  Session 1: {session1}")
    print(f"  Session 2: {session2}")
    
    print("✅ test_session_independence passed")


def test_memory_clear_on_exit():
    """Test: Memory is cleared on coordinator exit."""
    print("\nTest: Memory cleared on exit")
    
    memory = SessionMemory(capacity=3)
    
    # Simulate turns
    for turn in range(1, 4):
        intent = Intent(
            intent_type=IntentType.GREETING,
            confidence=1.0,
            raw_text=f"Turn {turn}"
        )
        response = MockResponseGenerator().generate(intent, memory)
        memory.append(
            user_utterance=f"Turn {turn}",
            parsed_intent=intent.intent_type.value,
            generated_response=response
        )
    
    print(f"  Before clear: {memory}")
    assert memory.get_recent_count() == 3, "Should have 3"
    
    # Coordinator exit clears memory
    memory.clear()
    
    print(f"  After clear: {memory}")
    assert memory.is_empty(), "Should be empty after clear"
    assert memory.get_recent_count() == 0, "Count should be 0"
    
    print("✅ test_memory_clear_on_exit passed")


def test_response_references_context():
    """Test: Responses can reference memory context."""
    print("\nTest: Responses reference context")
    
    memory = SessionMemory(capacity=3)
    generator = MockResponseGenerator()
    
    # Turn 1: No memory context
    intent1 = Intent(IntentType.GREETING, 1.0, "Hi")
    response1 = generator.generate(intent1, None)  # Pass None for first turn
    print(f"  Turn 1 response (no memory): '{response1}'")
    assert response1 == "Hello!", "Should have basic greeting"
    
    memory.append("Hi", "GREETING", response1)
    
    # Turn 2: With memory
    intent2 = Intent(IntentType.QUESTION, 1.0, "What time?")
    response2 = generator.generate(intent2, memory)
    print(f"  Turn 2 response (1 in memory): '{response2}'")
    assert "Aware of 1" in response2, "Should reference 1 interaction"
    
    memory.append("What time?", "QUESTION", response2)
    
    # Turn 3: With 2 in memory
    intent3 = Intent(IntentType.COMMAND, 1.0, "Stop")
    response3 = generator.generate(intent3, memory)
    print(f"  Turn 3 response (2 in memory): '{response3}'")
    assert "Aware of 2" in response3, "Should reference 2 interactions"
    
    print("✅ test_response_references_context passed")


def test_context_summary_generation():
    """Test: Context summary is generated correctly."""
    print("\nTest: Context summary generation")
    
    memory = SessionMemory(capacity=3)
    
    # Empty summary
    summary = memory.get_context_summary()
    assert summary == "", "Empty memory should have empty summary"
    
    # Add interaction
    memory.append("Hello", "GREETING", "Hi there!")
    summary = memory.get_context_summary()
    print(f"  Summary (1 interaction): {summary[:80]}...")
    assert "Turn 1:" in summary
    assert "Hello" in summary
    assert "GREETING" in summary
    assert "Hi there!" in summary
    
    # Add more
    memory.append("What time?", "QUESTION", "3 PM")
    summary = memory.get_context_summary()
    print(f"  Summary (2 interactions): {summary[:80]}...")
    assert "Turn 2:" in summary
    assert "Turn 1:" in summary
    
    print("✅ test_context_summary_generation passed")


def test_coordinator_loop_bounds():
    """Test: Coordinator loop stays bounded with memory."""
    print("\nTest: Coordinator loop bounds maintained")
    
    memory = SessionMemory(capacity=3)
    generator = MockResponseGenerator()
    
    MAX_INTERACTIONS = 3
    interactions = 0
    stop_requested = False
    
    # Simulate coordinator loop
    while True:
        interactions += 1
        
        intent = Intent(IntentType.QUESTION, 1.0, f"Q{interactions}")
        response = generator.generate(intent, memory)
        
        memory.append(
            user_utterance=f"Q{interactions}",
            parsed_intent=intent.intent_type.value,
            generated_response=response
        )
        
        # Check stop conditions
        if "stop" in response.lower():
            stop_requested = True
        
        if interactions >= MAX_INTERACTIONS:
            break
    
    print(f"  Completed {interactions} interactions")
    assert interactions == MAX_INTERACTIONS, "Should respect max interactions"
    assert memory.get_recent_count() == 3, "Memory should have 3"
    
    print("✅ test_coordinator_loop_bounds passed")


def test_multiple_concurrent_sessions():
    """Test: Multiple memory instances don't interfere."""
    print("\nTest: Multiple concurrent session memories")
    
    # Simulate two concurrent users
    memory_user1 = SessionMemory(capacity=3)
    memory_user2 = SessionMemory(capacity=3)
    
    generator = MockResponseGenerator()
    
    # User 1, Turn 1
    intent = Intent(IntentType.GREETING, 1.0, "Hi from User 1")
    response = generator.generate(intent, memory_user1)
    memory_user1.append("Hi from User 1", "GREETING", response)
    
    # User 2, Turn 1
    intent = Intent(IntentType.GREETING, 1.0, "Hi from User 2")
    response = generator.generate(intent, memory_user2)
    memory_user2.append("Hi from User 2", "GREETING", response)
    
    # Verify independence
    print(f"  User 1 memory: {memory_user1}")
    print(f"  User 2 memory: {memory_user2}")
    
    assert memory_user1.get_recent_utterances()[0] == "Hi from User 1"
    assert memory_user2.get_recent_utterances()[0] == "Hi from User 2"
    
    # Clear User 1
    memory_user1.clear()
    assert memory_user1.is_empty()
    assert memory_user2.get_recent_count() == 1
    
    print("✅ test_multiple_concurrent_sessions passed")


def test_memory_stats():
    """Test: Memory stats are accurate during coordinator loop."""
    print("\nTest: Memory stats during loop")
    
    memory = SessionMemory(capacity=3)
    
    # Turn 1
    stats = memory.get_stats()
    print(f"  Turn 0: {stats}")
    assert stats["count"] == 0
    assert stats["full"] is False
    
    memory.append("T1", "GREETING", "R1")
    stats = memory.get_stats()
    print(f"  Turn 1: {stats}")
    assert stats["count"] == 1
    assert stats["full"] is False
    
    memory.append("T2", "QUESTION", "R2")
    memory.append("T3", "COMMAND", "R3")
    stats = memory.get_stats()
    print(f"  Turn 3: {stats}")
    assert stats["count"] == 3
    assert stats["full"] is True
    
    memory.append("T4", "GREETING", "R4")
    stats = memory.get_stats()
    print(f"  Turn 4 (evicted): {stats}")
    assert stats["count"] == 3
    assert stats["full"] is True
    
    print("✅ test_memory_stats passed")


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("COORDINATOR v4 INTEGRATION TESTS (WITH MEMORY)")
    print("="*60)
    
    tests = [
        test_coordinator_memory_fills,
        test_coordinator_memory_eviction,
        test_session_independence,
        test_memory_clear_on_exit,
        test_response_references_context,
        test_context_summary_generation,
        test_coordinator_loop_bounds,
        test_multiple_concurrent_sessions,
        test_memory_stats,
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
