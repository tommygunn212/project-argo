"""
TASK 13 Run: Coordinator v3 (Bounded Interaction Loop)

Demonstrates bounded, controlled looping:
- Multiple wake/respond cycles in single session
- Clear stop conditions (user says "stop" OR max reached)
- No memory between turns (each turn independent)
- Clean exit after loop termination

Pipeline (repeats per iteration):
1. Wait for wake word (Porcupine)
2. Record audio
3. Transcribe (Whisper)
4. Parse intent (rules)
5. Generate response (LLM)
6. Speak response
7. Check stop condition
8. Loop continues OR exit cleanly

Stop conditions:
- User says stop command ("stop", "goodbye", etc.)
- OR max interactions reached (hardcoded: 3)

This is NOT conversation or memory:
- No context carryover
- No conversation history
- Each turn is fresh
- LLM doesn't know about previous turns
- Bounded and controlled
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
    print("TASK 13: Coordinator v3 (Bounded Interaction Loop)")
    print("=" * 70)

    try:
        # Import pipeline layers
        print("\n[*] Importing pipeline layers...")
        from core.input_trigger import PorcupineWakeWordTrigger
        from core.speech_to_text import WhisperSTT
        from core.intent_parser import RuleBasedIntentParser
        from core.response_generator import LLMResponseGenerator
        from core.output_sink import EdgeTTSOutputSink
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

        print("  [*] OutputSink (Edge-TTS)...")
        sink = EdgeTTSOutputSink(voice="en-US-AriaNeural")
        print("      [OK] Output sink ready")

        print("[OK] All layers initialized")

        # Initialize Coordinator v3
        print("\n[*] Initializing Coordinator v3 (with loop)...")
        coordinator = Coordinator(
            input_trigger=trigger,
            speech_to_text=stt,
            intent_parser=parser,
            response_generator=generator,
            output_sink=sink,
        )
        print("[OK] Coordinator v3 ready")

        # Show loop configuration
        print("\n" + "=" * 70)
        print("LOOP CONFIGURATION (TASK 13)")
        print("=" * 70)
        print(f"\nMax interactions per session: {coordinator.MAX_INTERACTIONS}")
        print(f"Stop keywords: {', '.join(coordinator.STOP_KEYWORDS)}")
        print("\nLoop will continue UNTIL:")
        print(f"  1. User's response contains a stop keyword")
        print(f"  2. OR max interactions ({coordinator.MAX_INTERACTIONS}) reached")
        print("\nBOUNDED & CONTROLLED:")
        print("  - No memory between turns")
        print("  - No context carryover")
        print("  - Each turn is independent")
        print("  - Clean exit when done")

        # Run end-to-end flow with loop
        print("\n" + "=" * 70)
        print("STARTING INTERACTION LOOP (WITH STOPPING CONDITIONS)")
        print("=" * 70)
        print("\n[*] Waiting for wake word...")
        print("    Speak 'computer' or 'hello' to trigger")
        print(f"    System will continue for up to {coordinator.MAX_INTERACTIONS} interactions")
        print(f"    OR until you get a response containing '{coordinator.STOP_KEYWORDS[0]}'")
        print()

        coordinator.run()

        print("\n" + "=" * 70)
        print("[OK] SUCCESS")
        print(f"Loop completed: {coordinator.interaction_count} interaction(s)")
        if coordinator.stop_requested:
            print("Reason: User requested stop (keyword detected in response)")
        else:
            print(f"Reason: Max interactions ({coordinator.MAX_INTERACTIONS}) reached")
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
