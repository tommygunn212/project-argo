#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer

player = MusicPlayer()

tests = [
    "rock from 1980",
    "rock 1980",
    "1980 rock",
]

for test in tests:
    result = player._extract_metadata_with_llm(test)
    print(f"'{test}' -> {result}")
