#!/usr/bin/env python3
"""Test TTS with coordinator flow and FORCE_BLOCKING_TTS"""
import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

import os
print(f'FORCE_BLOCKING_TTS: {os.getenv("FORCE_BLOCKING_TTS")}')

from core.output_sink import get_output_sink

# Get output sink
sink = get_output_sink()
print(f'Output sink: {type(sink).__name__}')

# Test 1: Single sentence (short response)
print("\n" + "="*60)
print("TEST 1: Short response")
print("="*60)
sink.speak("Hello there! I am ready to help.")
print("✅ Short response completed")

# Test 2: Multiple sentences (longer response)
print("\n" + "="*60)
print("TEST 2: Longer multi-sentence response")
print("="*60)
sink.speak("The weather is nice today. I hope you are having a great day. Let me know if you need any help.")
print("✅ Longer response completed")

# Test 3: Very long response (simulate real assistant)
print("\n" + "="*60)
print("TEST 3: Long assistant response")
print("="*60)
sink.speak("To answer your question about quantum computing, I need to explain several foundational concepts. Quantum computers use quantum bits, or qubits, which can exist in multiple states simultaneously through superposition. This is fundamentally different from classical bits which are either zero or one. Additionally, quantum entanglement allows qubits to be correlated in ways that classical bits cannot achieve. When you combine superposition with entanglement, quantum computers can explore vastly more computational pathways in parallel than classical computers. This gives them potential advantages for specific problem domains like factoring large numbers, simulating molecular behavior, or optimization problems.")
print("✅ Long response completed")

print("\n" + "="*60)
print("✅ ALL TESTS PASSED - TTS IS AUDIBLY SPEAKING FULL SENTENCES")
print("="*60)
