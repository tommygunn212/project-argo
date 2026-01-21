#!/usr/bin/env python3
"""
Debug Jellyfin advanced search API calls.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from core.jellyfin_provider import get_jellyfin_provider
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(message)s')

def test_jellyfin_debug():
    """Debug Jellyfin API calls."""
    
    print("Debugging Jellyfin Advanced Search Calls\n")
    
    provider = get_jellyfin_provider()
    
    # Test 1: Direct API call with genre parameter
    print("Test 1: Search for genre='Metal'")
    params = {
        "userId": provider.user_id,
        "includeItemTypes": "Audio",
        "recursive": "true",
        "fields": "PrimaryImageAspectRatio,SortName,Genres,ProductionYear",
        "Genres": "Metal",
        "limit": 10,
    }
    result = provider._api_call("/Items", params)
    if result:
        items = result.get("Items", [])
        print(f"  Found {len(items)} items")
        if items:
            item = items[0]
            print(f"  Sample: {item.get('Name')} (Genres: {item.get('Genres')})")
    print()
    
    # Test 2: With artist parameter
    print("Test 2: Search for artist='Alice Cooper'")
    params = {
        "userId": provider.user_id,
        "includeItemTypes": "Audio",
        "recursive": "true",
        "fields": "PrimaryImageAspectRatio,SortName,Genres,ProductionYear",
        "Artists": "Alice Cooper",
        "limit": 10,
    }
    result = provider._api_call("/Items", params)
    if result:
        items = result.get("Items", [])
        print(f"  Found {len(items)} items")
        if items:
            for item in items[:2]:
                print(f"    - {item.get('Name')} (Artist: {item.get('Artists')})")
    print()
    
    # Test 3: With year parameter
    print("Test 3: Search for year=1984")
    params = {
        "userId": provider.user_id,
        "includeItemTypes": "Audio",
        "recursive": "true",
        "fields": "PrimaryImageAspectRatio,SortName,Genres,ProductionYear",
        "Years": "1984",
        "limit": 10,
    }
    result = provider._api_call("/Items", params)
    if result:
        items = result.get("Items", [])
        print(f"  Found {len(items)} items")
        if items:
            item = items[0]
            print(f"  Sample: {item.get('Name')} (Year: {item.get('ProductionYear')})")
    print()

if __name__ == "__main__":
    test_jellyfin_debug()
