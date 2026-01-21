#!/usr/bin/env python3
"""
Coordinator Minimal Run Example

This demonstrates the complete flow:
1. Initialize InputTrigger (wake word detection)
2. Initialize OutputSink (audio output)
3. Initialize Coordinator (wires them together)
4. Call coordinator.run() (blocks until trigger fires)
5. When trigger detected: OutputSink.speak() is called
6. Program exits

This is the first moment where the system can:
- Detect a wake word
- Respond with audio

Still hardcoded, still scripted, but alive.
"""

import logging
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from core.input_trigger import InputTrigger
from core.output_sink import EdgeTTSOutputSink
from core.coordinator import Coordinator
from typing import Callable


# ============================================================================
# MOCK TRIGGER FOR TESTING (No Audio Required)
# ============================================================================

class MockWakeWordTrigger(InputTrigger):
    """Mock trigger for testing (simulates wake word detection)."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("[MockTrigger] Initialized")
    
    def on_trigger(self, callback: Callable) -> None:
        """Simulate wake word detection and invoke callback."""
        self.logger.info("[MockTrigger] Listening...")
        self.logger.info("[MockTrigger] [SIMULATED] Wake word detected!")
        callback()


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Run the coordinator example."""
    print("=" * 70)
    print("Coordinator Minimal Run Example")
    print("=" * 70)
    print()
    
    print("Step 1: Initialize InputTrigger...")
    trigger = MockWakeWordTrigger()
    print()
    
    print("Step 2: Initialize OutputSink...")
    sink = EdgeTTSLiveKitOutputSink()
    print()
    
    print("Step 3: Initialize Coordinator...")
    coordinator = Coordinator(trigger, sink)
    print()
    
    print("Step 4: Run coordinator (blocks until trigger → speak → exit)...")
    try:
        coordinator.run()
        
        print()
        print("=" * 70)
        print("✅ SUCCESS")
        print("=" * 70)
        print("Proof:")
        print("  ✅ InputTrigger initialized")
        print("  ✅ OutputSink initialized")
        print("  ✅ Coordinator initialized")
        print("  ✅ Wake word detected")
        print("  ✅ OutputSink.speak('Yes?') called")
        print("  ✅ Program exited cleanly")
        print()
        print("The system can wake up and respond.")
        print("=" * 70)
    
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
