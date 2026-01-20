"""
TASK 9 Test: Intent Parser (Isolated)

Minimal proof:
1. Initialize intent parser
2. Classify hardcoded text strings
3. Print Intent objects
4. Exit

No LLM calls.
No memory.
No personality.
Just rule-based classification.
"""

import sys
from core.intent_parser import RuleBasedIntentParser, IntentType


def main():
    print("=" * 70)
    print("TASK 9: Intent Parser (Isolated)")
    print("=" * 70)

    try:
        # Initialize parser
        print("\n[*] Initializing RuleBasedIntentParser...")
        parser = RuleBasedIntentParser()
        print("[OK] Parser initialized")

        # Test cases (hardcoded)
        test_cases = [
            "hello",
            "hi there",
            "what time is it",
            "what's the weather?",
            "play some music",
            "stop that",
            "this is just random text",
            "good morning",
            "can you help me",
            "turn off the lights",
            "why is the sky blue?",
            "tell me a joke",
        ]

        print("\n" + "=" * 70)
        print("CLASSIFYING TEXT:")
        print("=" * 70)

        for text in test_cases:
            intent = parser.parse(text)
            print(
                f"  Text: '{text}'"
                f"\n    -> {intent.intent_type.value.upper()} "
                f"(confidence: {intent.confidence:.2f})"
            )

        print("\n" + "=" * 70)
        print("[OK] SUCCESS")
        print("Intent parser works (dumb rules, no LLM, no retries)")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
