#!/usr/bin/env python3
"""Debug Jellyfin stream format."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.jellyfin_provider import get_jellyfin_provider
import requests

jellyfin = get_jellyfin_provider()
tracks = jellyfin.advanced_search(artist='Elton John')

if tracks:
    track = tracks[0]
    stream_url = jellyfin.get_play_url(track['jellyfin_id'])
    
    print("Testing Jellyfin stream...")
    print(f"URL: {stream_url}")
    
    # Test with HEAD
    resp = requests.head(stream_url)
    print(f'\nStatus: {resp.status_code}')
    print(f'Content-Type: {resp.headers.get("content-type", "unknown")}')
    print(f'Content-Length: {resp.headers.get("content-length", "unknown")}')
    
    # Get first chunk
    resp = requests.get(stream_url, stream=True, timeout=5)
    chunk = next(resp.iter_content(chunk_size=16))
    print(f'\nFirst 16 bytes (hex): {chunk.hex()}')
    print(f'First 16 bytes (text): {chunk}')
