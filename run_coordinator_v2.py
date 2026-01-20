"""
TASK 12 Run: Coordinator v2 (LLM Response Integration)

Full end-to-end pipeline demonstrating LLM-based responses:
1. Initialize all pipeline layers (including ResponseGenerator)
2. Run Coordinator v2
3. User speaks after wake word detected
4. System transcribes → classifies → generates (via LLM) → responds
5. Exit cleanly

Pipeline:
InputTrigger → Audio Capture → SpeechToText → IntentParser → ResponseGenerator (LLM) → OutputSink → Exit
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
    print("TASK 12: Coordinator v2 (LLM Response Integration)")
    print("=" * 70)

    try:
        # Import pipeline layers
        print("\n[*] Importing pipeline layers...")
        from core.input_trigger import PorcupineWakeWordTrigger
        from core.speech_to_text import WhisperSTT
        from core.intent_parser import RuleBasedIntentParser
        from core.response_generator import LLMResponseGenerator
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

        print("  [*] ResponseGenerator (LLM)...")
        generator = LLMResponseGenerator()
        print("      [OK] LLM response generator ready")

        print("  [*] OutputSink (Edge-TTS + LiveKit)...")
        sink = EdgeTTSLiveKitOutputSink()
        print("      [OK] Audio output ready")

        print("[OK] All layers initialized")

        # Initialize Coordinator v2
        print("\n[*] Initializing Coordinator v2...")
        coordinator = Coordinator(
            input_trigger=trigger,
            speech_to_text=stt,
            intent_parser=parser,
            response_generator=generator,
            output_sink=sink,
        )
        print("[OK] Coordinator v2 ready")

        # Run end-to-end flow
        print("\n" + "=" * 70)
        print("STARTING END-TO-END PIPELINE (WITH LLM)")
        print("=" * 70)
        print("\n[*] Waiting for wake word...")
        print("    Speak 'computer' or 'hello' to trigger")
        print()

        coordinator.run()

        print("\n" + "=" * 70)
        print("[OK] SUCCESS")
        print("Pipeline complete: wake → listen → generate (LLM) → respond → exit")
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
