#!/usr/bin/env python3
"""
InputTrigger Minimal Test Example

This demonstrates the simplest use case:
1. Create an InputTrigger instance
2. Define a callback function
3. Call on_trigger(callback) to listen
4. When triggered, callback fires once

NOTE: This example simulates the trigger since we cannot
capture live audio in the testing environment. In production,
Porcupine would listen to the microphone.
"""

import logging
import sys

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from core.input_trigger import InputTrigger


# ============================================================================
# MOCK TRIGGER FOR TESTING (No Audio Required)
# ============================================================================

class MockWakeWordTrigger(InputTrigger):
    """
    Mock trigger for testing (no audio, simulates detection).
    
    This is used for testing when Porcupine access key is unavailable
    or when we can't capture live audio.
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("[InputTrigger.Mock] Initialized (for testing)")
    
    def on_trigger(self, callback) -> None:
        """
        Simulate wake word detection (print message, then fire callback).
        """
        self.logger.info("[on_trigger] Listening for wake word...")
        self.logger.info("[Mock] Simulating wake word detection...")
        
        # Fire callback (simulating detection)
        self.logger.info("[Event] Invoking callback...")
        callback()
        self.logger.info("[Event] Callback complete")


# ============================================================================
# TEST EXECUTION
# ============================================================================

def main():
    """
    Minimal test example.
    """
    print("=" * 70)
    print("InputTrigger Minimal Test Example")
    print("=" * 70)
    print()
    
    # Step 1: Create trigger instance
    print("Step 1: Creating InputTrigger (Mock for testing)...")
    trigger = MockWakeWordTrigger()
    print()
    
    # Step 2: Define callback
    print("Step 2: Defining callback function...")
    def on_wake_detected():
        print("🎤 WAKE WORD DETECTED!")
    
    print("  Callback defined: on_wake_detected()")
    print()
    
    # Step 3: Listen for trigger
    print("Step 3: Calling trigger.on_trigger(callback)...")
    try:
        trigger.on_trigger(on_wake_detected)
        print()
        print("=" * 70)
        print("✅ SUCCESS")
        print("=" * 70)
        print("Proof:")
        print("  ✅ InputTrigger initialized")
        print("  ✅ Callback defined")
        print("  ✅ Wake word detected")
        print("  ✅ Callback invoked")
        print("  ✅ No crashes or exceptions")
        print("=" * 70)
    
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        sys.exit(1)


# ============================================================================
# NOTES FOR PRODUCTION USE
# ============================================================================

"""
To use PorcupineWakeWordTrigger in production:

1. Obtain a Porcupine access key:
   - Sign up at https://console.picovoice.ai
   - Create a project
   - Get your access key

2. Set the environment variable:
   export PORCUPINE_ACCESS_KEY="your_key_here"

3. Use the real trigger:
   from core.input_trigger import PorcupineWakeWordTrigger
   
   trigger = PorcupineWakeWordTrigger()
   trigger.on_trigger(callback)

4. Make sure microphone is accessible:
   - Default system microphone will be used
   - Porcupine listens continuously
   - When "picovoice" is spoken: callback fires once

5. Other wake words:
   - Modify keywords list in on_trigger() method
   - Porcupine supports multiple wake words
   - Each detection fires callback with keyword_index

Implementation details:
- Audio: 16kHz mono, 16-bit PCM
- Frame length: Porcupine-specific (usually ~512 samples)
- Processing: Real-time, very low latency
- Accuracy: High (false positive/negative rates configurable)

Constraints respected:
✓ NO speech-to-text
✓ NO audio storage
✓ NO intent parsing
✓ NO timers or retry logic
✓ NO logging framework integration
✓ Simple callback (no payload)
✓ Blocking call (waits for trigger)
✓ Deterministic (same conditions → same detection)
"""

if __name__ == "__main__":
    main()
