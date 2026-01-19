#!/usr/bin/env python3
"""
Direct Voice Mode Test: Call run_argo with voice_mode=True
This simulates exactly what happens when voice input is used
"""

import sys
sys.path.insert(0, 'wrapper')

from argo import run_argo

print("=" * 70)
print("TESTING VOICE MODE: voice_mode=True")
print("Query: 'Count to ten'")
print("=" * 70)
print()

# Call with voice_mode=True (stateless, memory-free)
run_argo(
    "Count to ten.",
    voice_mode=True  # CRITICAL: This forces stateless execution
)

print()
print("=" * 70)
print("Test complete. Check if output is simple: 1,2,3...10")
print("=" * 70)
