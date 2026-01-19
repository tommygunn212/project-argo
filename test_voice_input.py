#!/usr/bin/env python3
"""Test voice input initialization from argo.py context"""

import sys
import os

# Simulate wrapper/argo.py context
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=== Testing voice input initialization ===\n")

print("Step 1: Test keyboard import")
try:
    import keyboard
    print("  ✓ keyboard imported successfully")
except ImportError as e:
    print(f"  ✗ ImportError: {e}")

print("\nStep 2: Test voice_input import")
try:
    import voice_input
    print("  ✓ voice_input imported successfully")
except ImportError as e:
    print(f"  ✗ ImportError: {e}")

print("\nStep 3: Test get_voice_input_ptt import")
try:
    from voice_input import get_voice_input_ptt
    print("  ✓ get_voice_input_ptt imported successfully")
except ImportError as e:
    print(f"  ✗ ImportError: {e}")

print("\n=== All imports successful ===")
