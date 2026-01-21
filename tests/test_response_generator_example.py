"""
TASK 11 Test: Response Generator (LLM, Isolated)

Minimal proof:
1. Create fake Intent objects
2. Pass to ResponseGenerator
3. Print generated responses
4. Exit

No Coordinator wiring.
No OutputSink.
No orchestration.
Just LLM: Intent → Response.
"""

import sys
import logging

# === Setup Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)


def main():
    print("=" * 70)
    print("TASK 11: Response Generator (LLM, Isolated)")
    print("=" * 70)

    try:
        # Import dependencies
        print("\n[*] Importing dependencies...")
        from core.intent_parser import IntentType, Intent
        from core.response_generator import LLMResponseGenerator

        print("[OK] All imports successful")

        # Initialize LLM generator
        print("\n[*] Initializing LLMResponseGenerator...")
        generator = LLMResponseGenerator()
        print("[OK] LLM ready (connected to Ollama)")

        # Test cases: create fake Intent objects
        print("\n[*] Creating test Intent objects...")
        test_cases = [
            Intent(
                intent_type=IntentType.GREETING,
                confidence=0.95,
                raw_text="hello there",
            ),
            Intent(
                intent_type=IntentType.QUESTION,
                confidence=1.0,
                raw_text="what's the weather today?",
            ),
            Intent(
                intent_type=IntentType.COMMAND,
                confidence=0.75,
                raw_text="play some music",
            ),
            Intent(
                intent_type=IntentType.UNKNOWN,
                confidence=0.1,
                raw_text="xyzabc foobar",
            ),
        ]
        print(f"[OK] Created {len(test_cases)} test cases")

        # Generate responses for each intent
        print("\n" + "=" * 70)
        print("GENERATING RESPONSES (LLM):")
        print("=" * 70)

        for i, intent in enumerate(test_cases, 1):
            print(f"\n[Test {i}] Intent: {intent.intent_type.value}")
            print(f"       Text: '{intent.raw_text}'")
            print(f"       Confidence: {intent.confidence:.2f}")
            print(f"       [*] Calling LLM...")

            try:
                response = generator.generate(intent)
                print(f"       [OK] Response: '{response}'")

            except Exception as e:
                print(f"       [ERROR] {e}")
                return 1

        print("\n" + "=" * 70)
        print("[OK] SUCCESS")
        print("LLM response generation works (Intent → Response)")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
