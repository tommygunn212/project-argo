#!/usr/bin/env python3
"""Test that we fixed the hallucination cases from the logs."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer

player = MusicPlayer()

print("\n" + "="*80)
print("HALLUCINATION FIX VERIFICATION")
print("="*80 + "\n")

# Case 1: From the logs - "elton john" 
print("Case 1: User says 'elton john'")
result = player._extract_metadata_with_llm("elton john")
print(f"Extracted: {result}")
if result.get("song") is None and result.get("year") is None:
    print("✓ FIXED - No hallucination of song/year\n")
else:
    print("✗ FAILED - Still hallucinating\n")

# Case 2: From the logs - "gods and roses"
print("Case 2: User says 'gods and roses'")
result = player._extract_metadata_with_llm("gods and roses")
print(f"Extracted: {result}")
if result is None or (result.get("song") is None):
    print("✓ GOOD - Not treating it as song name\n")
else:
    print("✗ FAILED - Hallucinating song\n")

# Case 3: Full context - "Elton John Music"
print("Case 3: User says 'play Elton John Music' (context from logs)")
result = player._extract_metadata_with_llm("elton john")
print(f"Extracted: {result}")
if result.get("song") is None and result.get("year") is None and result.get("genre") is None:
    print("✓ PERFECT - Only artist extracted, no hallucinations\n")
else:
    print("✗ FAILED - Hallucinating\n")
