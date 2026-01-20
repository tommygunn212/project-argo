"""
TASK 10 Test: Coordinator v1 (End-to-End Flow)

Minimal proof:
1. Initialize all pipeline layers
2. Run Coordinator (orchestrates wake → listen → respond → exit)
3. User speaks after wake word detected
4. System transcribes → classifies → responds
5. Exit cleanly

Full pipeline:
InputTrigger → Audio Capture → SpeechToText → IntentParser → Hardcoded Response → OutputSink → Exit
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
    print("TASK 10: Coordinator v1 (End-to-End)")
    print("=" * 70)

    try:
        # Import pipeline layers
        print("\n[*] Importing pipeline layers...")
        from core.input_trigger import PorcupineWakeWordTrigger
        from core.speech_to_text import WhisperSTT
        from core.intent_parser import RuleBasedIntentParser
        from core.output_sink import EdgeTTSLiveKitOutputSink
        from core.coordinator import Coordinator

        print("[OK] All imports successful")

        # Initialize layers
        print("\n[*] Initializing pipeline layers...")
        print("  [*] InputTrigger (Porcupine)...")
        trigger = PorcupineWakeWordTrigger()
        print("      [OK] Wake word detector ready")

        print("  [*] SpeechToText (Whisper)...")
        stt = WhisperSTT()
        print("      [OK] Whisper engine ready")

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
        print("STARTING END-TO-END PIPELINE")
        print("=" * 70)
        print("\n[*] Waiting for wake word...")
        print("    Speak 'computer' or 'hello' to trigger")
        print()

        coordinator.run()

        print("\n" + "=" * 70)
        print("[OK] SUCCESS")
        print("Pipeline complete: wake → listen → respond → exit")
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
