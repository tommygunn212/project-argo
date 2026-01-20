#!/usr/bin/env python3
"""Test artist/song extraction in rebuilt index."""

import sys
sys.path.insert(0, '.')

from core.music_index import get_music_index
from core.music_player import get_music_player

print("=" * 60)
print("ARTIST/SONG EXTRACTION TEST")
print("=" * 60)

print("\n[TEST 1] Loading index (will rebuild)...")
index = get_music_index()
print(f"Total tracks: {len(index.tracks)}")

# Count fields
artist_count = len([t for t in index.tracks if t.get("artist")])
song_count = len([t for t in index.tracks if t.get("song")])

print(f"\nExtraction stats:")
print(f"  Tracks with artist: {artist_count}")
print(f"  Tracks with song: {song_count}")

# Show samples with both artist and song
print(f"\n[TEST 2] Sample tracks with artist/song:")
samples = [t for t in index.tracks if t.get("artist") and t.get("song")][:5]
for t in samples:
    song = t["song"][:40].ljust(40)
    artist = t["artist"][:30]
    print(f"  {song} by {artist}")

# Test artist filtering
print(f"\n[TEST 3] Artist filtering:")
artist_counts = {}
for t in index.tracks:
    if t.get("artist"):
        artist = t["artist"]
        artist_counts[artist] = artist_counts.get(artist, 0) + 1

print(f"Unique artists: {len(artist_counts)}")

if artist_counts:
    top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"Top artists by track count:")
    for artist, count in top_artists:
        print(f"  {artist}: {count} tracks")
        
    # Test filtering by top artist
    if top_artists:
        test_artist = top_artists[0][0]
        filtered = index.filter_by_artist(test_artist)
        print(f"\nFiltering by '{test_artist}': {len(filtered)} tracks")

# Test song filtering
print(f"\n[TEST 4] Song filtering:")
songs_with_tracks = {}
for t in index.tracks:
    if t.get("song"):
        song = t["song"]
        songs_with_tracks[song] = songs_with_tracks.get(song, 0) + 1

print(f"Unique songs: {len(songs_with_tracks)}")

# Test player announcement
print(f"\n[TEST 5] Player announcements:")
player = get_music_player()

test_cases = [
    {"song": "Hotel California", "artist": "Eagles"},
    {"song": "Bohemian Rhapsody", "artist": None},
    {"song": None, "artist": "Pink Floyd"},
    {"song": "Song", "artist": "Artist", "name": "fallback.mp3"},
]

for track in test_cases:
    announcement = player._build_announcement(track)
    print(f"  {str(track):50} -> '{announcement}'")

print("\n" + "=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
