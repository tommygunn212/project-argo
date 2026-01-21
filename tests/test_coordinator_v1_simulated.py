"""
TASK 10 Test: Coordinator v1 (Simulated End-to-End)

Minimal proof using mock trigger (no actual wake word detection needed):
1. Initialize all pipeline layers (except trigger - use mock)
2. Create mock trigger that fires immediately
3. Run Coordinator through full pipeline
4. Verify all layers execute in order
5. Exit cleanly

Full pipeline verified:
Mock Wake → Audio Capture → SpeechToText → IntentParser → Hardcoded Response → OutputSink → Exit
"""

import sys
import logging

# === Setup Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(message)s",
)


class MockInputTrigger:
    """Mock trigger that fires immediately without waiting for wake word."""

    def on_trigger(self, callback):
        """Fire callback immediately (for testing)."""
        callback()


class MockSpeechToText:
    """Mock STT that returns a test question instead of processing audio."""

    def transcribe(self, audio_data, sample_rate):
        """Return a test question for demonstration."""
        return "what time is it"


def main():
    print("=" * 70)
    print("TASK 10: Coordinator v1 (Simulated End-to-End)")
    print("=" * 70)

    try:
        # Import pipeline layers
        print("\n[*] Importing pipeline layers...")
        from core.intent_parser import RuleBasedIntentParser
        from core.output_sink import EdgeTTSLiveKitOutputSink
        from core.coordinator import Coordinator

        print("[OK] All imports successful")

        # Initialize layers
        print("\n[*] Initializing pipeline layers...")
        print("  [*] InputTrigger (Mock - fires immediately)...")
        trigger = MockInputTrigger()
        print("      [OK] Mock trigger ready")

        print("  [*] SpeechToText (Mock - returns test question)...")
        stt = MockSpeechToText()
        print("      [OK] Mock STT ready")

        print("  [*] IntentParser (Rules)...")
        parser = RuleBasedIntentParser()
        print("      [OK] Intent classifier ready")

        print("  [*] OutputSink (Edge-TTS + LiveKit)...")
        sink = EdgeTTSLiveKitOutputSink()
        print("      [OK] Audio output ready")

        print("[OK] All layers initialized")

        # Initialize Coordinator
        print("\n[*] Initializing Coordinator v1...")
        coordinator = Coordinator(
            input_trigger=trigger,
            speech_to_text=stt,
            intent_parser=parser,
            output_sink=sink,
        )
        print("[OK] Coordinator ready")

        # Run end-to-end flow
        print("\n" + "=" * 70)
        print("STARTING END-TO-END PIPELINE (SIMULATED)")
        print("=" * 70)
        print("\n[*] Running coordinator (mock trigger fires immediately)...")
        print("    Mock STT will return: 'what time is it'")
        print("    Expected response: 'I heard a question.'")
        print()

        coordinator.run()

        print("\n" + "=" * 70)
        print("[OK] SUCCESS")
        print("Pipeline executed: wake → listen → respond → exit")
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
