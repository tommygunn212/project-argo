#!/usr/bin/env python3
"""Debug the 'give me some pink floyd' case."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.music_player import MusicPlayer
from mock_jellyfin_provider import MockJellyfinProvider

player = MusicPlayer(provider=MockJellyfinProvider())
result = player._parse_music_keyword("give me some pink floyd")
print("Result:", result)
print("Artist:", repr(result.get("artist")))
