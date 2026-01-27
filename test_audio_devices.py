#!/usr/bin/env python
"""Test all audio devices to find active microphone"""
import sounddevice as sd
import numpy as np

print("=" * 60)
print("AUDIO DEVICE DETECTION TEST")
print("=" * 60)
print()

# Test common microphone indices
test_devices = [1, 2, 10, 20, 21, 35, 36]
print(f"Testing devices: {test_devices}")
print()

SAMPLE_RATE = 16000
DURATION = 2

for device_id in test_devices:
    try:
        info = sd.query_devices(device_id)
        device_name = info['name']
        input_channels = info['max_input_channels']
        
        if input_channels == 0:
            print(f"Device {device_id}: {device_name} - (OUTPUT ONLY, skipping)")
            continue
        
        print(f"Device {device_id}: {device_name}")
        print(f"  Recording {DURATION}s...", end=" ", flush=True)
        
        audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32', device=device_id)
        sd.wait()
        
        volume = np.linalg.norm(audio) * 10
        peak = np.max(np.abs(audio))
        
        print(f"✓")
        print(f"    Volume: {volume:.2f} | Peak: {peak:.4f}")
        
        if volume > 2.0:
            print(f"    🎤 ACTIVE MICROPHONE (high volume)")
        elif volume > 0.5:
            print(f"    🔇 Quiet microphone")
        else:
            print(f"    🔕 Silent/no input")
        print()
        
    except Exception as e:
        print(f"Device {device_id}: ERROR - {str(e)[:60]}")
        print()

print("=" * 60)
print("Find the device with highest volume - that's your active microphone")
print("=" * 60)
