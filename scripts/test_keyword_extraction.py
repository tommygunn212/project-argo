#!/usr/bin/env python3
"""Test music keyword extraction with 'playing' variation."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.intent_parser import RuleBasedIntentParser

parser = RuleBasedIntentParser()

test_cases = [
    "play Elton John",
    "playing Guns in Roses",
    "playing guns and roses",
    "I'm playing Pink Floyd",
    "played some rock",
    "plays metal music",
    "can you play jazz",
]

print("Music Keyword Extraction Test\n")
print("=" * 80)

for text in test_cases:
    intent = parser.parse(text)
    print(f"\nText: '{text}'")
    print(f"  Intent: {intent.intent_type.value}")
    print(f"  Keyword: {repr(intent.keyword)}")
    print(f"  Confidence: {intent.confidence}")
