#!/usr/bin/env python3
import sounddevice
import sys

print("Available audio devices:")
print("="*60)

devs = sounddevice.query_devices()
for i, d in enumerate(devs):
    name = d.get("name", "Unknown") if isinstance(d, dict) else d.name
    ins = d.get("max_input_channels", 0) if isinstance(d, dict) else d.max_input_channels
    outs = d.get("max_output_channels", 0) if isinstance(d, dict) else d.max_output_channels
    
    if ins > 0 or outs > 0:
        device_type = "INPUT" if ins > 0 else "OUTPUT"
        print(f"[{i}] {name:40} {device_type:6} (in:{ins} out:{outs})")

print("\nDefault input device:", sounddevice.default.device[0])
print("Default output device:", sounddevice.default.device[1])

# Try to detect Brio
print("\n" + "="*60)
brio_found = any("Brio" in str(d) for d in devs)
if brio_found:
    print("✓ Brio microphone DETECTED")
else:
    print("✗ Brio microphone NOT found")
