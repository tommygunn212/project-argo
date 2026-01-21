#!/usr/bin/env python3
"""
Personality System Evaluation Test

Validates that:
1. Examples load correctly for both modes
2. Mild and Claptrap modes return different responses
3. Same question always returns same answer (consistency)
4. Integration with LLMResponseGenerator works
"""

import sys
sys.path.insert(0, r'i:\argo')

from core.personality import get_personality_loader
from core.response_generator import LLMResponseGenerator


def test_personality_loader():
    """Test PersonalityLoader basic functionality."""
    print("=" * 60)
    print("TEST 1: Personality Loader Basics")
    print("=" * 60)
    
    loader = get_personality_loader()
    
    # Test loading examples
    mild_examples = loader.load_examples("mild")
    claptrap_examples = loader.load_examples("claptrap")
    
    print(f"Loaded {len(mild_examples)} Mild examples")
    print(f"Loaded {len(claptrap_examples)} Claptrap examples")
    
    assert len(mild_examples) > 0, "Mild examples should be loaded"
    assert len(claptrap_examples) > 0, "Claptrap examples should be loaded"
    
    print("[PASS] Example loading works\n")


def test_mode_differences():
    """Test that Mild and Claptrap modes produce different answers."""
    print("=" * 60)
    print("TEST 2: Mode Differences (Mild vs Claptrap)")
    print("=" * 60)
    
    loader = get_personality_loader()
    
    test_questions = [
        "Why do cats act offended all the time?",
        "Why does bad coffee taste so bad?",
    ]
    
    for q in test_questions:
        mild = loader.get_example("mild", q)
        claptrap = loader.get_example("claptrap", q)
        
        print(f"\nQuestion: {q}")
        if mild and claptrap:
            print(f"  Mild (first 60 chars): {mild[:60]}...")
            print(f"  Claptrap (first 60 chars): {claptrap[:60]}...")
            assert mild != claptrap, f"Mild and Claptrap should differ for '{q}'"
            print("  [PASS] Answers differ significantly")
        else:
            print(f"  [WARNING] Mild: {mild is not None}, Claptrap: {claptrap is not None}")


def test_consistency():
    """Test that same question returns same answer (consistency)."""
    print("\n" + "=" * 60)
    print("TEST 3: Answer Consistency")
    print("=" * 60)
    
    loader = get_personality_loader()
    q = "Why do cats act offended all the time?"
    
    # Call get_example multiple times
    results = []
    for i in range(5):
        answer = loader.get_example("mild", q)
        results.append(answer)
    
    print(f"Question: {q}")
    print(f"Calling get_example 5 times...")
    
    # Check all results are identical
    for i, result in enumerate(results):
        assert result == results[0], f"Call {i} returned different answer"
    
    print(f"[PASS] All 5 calls returned identical answer")


def test_response_generator_integration():
    """Test that response_generator has personality integration."""
    print("\n" + "=" * 60)
    print("TEST 4: Response Generator Integration")
    print("=" * 60)
    
    gen = LLMResponseGenerator()
    
    print(f"LLMResponseGenerator instantiated")
    assert hasattr(gen, 'personality_loader'), "Should have personality_loader"
    assert hasattr(gen, 'personality_mode'), "Should have personality_mode"
    
    print(f"  personality_loader: {type(gen.personality_loader).__name__}")
    print(f"  personality_mode: {gen.personality_mode}")
    print("[PASS] Integration attributes present")


def test_personality_with_intent_parser():
    """Test personality in response generation context (end-to-end simulation)."""
    print("\n" + "=" * 60)
    print("TEST 5: End-to-End (Response Generator + Personality)")
    print("=" * 60)
    
    loader = get_personality_loader()
    
    test_input = "Why do cats act offended all the time?"
    
    print(f"Input: {test_input}")
    
    # Simulate what response_generator.generate() does
    # (skipping LLM call, just checking personality lookup)
    intent_type = "question"  # This would come from parser
    
    # Get personality example (only for non-command intents)
    if intent_type != "command":
        # This is what response_generator does now with personality injection
        example = loader.get_example("mild", test_input)
        print(f"Personality example found: {example is not None}")
        if example:
            print(f"Example: {example[:80]}...")
            print("[PASS] Personality injection in generate() would return this")
        else:
            print("[WARNING] No example found (would proceed to LLM)")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("PERSONALITY SYSTEM EVALUATION")
    print("=" * 60 + "\n")
    
    try:
        test_personality_loader()
        test_mode_differences()
        test_consistency()
        test_response_generator_integration()
        test_personality_with_intent_parser()
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n[FAILED] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
