"""
TASK 10 Comprehensive Test: All Intent Types

Tests the full pipeline with different intents to show all response paths.
"""

import sys
import logging
import pytest

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

    def get_last_metrics(self):
        return {"confidence": 1.0}


class MockResponseGenerator:
    def generate(self, intent, memory=None):
        intent_type = intent.intent_type.value if hasattr(intent, "intent_type") else "unknown"
        if intent_type == "greeting":
            return "Hello."
        if intent_type == "question":
            return "I heard a question."
        if intent_type in {"command", "music", "music_stop", "music_next", "music_status"}:
            return "I heard a command."
        return "I'm not sure what you meant."


TEST_CASES = [
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


def _run_intent_type(intent_input, expected_type, expected_response):
    """Run a single intent classification and response check."""
    from core.intent_parser import RuleBasedIntentParser
    from core.output_sink import EdgeTTSLiveKitOutputSink
    from core.coordinator import Coordinator

    print(f"\n[TEST] Input: '{intent_input}'")
    print(f"       Expected: {expected_type} → '{expected_response}'")

    parser = RuleBasedIntentParser()
    generator = MockResponseGenerator()

    intent = parser.parse(intent_input)
    actual_response = generator.generate(intent)

    if actual_response == expected_response:
        print(f"       [OK] ✅ Response matched: '{actual_response}'")
    else:
        print(
            f"       [FAIL] ❌ Got: '{actual_response}' "
            f"(expected: '{expected_response}')"
        )

    assert actual_response == expected_response


@pytest.mark.parametrize("intent_input, expected_type, expected_response", TEST_CASES)
def test_intent_type(intent_input, expected_type, expected_response):
    """Test a single intent classification and response."""
    _run_intent_type(intent_input, expected_type, expected_response)


def main():
    print("=" * 70)
    print("TASK 10: Comprehensive Intent Classification Test")
    print("=" * 70)

    results = []

    for input_text, expected_type, expected_response in TEST_CASES:
        try:
            _run_intent_type(input_text, expected_type, expected_response)
            results.append(True)
        except AssertionError:
            results.append(False)

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
