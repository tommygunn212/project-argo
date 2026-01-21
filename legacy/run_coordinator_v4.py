"""
TASK 15 Run: Coordinator v4 (Session Memory + Music)

Demonstrates the complete local assistant loop:
- Interaction Loop: Wake -> Record -> Transcribe -> Think -> Speak
- Session Memory: Remembers the last 3 turns for context
- Music Control: Can play/stop local music files
- Latency Tracking: Logs timing for every stage

Pipeline (repeats per iteration):
1. Wait for wake word (Porcupine)
2. Record audio (Dynamic silence detection)
3. Transcribe (Whisper)
4. Parse intent (Rules + Music)
5. Generate response (LLM + SessionContext)
6. Speak response (Piper/EdgeTTS)
7. Store interaction in SessionMemory
8. Check stop condition

Stop conditions:
- User says stop command ("stop", "goodbye", etc.)
- OR max interactions reached (hardcoded: 10)
"""

import sys
import logging
import os
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# === Setup Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

def main():
    print("=" * 70)
    print("TASK 15: Coordinator v4 (Memory + Music + Latency)")
    print("=" * 70)

    try:
        # Import pipeline layers
        print("\n[*] Importing pipeline layers...")
        from core.input_trigger import PorcupineWakeWordTrigger
        from core.speech_to_text import WhisperSTT
        from core.intent_parser import RuleBasedIntentParser
        from core.response_generator import LLMResponseGenerator
        from core.output_sink import PiperOutputSink
        from core.coordinator import Coordinator
        
        # Bootstrap music (ensure index exists)
        from core.music_bootstrap import bootstrap_music_system
        print("[*] Bootstrapping music system...")
        music_ready = bootstrap_music_system()
        print(f"    Music System: {'READY' if music_ready else 'DISABLED'}")

        print("[OK] All imports successful")

        # Initialize layers
        print("\n[*] Initializing pipeline layers...")
        
        # 1. Trigger
        print("  [*] InputTrigger (Porcupine)...")
        trigger = PorcupineWakeWordTrigger()
        print("      [OK] Wake word detector ready")

        # 2. STT
        print("  [*] SpeechToText (Whisper)...")
        stt = WhisperSTT()
        print("      [OK] Whisper engine ready")

        # 3. Intent
        print("  [*] IntentParser (Rules)...")
        parser = RuleBasedIntentParser()
        print("      [OK] Intent classifier ready")

        # 4. Generator (LLM)
        print("  [*] ResponseGenerator (LLM)...")
        generator = LLMResponseGenerator()
        print("      [OK] LLM response generator ready")

        # 5. Output Sink
        print("  [*] OutputSink (Piper TTS)...")
        sink = PiperOutputSink()
        print("      [OK] Output sink ready")

        print("[OK] All layers initialized")

        # Initialize Coordinator v4
        print("\n[*] Initializing Coordinator v4...")
        coordinator = Coordinator(
            input_trigger=trigger,
            speech_to_text=stt,
            intent_parser=parser,
            response_generator=generator,
            output_sink=sink,
        )
        print(f"[OK] Coordinator v4 ready")
        print(f"     Memory Capacity: {coordinator.memory.capacity}")

        # Show loop configuration
        print("\n" + "=" * 70)
        print("SYSTEM READY")
        print("=" * 70)
        print(f"\nMax interactions: {coordinator.MAX_INTERACTIONS}")
        print(f"Stop keywords: {', '.join(coordinator.STOP_KEYWORDS)}")
        print("\nCAPABILITIES:")
        print("  [x] Short-term Memory (Context aware)")
        print("  [x] Music Playback (Local files + ID3 tags)")
        print("  [x] Latency Logging (Performance tracking)")
        print("  [x] Silence Detection (Smarter listening)")

        # Run end-to-end flow with loop
        print("\n" + "=" * 70)
        print("LISTENING FOR WAKE WORD...")
        print("=" * 70)
        print("    Speak 'ARGO' or 'PICOVOICE' to start.")
        print()

        coordinator.run()

        print("\n" + "=" * 70)
        print("[OK] SESSION ENDED")
        print(f"Interactions: {coordinator.interaction_count}")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        try:
            # Emergency music stop on Ctrl+C
            from core.music_player import get_music_player
            get_music_player().stop()
        except:
            pass
        return 1
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
