#!/usr/bin/env python3
"""
Direct test of advanced_search method.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.jellyfin_provider import get_jellyfin_provider

def test_advanced_search_direct():
    """Test advanced_search method directly."""
    
    provider = get_jellyfin_provider()
    
    # Test 1: Genre search
    print("Test 1: advanced_search(genre='Metal')")
    tracks = provider.advanced_search(genre="Metal")
    print(f"  Found {len(tracks)} tracks\n")
    
    # Test 2: Year search
    print("Test 2: advanced_search(year=1984)")
    tracks = provider.advanced_search(year=1984)
    print(f"  Found {len(tracks)} tracks\n")
    
    # Test 3: Artist search
    print("Test 3: advanced_search(artist='Alice Cooper')")
    tracks = provider.advanced_search(artist="Alice Cooper")
    print(f"  Found {len(tracks)} tracks\n")
    
    # Test 4: Combined
    print("Test 4: advanced_search(genre='Rock', year=1980)")
    tracks = provider.advanced_search(genre="Rock", year=1980)
    print(f"  Found {len(tracks)} tracks\n")

if __name__ == "__main__":
    test_advanced_search_direct()
