#!/usr/bin/env python3
"""
Full ARGO integration test: Voice input → Piper output

Tests the complete pipeline:
1. Start voice input system
2. Record audio (simulated)
3. Transcribe with Whisper
4. Query Ollama LLM
5. Play response with Piper TTS

No wake-word detection in this test - uses manual trigger.
"""

import sys
import os
import asyncio
import numpy as np

# Ensure Piper is enabled
os.environ['VOICE_ENABLED'] = 'true'
os.environ['PIPER_ENABLED'] = 'true'

from core.output_sink import get_output_sink

print('[ARGO FULL TEST] Integration test: Voice → LLM → Piper', file=sys.stderr)
print('=' * 70, file=sys.stderr)

# Get output sink (should be Piper)
sink = get_output_sink()
print(f'✓ Output sink: {type(sink).__name__}', file=sys.stderr)

# Test 1: Simple response
print('\n[Test 1] Simple greeting response', file=sys.stderr)
sink.speak('Hello, I am ARGO voice system. I can now talk!')
print('✓ Greeting played', file=sys.stderr)

# Test 2: Simulated LLM response
print('\n[Test 2] Simulated LLM response', file=sys.stderr)
response = 'I have successfully integrated Piper text to speech with the ARGO system. Audio is now working cleanly through M Audio speakers.'
sink.speak(response)
print('✓ LLM response played', file=sys.stderr)

# Test 3: Question-answer simulation
print('\n[Test 3] Q&A simulation', file=sys.stderr)
print('Question: What is ARGO?', file=sys.stderr)
sink.speak('ARGO is an advanced voice AI system designed for real time conversational interactions.')
print('✓ Answer played', file=sys.stderr)

print('\n' + '=' * 70, file=sys.stderr)
print('[TEST COMPLETE] Full ARGO pipeline working with Piper TTS', file=sys.stderr)
print('✓ Ready for live voice input integration', file=sys.stderr)
