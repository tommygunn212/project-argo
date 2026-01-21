"""
TASK 10 Comprehensive Test: All Intent Types

Tests the full pipeline with different intents to show all response paths.
"""

import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)


class MockTrigger:
    def on_trigger(self, callback):
        callback()


class MockSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio_data, sample_rate):
        return self.text


def test_intent_type(intent_input, expected_type, expected_response):
    """Test a single intent classification and response."""
    from core.intent_parser import RuleBasedIntentParser
    from core.output_sink import EdgeTTSLiveKitOutputSink
    from core.coordinator import Coordinator

    print(f"\n[TEST] Input: '{intent_input}'")
    print(f"       Expected: {expected_type} → '{expected_response}'")

    try:
        trigger = MockTrigger()
        stt = MockSTT(intent_input)
        parser = RuleBasedIntentParser()
        sink = EdgeTTSLiveKitOutputSink()

        coordinator = Coordinator(trigger, stt, parser, sink)

        # Capture what response is actually selected
        original_speak = sink.speak
        actual_response = [None]

        def mock_speak(text):
            actual_response[0] = text
            # Don't actually call the output sink

        sink.speak = mock_speak
        coordinator.run()

        if actual_response[0] == expected_response:
            print(f"       [OK] ✅ Response matched: '{actual_response[0]}'")
            return True
        else:
            print(
                f"       [FAIL] ❌ Got: '{actual_response[0]}' "
                f"(expected: '{expected_response}')"
            )
            return False

    except Exception as e:
        print(f"       [ERROR] {e}")
        return False


def main():
    print("=" * 70)
    print("TASK 10: Comprehensive Intent Classification Test")
    print("=" * 70)

    test_cases = [
        # (input_text, expected_intent_type, expected_response)
        ("hello", "greeting", "Hello."),
        ("hi", "greeting", "Hello."),
        ("what time is it", "question", "I heard a question."),
        ("what's the weather?", "question", "I heard a question."),
        ("why", "question", "I heard a question."),
        ("play music", "command", "I heard a command."),
        ("stop", "command", "I heard a command."),
        ("turn off the lights", "command", "I heard a command."),
        ("xyzabc foobar", "unknown", "I'm not sure what you meant."),
        ("random words here", "unknown", "I'm not sure what you meant."),
    ]

    results = []

    for input_text, expected_type, expected_response in test_cases:
        result = test_intent_type(input_text, expected_type, expected_response)
        results.append(result)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n[OK] SUCCESS - All intent types working correctly")
        return 0
    else:
        print(f"\n[FAIL] {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
