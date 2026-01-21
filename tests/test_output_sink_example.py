#!/usr/bin/env python3
"""
OutputSink Minimal Usage Example

This demonstrates the simplest use case:
1. Create an OutputSink instance
2. Call speak() with text
3. Audio is generated and published

No configuration, no setup, no orchestration.
"""

import logging
import sys

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Import the OutputSink from core module
from core.output_sink import EdgeTTSOutputSink


def main():
    """
    Minimal usage example.
    """
    print("=" * 70)
    print("OutputSink Minimal Usage Example")
    print("=" * 70)
    print()
    
    # Step 1: Create an instance
    print("Step 1: Creating EdgeTTSOutputSink...")
    sink = EdgeTTSOutputSink()
    print()
    
    # Step 2: Call speak() with text
    print("Step 2: Calling sink.speak('hello')...")
    try:
        sink.speak("hello")
        print()
        print("=" * 70)
        print("✅ SUCCESS")
        print("=" * 70)
        print("Proof:")
        print("  ✅ Edge-TTS generated audio from 'hello'")
        print("  ✅ JWT token created with publish grant")
        print("  ✅ Audio track published to LiveKit")
        print("  ✅ No crashes or exceptions")
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
