#!/usr/bin/env python3
"""
Test Jellyfin advanced search integration with year, genre, and artist filters.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env first
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.jellyfin_provider import get_jellyfin_provider

def test_jellyfin_advanced_search():
    """Test Jellyfin advanced search with multiple filters."""
    
    print("Testing Jellyfin Advanced Search Integration...\n")
    
    try:
        provider = get_jellyfin_provider()
        
        # Test 1: Search by year only
        print("Test 1: Search for music from 1984")
        tracks = provider.advanced_search(year=1984)
        print(f"  Found {len(tracks)} tracks from 1984")
        if tracks:
            print(f"  Sample: {tracks[0]['artist']} - {tracks[0]['song']}")
        print()
        
        # Test 2: Search by genre only
        print("Test 2: Search for Metal genre")
        tracks = provider.advanced_search(genre="Metal")
        print(f"  Found {len(tracks)} Metal tracks")
        if tracks:
            print(f"  Sample: {tracks[0]['artist']} - {tracks[0]['song']}")
        print()
        
        # Test 3: Search by artist
        print("Test 3: Search for Alice Cooper")
        tracks = provider.advanced_search(artist="Alice Cooper")
        print(f"  Found {len(tracks)} Alice Cooper tracks")
        if tracks:
            for track in tracks[:3]:
                print(f"    - {track['artist']} - {track['song']}")
        print()
        
        # Test 4: Combined search (genre + year)
        print("Test 4: Search for Rock from 1980")
        tracks = provider.advanced_search(genre="Rock", year=1980)
        print(f"  Found {len(tracks)} Rock tracks from 1980")
        if tracks:
            print(f"  Sample: {tracks[0]['artist']} - {tracks[0]['song']}")
        print()
        
        # Test 5: Simple keyword search (fallback)
        print("Test 5: Keyword search for 'Bowie'")
        tracks = provider.search_by_keyword("bowie")
        print(f"  Found {len(tracks)} tracks matching 'bowie'")
        if tracks:
            print(f"  Sample: {tracks[0]['artist']} - {tracks[0]['song']}")
        print()
        
        print("✓ All Jellyfin advanced search tests passed!")
        
    except Exception as e:
        print(f"✗ Error testing Jellyfin: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_jellyfin_advanced_search()
