#!/usr/bin/env python3
"""Quick device enumeration."""
import sounddevice

print("Audio input devices:")
for i, d in enumerate(sounddevice.query_devices()):
    if d['max_input_channels'] > 0:
        print(f"  {i}: {d['name']} ({d['max_input_channels']} in)")
