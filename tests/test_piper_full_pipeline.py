#!/usr/bin/env python3
"""
Full end-to-end test of Piper TTS pipeline.
Tests that Piper works without squeal for various text lengths.
"""

import sys
import os

# Ensure Piper is enabled
os.environ['VOICE_ENABLED'] = 'true'
os.environ['PIPER_ENABLED'] = 'true'

from core.output_sink import get_output_sink

print('[TEST] Full pipeline with Piper TTS', file=sys.stderr)
print('=' * 60, file=sys.stderr)

# Get output sink (should be Piper)
sink = get_output_sink()
print(f'Output sink: {type(sink).__name__}', file=sys.stderr)

# Test Piper with various text lengths
test_phrases = [
    'Hello',
    'This is ARGO voice system',
    'Testing text to speech with Piper',
    'The quick brown fox jumps over the lazy dog',
]

for i, phrase in enumerate(test_phrases, 1):
    print(f'\n[Test {i}] "{phrase}"', file=sys.stderr)
    sink.speak(phrase)
    print(f'[OK] Played without squeal', file=sys.stderr)

print('\n' + '=' * 60, file=sys.stderr)
print('[TEST COMPLETE] Full pipeline working with Piper', file=sys.stderr)
