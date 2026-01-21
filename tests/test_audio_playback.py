#!/usr/bin/env python3
"""Test sounddevice playback of Piper WAV output"""

import sounddevice as sd
import soundfile as sf
from pathlib import Path

wav_path = Path('audio/piper/piper/test.wav')
audio_data, sample_rate = sf.read(wav_path)

print(f'Playing audio: {len(audio_data)} samples @ {sample_rate} Hz')
print(f'Audio range: min={audio_data.min():.4f}, max={audio_data.max():.4f}')
print(f'Audio dtype: {audio_data.dtype}')

# Try to list available devices
print('\nAvailable audio devices:')
try:
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            marker = " (DEFAULT)" if device.get('is_default') else ""
            print(f'  [{i}] {device["name"]} ({device["max_output_channels"]} channels){marker}')
except Exception as e:
    print(f'  Error listing devices: {e}')

# Play it
print('\nPlaying...')
try:
    sd.play(audio_data, samplerate=sample_rate, blocking=True)
    print('Playback complete')
except Exception as e:
    print(f'ERROR: {e}')
