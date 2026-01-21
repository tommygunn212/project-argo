#!/usr/bin/env python3
"""Quick test to hear Edge-TTS voice output."""

import sys
sys.path.insert(0, 'I:\\argo')

from core.output_sink import EdgeTTSOutputSink

# Create the sink
sink = EdgeTTSOutputSink(voice="en-US-AriaNeural")

# Test sentence
test_sentence = "Hello! This is a test of the Edge-TTS voice system. The audio should sound clear and natural, without any static or squeaking noises."

print(f"[Test] Playing: {test_sentence}")
print()

# Speak it
sink.speak(test_sentence)

print()
print("[Test] Done!")
